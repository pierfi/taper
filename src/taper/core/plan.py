"""Build, write, read and validate cut plans.

Sources, in priority order: video chapters > description timestamps > silence detection.
Plans are YAML files meant to be edited by hand: times and titles are always written
quoted, because PyYAML would read an unquoted `1:02:33` as the integer 3753 and a title
like `No` as a boolean.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from taper.core.ffmpeg import detect_silences
from taper.core.timestamps import (
    format_short,
    format_time,
    parse_description_timestamps,
    parse_time,
)
from taper.errors import InvalidPlanError, TaperError
from taper.models import (
    PLAN_VERSION,
    SOURCE_CHAPTERS,
    SOURCE_DESCRIPTION,
    SOURCE_SILENCE,
    AlbumMeta,
    Chapter,
    CutPlan,
    Segment,
    SourceInfo,
)

DEFAULT_SILENCE_DB = -30.0
DEFAULT_SILENCE_MIN_S = 2.0
DEFAULT_MIN_SEGMENT_S = 30.0
SOURCE_CHOICES = ("auto", SOURCE_CHAPTERS, SOURCE_DESCRIPTION, SOURCE_SILENCE)

# Tolerance when checking that a segment does not run past the end of the audio.
END_TOLERANCE_MS = 1000

SilenceDetector = Callable[..., list[tuple[int, int]]]


@dataclass(frozen=True)
class PlanOptions:
    source: str = "auto"
    silence_db: float = DEFAULT_SILENCE_DB
    silence_min_s: float = DEFAULT_SILENCE_MIN_S
    min_segment_s: float = DEFAULT_MIN_SEGMENT_S


@dataclass
class PlanResult:
    plan: CutPlan
    source: str  # which source produced the segments
    notes: list[str] = field(default_factory=list)  # things the user should double-check


# --------------------------------------------------------------------------- segments


def _default_title(index: int) -> str:
    return f"Track {index:02d}"


def segments_from_chapters(chapters: list[Chapter], duration_ms: int) -> list[Segment]:
    segments: list[Segment] = []
    for ch in sorted(chapters, key=lambda c: c.start_ms):
        start, end = max(0, ch.start_ms), min(ch.end_ms, duration_ms)
        if end <= start:
            continue
        title = ch.title.strip() or _default_title(len(segments) + 1)
        segments.append(Segment(start, end, title, SOURCE_CHAPTERS))
    return segments if len(segments) >= 2 else []


def segments_from_description(description: str, duration_ms: int) -> list[Segment]:
    entries = [e for e in parse_description_timestamps(description) if e.start_ms < duration_ms]
    segments: list[Segment] = []
    for i, entry in enumerate(entries):
        next_start = entries[i + 1].start_ms if i + 1 < len(entries) else duration_ms
        # Explicit range ends are honoured; otherwise segments are contiguous (gapless).
        end = min(entry.end_ms, next_start) if entry.end_ms else next_start
        title = entry.title or _default_title(i + 1)
        segments.append(Segment(entry.start_ms, min(end, duration_ms), title, SOURCE_DESCRIPTION))
    return segments if len(segments) >= 2 else []


def segments_from_silences(
    silences: list[tuple[int, int]], duration_ms: int, min_segment_ms: int
) -> list[Segment]:
    """Cut in the middle of each silence, merging segments shorter than `min_segment_ms`."""
    cuts = sorted((s + e) // 2 for s, e in silences)
    cuts = [c for c in cuts if 0 < c < duration_ms]
    spans: list[list[int]] = []
    start = 0
    for cut in cuts:
        if cut - start >= min_segment_ms:
            spans.append([start, cut])
            start = cut
    if spans and duration_ms - start < min_segment_ms:
        spans[-1][1] = duration_ms  # too short a tail: merge it into the last segment
    else:
        spans.append([start, duration_ms])
    return [
        Segment(s, e, _default_title(i), SOURCE_SILENCE) for i, (s, e) in enumerate(spans, start=1)
    ]


# ----------------------------------------------------------------------- generation


def apply_album_override(album: AlbumMeta, override: AlbumMeta | None) -> AlbumMeta:
    """Fields set in `override` (artist/album/year given by the user) win over `album`."""
    if override is None:
        return album
    return AlbumMeta(
        artist=override.artist or album.artist,
        album=override.album or album.album,
        year=override.year or album.year,
    )


def generate_plan(
    audio: Path,
    info: SourceInfo | None,
    duration_ms: int,
    options: PlanOptions | None = None,
    *,
    detector: SilenceDetector | None = None,
    album_override: AlbumMeta | None = None,
) -> PlanResult:
    """Create a plan for `audio` (`info` is None for local files without a sidecar)."""
    options = options or PlanOptions()
    if options.source not in SOURCE_CHOICES:
        raise TaperError(
            f"Sorgente non valida: {options.source!r}",
            f"Valori ammessi: {', '.join(SOURCE_CHOICES)}",
        )
    detector = detector or detect_silences
    wanted = options.source
    notes: list[str] = []
    segments: list[Segment] = []
    used = ""

    def try_source(name: str) -> bool:
        nonlocal segments, used
        if wanted not in ("auto", name):
            return False
        if name == SOURCE_CHAPTERS:
            found = segments_from_chapters(info.chapters, duration_ms) if info else []
        elif name == SOURCE_DESCRIPTION:
            found = segments_from_description(info.description, duration_ms) if info else []
        else:
            silences = detector(
                audio,
                noise_db=options.silence_db,
                min_silence_s=options.silence_min_s,
                duration_ms=duration_ms,
            )
            found = segments_from_silences(
                silences, duration_ms, round(options.min_segment_s * 1000)
            )
        if found:
            segments, used = found, name
        return bool(found)

    for name in (SOURCE_CHAPTERS, SOURCE_DESCRIPTION, SOURCE_SILENCE):
        if try_source(name):
            break
    if not segments:
        raise TaperError(
            f"Nessun taglio trovato con la sorgente '{wanted}'.",
            "Prova un'altra --source o scrivi il piano a mano.",
        )

    if used == SOURCE_SILENCE:
        if len(segments) == 1:
            notes.append(
                "Nessun silenzio utile trovato: piano con un solo segmento. "
                "Nei concerti tra un brano e l'altro ci sono spesso applausi, non silenzio: "
                "prova --silence-db più alto (es. -25) o dividi a mano."
            )
        else:
            notes.append(
                "Tagli da silenzi: controlla i confini, nei live possono essere imprecisi."
            )
    if segments[0].start_ms >= 5000:
        head = format_short(segments[0].start_ms)
        notes.append(f"I primi {head} dell'audio non sono coperti da nessun segmento.")

    album = AlbumMeta(
        artist=info.default_artist if info else None,
        album=info.title if info else audio.stem,
        year=info.default_year if info else None,
    )
    override = album_override or AlbumMeta()
    if info and not (info.artist or info.creator) and info.uploader and not override.artist:
        notes.append(
            f"Artista ricavato dal canale '{info.uploader}': "
            "probabilmente va corretto in 'album.artist' (o con --artist)."
        )
    if info and info.upload_date and not override.year:
        notes.append(
            f"Anno ricavato dalla data di upload ({info.upload_date}): "
            "potrebbe non essere l'anno del concerto (--year)."
        )
    if info and info.title and not override.album:
        notes.append(
            "Il titolo dell'album è il titolo del video: sistemalo in 'album.album' (--album)."
        )
    album = apply_album_override(album, override)

    plan = CutPlan(source_file=audio.name, album=album, segments=segments)
    return PlanResult(plan, used, notes)


# ------------------------------------------------------------------------------ YAML

_HEADER = """\
# taper cut plan — modificabile a mano.
# Poi: taper cut <file> --plan <questo file>
#
# - start/end sono stringhe "H:MM:SS.mmm" (anche "M:SS" o secondi); tienile tra virgolette.
# - I segmenti devono essere in ordine e non sovrapposti.
# - 'source' dice da dove arriva ogni taglio (chapters, description, silence, manual).
"""


def _q(value: str) -> str:
    """A YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    return _q(str(value))


def dump_plan(plan: CutPlan, notes: list[str] | None = None) -> str:
    lines = [_HEADER.rstrip("\n")]
    if notes:
        lines += ["#", "# DA VERIFICARE:"] + [f"#  * {n}" for n in notes]
    lines += [
        "",
        f"version: {plan.version}",
        f"source_file: {_q(plan.source_file)}",
        "album:",
        f"  artist: {_scalar(plan.album.artist)}",
        f"  album: {_scalar(plan.album.album)}",
        f"  year: {_scalar(plan.album.year)}",
        "segments:",
    ]
    for seg in plan.segments:
        lines += [
            f"  - start: {_q(format_time(seg.start_ms))}",
            f"    end: {_q(format_time(seg.end_ms))}",
            f"    title: {_q(seg.title)}",
            f"    source: {seg.source}",
        ]
    return "\n".join(lines) + "\n"


def save_plan(
    plan: CutPlan, path: Path, notes: list[str] | None = None, *, overwrite: bool = False
) -> Path:
    """Write the plan atomically. Never clobbers an existing (maybe hand-edited) plan."""
    if path.exists() and not overwrite:
        raise TaperError(
            f"Il piano '{path}' esiste già.",
            "Usa --force per sovrascriverlo o scegli un altro --out.",
        )
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(dump_plan(plan, notes), encoding="utf-8")
    tmp.replace(path)
    return path


def _time_value(value: Any) -> int:
    """YAML may hand us int/float seconds (sexagesimal) or a string."""
    if isinstance(value, bool) or value is None:
        raise ValueError("valore mancante o non valido")
    if isinstance(value, int | float):
        if value < 0:
            raise ValueError("tempo negativo")
        return round(value * 1000)
    if isinstance(value, str):
        return parse_time(value)
    raise ValueError(f"tipo non valido: {type(value).__name__}")


def plan_from_data(data: Any) -> CutPlan:
    """Build a CutPlan from parsed YAML, collecting EVERY structural problem."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise InvalidPlanError(["il file deve contenere una mappa YAML"])

    version = data.get("version", PLAN_VERSION)
    if version != PLAN_VERSION:
        problems.append(f"versione del piano non supportata: {version!r}")
    source_file = data.get("source_file")
    if not isinstance(source_file, str) or not source_file:
        problems.append("'source_file' mancante")
        source_file = ""

    album_data = data.get("album") or {}
    album = AlbumMeta()
    if not isinstance(album_data, dict):
        problems.append("'album' deve essere una mappa")
    else:
        for key in ("artist", "album"):
            val = album_data.get(key)
            if val is not None and not isinstance(val, str):
                problems.append(f"album.{key} deve essere testo (usa le virgolette)")
        year = album_data.get("year")
        if year is not None:
            if isinstance(year, bool) or not (
                isinstance(year, int) or (isinstance(year, str) and year.strip().isdigit())
            ):
                problems.append(f"album.year non valido: {year!r}")
                year = None
            else:
                year = int(year)
        album = AlbumMeta(
            artist=album_data.get("artist") if isinstance(album_data.get("artist"), str) else None,
            album=album_data.get("album") if isinstance(album_data.get("album"), str) else None,
            year=year,
        )

    raw_segments = data.get("segments")
    segments: list[Segment] = []
    if not isinstance(raw_segments, list) or not raw_segments:
        problems.append("'segments' mancante o vuoto")
        raw_segments = []
    for i, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, dict):
            problems.append(f"segmento {i}: deve essere una mappa")
            continue
        ok = True
        times: dict[str, int] = {}
        for key in ("start", "end"):
            try:
                times[key] = _time_value(raw.get(key))
            except ValueError as exc:
                problems.append(f"segmento {i}: '{key}' {exc}")
                ok = False
        title = raw.get("title")
        if not isinstance(title, str):
            problems.append(f"segmento {i}: 'title' deve essere testo (usa le virgolette)")
            ok = False
        if ok:
            segments.append(
                Segment(times["start"], times["end"], title, str(raw.get("source") or "manual"))
            )
    if problems:
        raise InvalidPlanError(problems)
    return CutPlan(source_file=source_file, album=album, segments=segments, version=version)


def load_plan(path: Path) -> CutPlan:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TaperError(f"Impossibile leggere il piano '{path}': {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise InvalidPlanError([f"YAML non valido: {exc}"]) from exc
    return plan_from_data(data)


# ------------------------------------------------------------------------ validation


def validate_plan(plan: CutPlan, duration_ms: int | None = None) -> list[str]:
    """All problems found in the plan (empty list = valid). Segment numbers are 1-based."""
    problems: list[str] = []
    if not plan.segments:
        return ["il piano non ha segmenti"]
    previous_end = 0
    for i, seg in enumerate(plan.segments, start=1):
        if seg.start_ms < 0:
            problems.append(f"segmento {i}: start negativo")
        if seg.end_ms <= seg.start_ms:
            problems.append(
                f"segmento {i} ('{seg.title}'): end ({format_time(seg.end_ms)}) "
                f"deve essere dopo start ({format_time(seg.start_ms)})"
            )
        if not seg.title.strip():
            problems.append(f"segmento {i}: titolo vuoto")
        if seg.start_ms < previous_end:
            problems.append(
                f"segmento {i} ('{seg.title}'): inizia a {format_time(seg.start_ms)} "
                f"prima della fine del precedente ({format_time(previous_end)})"
            )
        if duration_ms is not None and seg.end_ms > duration_ms + END_TOLERANCE_MS:
            problems.append(
                f"segmento {i} ('{seg.title}'): end ({format_time(seg.end_ms)}) "
                f"oltre la durata dell'audio ({format_time(duration_ms)})"
            )
        previous_end = max(previous_end, seg.end_ms)
    year = plan.album.year
    if year is not None and not 1000 <= year <= 2200:
        problems.append(f"album.year fuori intervallo: {year}")
    return problems


def ensure_valid(plan: CutPlan, duration_ms: int | None = None) -> None:
    problems = validate_plan(plan, duration_ms)
    if problems:
        raise InvalidPlanError(problems)
