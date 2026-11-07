"""Download the best audio stream with yt-dlp, keeping the NATIVE codec (no re-encoding)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from taper.core.ffmpeg import AudioInfo, ffarg, find_tool, probe_audio, run_ffmpeg
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.core.sidecar import load_sidecar, save_sidecar, sidecar_path
from taper.errors import CancelledError, SourceError
from taper.models import Chapter, SourceInfo

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass(frozen=True)
class FetchResult:
    workdir: Path
    audio: Path
    sidecar: Path
    thumbnail: Path | None
    info: SourceInfo
    audio_info: AudioInfo


def _seconds_to_ms(value: Any) -> int | None:
    try:
        return round(float(value) * 1000)
    except (TypeError, ValueError):
        return None


def source_info_from_ydl(
    data: dict[str, Any], *, thumbnail: str | None = None, url: str | None = None
) -> SourceInfo:
    """Map a yt-dlp info dict to our serializable SourceInfo (pure)."""
    chapters = []
    for ch in data.get("chapters") or []:
        start, end = _seconds_to_ms(ch.get("start_time")), _seconds_to_ms(ch.get("end_time"))
        if start is None or end is None:
            continue
        chapters.append(Chapter(start, end, str(ch.get("title") or "")))
    return SourceInfo(
        title=str(data.get("title") or data.get("id") or "Untitled"),
        url=url or data.get("webpage_url") or data.get("original_url"),
        uploader=data.get("uploader") or data.get("channel"),
        artist=data.get("artist"),
        creator=data.get("creator"),
        upload_date=data.get("upload_date"),
        description=data.get("description") or "",
        duration_ms=_seconds_to_ms(data.get("duration")),
        chapters=chapters,
        thumbnail=thumbnail,
    )


class _EventLogger:
    """yt-dlp would print its own 'ERROR: ...' on top of ours, so errors are left to us.

    Warnings are NOT swallowed: some change what is downloaded (e.g. falling back to a
    different format), so they are forwarded as `warning` events.
    """

    def __init__(self, on_event: ProgressCallback | None) -> None:
        self._on_event = on_event
        self._seen: set[str] = set()

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None:
        clean = re.sub(r"^\s*WARNING:\s*", "", msg).strip()
        if clean and clean not in self._seen:
            self._seen.add(clean)
            emit(self._on_event, ProgressEvent("warning", None, clean))


_UPDATE_HINT = (
    "Aggiorna yt-dlp ('uv lock --upgrade-package yt-dlp' poi 'uv sync'); "
    "per YouTube può servire anche un runtime JavaScript esterno (es. deno)."
)


def describe_download_error(text: str, url: str) -> tuple[str, str | None]:
    """Turn a yt-dlp error into (message, hint) the user can act on (pure)."""
    clean = re.sub(r"^(\s*ERROR:\s*)+", "", text.strip())
    low = clean.lower()
    if "unsupported url" in low:
        return (
            f"URL non supportato: {url}",
            "Controlla l'indirizzo; 'yt-dlp --list-extractors' elenca le fonti supportate.",
        )
    if "is not a valid url" in low:
        return (
            f"URL non valido: {url}",
            "Serve un indirizzo completo, ad esempio https://www.youtube.com/watch?v=...",
        )
    if "http error 404" in low:
        return f"Pagina non trovata (404): {url}", "Controlla l'indirizzo."
    if any(
        k in low for k in ("name resolution", "getaddrinfo", "network is unreachable", "timed out")
    ):
        return "Connessione non riuscita.", "Controlla la connessione a internet e riprova."
    if any(k in low for k in ("private video", "members-only", "sign in", "confirm your age")):
        return (
            "Contenuto non accessibile senza accesso (privato, per iscritti o con limite d'età).",
            "taper non gestisce login o cookie: usa un contenuto pubblico.",
        )
    if any(
        k in low for k in ("video unavailable", "this video is not available", "has been removed")
    ):
        return (
            "Video non disponibile (rimosso, privato o bloccato nel tuo paese).",
            "Controlla l'indirizzo aprendolo nel browser.",
        )
    return f"Download fallito: {clean}", _UPDATE_HINT


def build_ydl_options(
    root: Path,
    progress_hooks: list[Any] | None = None,
    on_event: ProgressCallback | None = None,
) -> dict[str, Any]:
    """yt-dlp options: best audio as downloaded (no post-processing), one work dir per id.

    There is deliberately NO FFmpegExtractAudio post-processor: for codecs it does not know
    (ac3, eac3, dts, pcm...) it silently re-encodes to mp3. `remux_native` does the container
    change with stream copy instead.
    """
    root_escaped = str(root).replace("%", "%%")  # outtmpl treats % specially
    return {
        "format": "bestaudio/best",
        "outtmpl": {"default": f"{root_escaped}/%(id)s/%(id)s.%(ext)s"},
        "noplaylist": True,
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": False,  # warnings go to our logger, which forwards them as events
        "noprogress": True,
        "logger": _EventLogger(on_event),
        "progress_hooks": progress_hooks or [],
    }


def find_thumbnail(workdir: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        candidate = workdir / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def _audio_path_from(info: dict[str, Any]) -> Path:
    downloads = info.get("requested_downloads") or []
    filepath = downloads[0].get("filepath") if downloads else None
    filepath = filepath or info.get("filepath")
    if not filepath:
        raise SourceError("yt-dlp non ha prodotto alcun file audio.")
    return Path(filepath)


AUDIO_EXTENSIONS = (".opus", ".m4a", ".mp3", ".ogg", ".flac", ".wav")

# Native container (extension) for each audio codec we can keep as it is.
_NATIVE_EXTENSION = {
    "opus": ".opus",
    "aac": ".m4a",
    "mp3": ".mp3",
    "vorbis": ".ogg",
    "flac": ".flac",
    "alac": ".m4a",
}


def native_extension(codec: str) -> str | None:
    """File extension that holds `codec` as it is, or None if taper cannot keep it (pure)."""
    if codec.startswith("pcm_"):
        return ".wav"
    return _NATIVE_EXTENSION.get(codec)


def remux_native(src: Path, *, cancel: threading.Event | None = None) -> Path:
    """Move the audio stream of `src` (webm, mp4, mkv...) into its native container, by COPY.

    Never re-encodes. A codec taper cannot keep stops with a clear error instead.
    """
    codec = probe_audio(src).codec
    ext = native_extension(codec)
    if ext is None:
        raise SourceError(
            f"Il codec audio '{codec}' non è supportato da taper.",
            "taper non ricodifica mai in silenzio: scarica il file con yt-dlp in un formato "
            "opus/aac/mp3/vorbis/flac, oppure convertilo tu e usa 'taper plan' / 'taper cut'.",
        )
    target = src.with_suffix(ext)
    tmp = src.with_name(f"{src.stem}.part{ext}")
    try:
        run_ffmpeg(
            [
                "-i",
                ffarg(src),
                "-map",
                "0:a:0",
                "-vn",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-c:a",
                "copy",
                ffarg(tmp),
            ],  # fmt: skip
            cancel=cancel,
        )
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    if target != src:
        src.unlink(missing_ok=True)
    return target


def find_existing(root: Path, video_id: str) -> FetchResult | None:
    """A complete earlier download of `video_id` (audio + sidecar), if there is one."""
    workdir = root / video_id
    audio = next(
        (
            workdir / f"{video_id}{ext}"
            for ext in AUDIO_EXTENSIONS
            if (workdir / f"{video_id}{ext}").is_file()
        ),
        None,
    )
    info = load_sidecar(audio) if audio else None
    if audio is None or info is None:
        return None
    thumb = find_thumbnail(workdir, audio.stem)
    return FetchResult(workdir, audio, sidecar_path(audio), thumb, info, probe_audio(audio))


def fetch(
    url: str,
    root: Path,
    *,
    reuse: bool = True,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> FetchResult:
    """Download `url` into `root/<video id>/` and write the metadata sidecar.

    With `reuse` (default) a complete earlier download is returned as is, without
    downloading again.
    """
    find_tool("ffmpeg")
    find_tool("ffprobe")
    check_cancelled(cancel)

    def hook(status: dict[str, Any]) -> None:
        check_cancelled(cancel)
        state = status.get("status")
        if state == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            done = status.get("downloaded_bytes")
            fraction = done / total if total and done is not None else None
            emit(on_event, ProgressEvent("download", fraction, "Download in corso"))
        elif state == "finished":
            emit(
                on_event,
                ProgressEvent("postprocess", None, "Estrazione audio (copia, senza ricodifica)"),
            )

    options = build_ydl_options(root, [hook], on_event)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            if reuse:
                meta = ydl.extract_info(url, download=False)
                existing = find_existing(root, str(meta["id"])) if meta and meta.get("id") else None
                if existing:
                    emit(on_event, ProgressEvent("fetch_done", 1.0, "Già scaricato: riuso il file"))
                    return existing
                # Reuse the metadata we already have instead of extracting it a second time.
                data = ydl.process_ie_result(meta, download=True) if meta else None
            else:
                data = ydl.extract_info(url, download=True)
    except CancelledError:
        raise
    except DownloadError as exc:
        check_cancelled(cancel)  # yt-dlp may wrap an exception raised by our hook
        message, hint = describe_download_error(str(exc), url)
        raise SourceError(message, hint) from exc

    if data is None:
        raise SourceError(f"Nessun risultato per {url}")

    audio = remux_native(_audio_path_from(data), cancel=cancel)
    workdir = audio.parent
    thumb = find_thumbnail(workdir, audio.stem)
    info = source_info_from_ydl(data, thumbnail=thumb.name if thumb else None, url=url)
    sidecar = save_sidecar(info, audio)
    audio_info = probe_audio(audio)
    emit(on_event, ProgressEvent("fetch_done", 1.0, "Download completato"))
    return FetchResult(workdir, audio, sidecar, thumb, info, audio_info)
