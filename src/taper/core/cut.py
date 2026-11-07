"""Cut a source file into tracks following a plan. Never touches the original.

Strategy (the point of the tool is to NOT lose quality):
- lossy sources (opus, aac, mp3, vorbis): stream copy, then verify the result with ffprobe;
  only if the cut is not precise (start or duration off by more than 2 codec frames) that
  single segment is re-encoded with the same codec, and a warning is reported;
- lossless sources (flac, alac, wav...): always re-encoded to FLAC, which is sample-accurate
  and loses nothing.

Seeking uses the OUTPUT-side `-ss` (after `-i`): with stream copy the input-side variant
starts at the previous container page and can begin hundreds of ms early. `-ss` is omitted for
segments starting at 0 (with it ffmpeg drops the first packet).

Known limit: a stream-copied cut is accurate to the codec frame (about 20 ms for opus), and
every Opus segment keeps the source's pre-skip (312 samples, ~6.5 ms) which decoders discard,
so copied tracks are NOT sample-exact gapless. Lossless sources (FLAC output) are.

All tracks are produced in a temporary folder inside the output folder and moved into place
only when every segment succeeded, so a failure leaves nothing behind.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from taper.core.ffmpeg import AudioInfo, ffarg, packet_duration_ms, probe_audio, run_ffmpeg
from taper.core.naming import track_filename
from taper.core.plan import ensure_valid
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.core.timestamps import format_time
from taper.errors import SourceError, TaperError
from taper.models import CutPlan, Segment

MODE_COPY = "copy"
MODE_LOSSLESS = "lossless"
MODE_REENCODE = "reencode"  # lossy -> lossy: the only mode that loses quality

DEFAULT_BITRATE = 128_000
TOLERANCE_FRAMES = 2


@dataclass(frozen=True)
class CodecProfile:
    ext: str  # extension of the produced tracks
    encoder: str  # ffmpeg encoder used when re-encoding
    lossless: bool
    frame_samples: int | None = None  # samples per codec frame (None: fixed `frame_ms`)
    frame_ms: float = 0.0


_PROFILES = {
    "opus": CodecProfile("opus", "libopus", False, frame_ms=20.0),
    "aac": CodecProfile("m4a", "aac", False, frame_samples=1024),
    "mp3": CodecProfile("mp3", "libmp3lame", False, frame_samples=1152),
    "vorbis": CodecProfile("ogg", "libvorbis", False, frame_samples=2048),
}
_LOSSLESS = CodecProfile("flac", "flac", True, frame_samples=4096)
_LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape", "tta"}


def profile_for(codec: str) -> CodecProfile:
    if codec in _PROFILES:
        return _PROFILES[codec]
    if codec in _LOSSLESS_CODECS or codec.startswith("pcm_"):
        return _LOSSLESS
    raise SourceError(
        f"Codec audio non supportato: '{codec}'.",
        "Formati gestiti: opus, aac/m4a, mp3, vorbis, flac e altri lossless (wav, alac).",
    )


def tolerance_ms(
    profile: CodecProfile, sample_rate: int | None, packet_ms: float | None = None
) -> float:
    """Allowed deviation of a stream-copied cut: 2 codec frames.

    `packet_ms` is the real packet size measured on the source (Opus may use 40/60 ms frames).
    """
    if profile.frame_samples and sample_rate:
        frame = profile.frame_samples / sample_rate * 1000
    else:
        frame = profile.frame_ms or 20.0
    if packet_ms:
        frame = max(frame, packet_ms)
    return TOLERANCE_FRAMES * frame


def copy_deviation(expected_ms: int, actual: AudioInfo, tol_ms: float) -> str | None:
    """Why a stream-copied segment is not precise enough, or None if it is (pure)."""
    if abs(actual.duration_ms - expected_ms) > tol_ms:
        return f"durata {format_time(actual.duration_ms)} invece di {format_time(expected_ms)}"
    if actual.start_time_ms is not None and abs(actual.start_time_ms) > tol_ms:
        return f"inizio sfasato di {actual.start_time_ms} ms"
    return None


@dataclass(frozen=True)
class CutResult:
    index: int  # 1-based
    segment: Segment
    path: Path
    mode: str
    audio_info: AudioInfo
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reencoded(self) -> bool:
        """True only when quality was lost (lossy -> lossy). Lossless->FLAC is not a loss."""
        return self.mode == MODE_REENCODE


def _part_name(name: str) -> str:
    # Keep the real extension last so ffmpeg picks the right muxer.
    stem, dot, ext = name.rpartition(".")
    return f"{stem}.part.{ext}" if dot else f"{name}.part"


def _times(start_ms: int, end_ms: int) -> list[str]:
    seek = ["-ss", f"{start_ms / 1000:.3f}"] if start_ms > 0 else []
    return [*seek, "-t", f"{(end_ms - start_ms) / 1000:.3f}"]


def _base_args(source: Path, start_ms: int, end_ms: int) -> list[str]:
    # -ss AFTER -i (see module docstring); drop video/cover, source tags and chapters.
    return ["-i", ffarg(source), *_times(start_ms, end_ms), "-map", "0:a:0", "-vn",
            "-map_metadata", "-1", "-map_chapters", "-1"]  # fmt: skip


def _encode(work: Path, name: str, args: list[str], cancel: threading.Event | None) -> AudioInfo:
    """Run ffmpeg into `work/<name>.part.ext`, probe it, then rename to `work/<name>`."""
    tmp = work / _part_name(name)
    try:
        run_ffmpeg([*args, ffarg(tmp)], cancel=cancel)
        info = probe_audio(tmp)
        tmp.replace(work / name)
        return info
    finally:
        tmp.unlink(missing_ok=True)


def _cut_one(
    source: Path,
    src: AudioInfo,
    profile: CodecProfile,
    tol_ms: float,
    index: int,
    seg: Segment,
    end_ms: int,
    work: Path,
    name: str,
    cancel: threading.Event | None,
) -> CutResult:
    base = _base_args(source, seg.start_ms, end_ms)
    expected = end_ms - seg.start_ms
    final = work / name

    if profile.lossless:
        info = _encode(work, name, [*base, "-c:a", "flac"], cancel)
        warnings = ()
        if src.codec.startswith("pcm_f"):  # float PCM has more precision than FLAC can store
            warnings = (
                f"Segmento {index} ('{seg.title}'): la sorgente è PCM float, FLAC la "
                "memorizza a 24 bit: possibile minima perdita di precisione.",
            )
        return CutResult(index, seg, final, MODE_LOSSLESS, info, warnings)

    # 1) stream copy into a temp file, verified before it is kept
    tmp = work / _part_name(name)
    reason: str | None = None
    try:
        run_ffmpeg([*base, "-c:a", "copy", ffarg(tmp)], cancel=cancel)
        info = probe_audio(tmp)
        reason = copy_deviation(expected, info, tol_ms)
        if reason is None:
            tmp.replace(final)
            return CutResult(index, seg, final, MODE_COPY, info)
    except SourceError as exc:  # empty/unreadable copy (e.g. a very short segment): fall back
        reason = f"copia non riuscita: {exc.message.splitlines()[0]}"
    finally:
        tmp.unlink(missing_ok=True)

    # 2) not precise: re-encode ONLY this segment with the same codec, and say so
    bitrate = src.bitrate or DEFAULT_BITRATE
    info = _encode(work, name, [*base, "-c:a", profile.encoder, "-b:a", str(bitrate)], cancel)
    warning = (
        f"Segmento {index} ('{seg.title}'): taglio senza ricodifica non preciso ({reason}); "
        f"ricodificato con {profile.encoder} a {bitrate // 1000} kbps: "
        "piccola perdita di qualità."
    )
    return CutResult(index, seg, final, MODE_REENCODE, info, (warning,))


def cut_plan(
    source: Path,
    plan: CutPlan,
    out_dir: Path,
    *,
    overwrite: bool = False,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> list[CutResult]:
    """Cut `source` into `out_dir/NN - Title.ext` following `plan` (all or nothing)."""
    src = probe_audio(source)
    ensure_valid(plan, src.duration_ms)
    profile = profile_for(src.codec)
    packet_ms = None if profile.lossless else packet_duration_ms(source)
    tol_ms = tolerance_ms(profile, src.sample_rate, packet_ms)
    total = len(plan.segments)

    targets = [
        out_dir / track_filename(i, seg.title, profile.ext, total=total)
        for i, seg in enumerate(plan.segments, start=1)
    ]
    source_resolved = source.resolve()
    if any(t.resolve() == source_resolved for t in targets):
        raise TaperError(
            "La destinazione coincide con il file originale.", "Scegli un'altra --out."
        )
    existing = [t for t in targets if t.exists()]
    if existing and not overwrite:
        raise TaperError(
            f"{len(existing)} file di destinazione esistono già in '{out_dir}' "
            f"(es. '{existing[0].name}').",
            "Usa --force per rigenerarli o scegli un'altra --out.",
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix=".taper-cut-", dir=out_dir))
    try:
        produced: list[CutResult] = []
        for i, (seg, target) in enumerate(zip(plan.segments, targets, strict=True), start=1):
            check_cancelled(cancel)
            emit(on_event, ProgressEvent("cut", (i - 1) / total, f"{i}/{total} {seg.title}"))
            end_ms = min(seg.end_ms, src.duration_ms)
            produced.append(
                _cut_one(source, src, profile, tol_ms, i, seg, end_ms, work, target.name, cancel)
            )
        results = []
        for r, target in zip(produced, targets, strict=True):  # commit: move into place
            os.replace(r.path, target)
            results.append(replace(r, path=target))
    finally:
        shutil.rmtree(work, ignore_errors=True)  # nothing is left behind on failure
    emit(on_event, ProgressEvent("cut_done", 1.0, "Taglio completato"))
    return results
