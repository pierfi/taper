"""High-level operations the CLI (and later the web UI) call. No printing, no prompts."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from taper.config import ensure_library_allowed
from taper.core.cover import CoverImage, find_cover_source, make_square_cover
from taper.core.cut import CutResult, cut_plan
from taper.core.export import ExportResult, export_to_library
from taper.core.library import file_sha256, find_source
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.core.tagging import tags_for_plan, write_tags
from taper.errors import TaperError
from taper.models import CutPlan, SourceInfo


@dataclass
class CutAndTagResult:
    results: list[CutResult]
    cover: CoverImage | None = None
    notes: list[str] = field(default_factory=list)


def cut_and_tag(
    source: Path,
    plan: CutPlan,
    out_dir: Path,
    *,
    info: SourceInfo | None = None,
    embed_cover: bool = True,
    overwrite: bool = False,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> CutAndTagResult:
    """Cut the plan's segments, then tag every track and embed the square cover."""
    notes: list[str] = []
    cover: CoverImage | None = None
    if embed_cover:
        image = find_cover_source(source, info.thumbnail if info else None)
        if image is None:
            notes.append("Nessuna copertina trovata: i brani non avranno immagine incorporata.")
        else:
            cover = make_square_cover(image)  # fail early, before any file is written
    if not plan.album.artist:
        notes.append("album.artist è vuoto: i brani non avranno il tag artista.")

    results = cut_plan(source, plan, out_dir, overwrite=overwrite, on_event=on_event, cancel=cancel)

    total = len(results)
    for r in results:
        check_cancelled(cancel)
        emit(
            on_event,
            ProgressEvent("tag", (r.index - 1) / total, f"{r.index}/{total} {r.segment.title}"),
        )
        write_tags(r.path, tags_for_plan(plan, r.index), cover)
    emit(on_event, ProgressEvent("done", 1.0, "Tag scritti"))
    return CutAndTagResult(results, cover, notes)


@dataclass
class ApplyResult:
    results: list[CutResult]
    cover: CoverImage | None
    notes: list[str]
    export: ExportResult | None = None  # None when no library was requested


def apply_plan(
    source: Path,
    plan: CutPlan,
    staging_dir: Path,
    *,
    library: Path | None = None,
    info: SourceInfo | None = None,
    embed_cover: bool = True,
    overwrite: bool = False,
    allow_duplicate: bool = False,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> ApplyResult:
    """Cut + tag, and (if `library` is given) export to the library and register in SQLite.

    With `library=None` the tagged tracks simply stay in `staging_dir`.
    """
    source_hash = None
    if library is not None:
        ensure_library_allowed(library)
        source_hash = file_sha256(source)
        existing = find_source(library, source_hash)  # fail BEFORE spending time cutting
        if existing and not allow_duplicate:
            raise TaperError(
                f"Questa sorgente è già in libreria ('{existing.title}', {existing.track_count} "
                f"brani, aggiunta il {existing.added_at}; es. {existing.first_path}).",
                "Usa --allow-duplicate per esportarla di nuovo in una nuova cartella.",
            )

    outcome = cut_and_tag(
        source, plan, staging_dir, info=info, embed_cover=embed_cover,
        overwrite=overwrite, on_event=on_event, cancel=cancel,
    )  # fmt: skip
    export = None
    if library is not None:
        export = export_to_library(
            library, plan, outcome.results,
            source_hash=source_hash, source_title=info.title if info else source.stem,
            info=info, cover=outcome.cover, on_event=on_event, cancel=cancel,
        )  # fmt: skip
    return ApplyResult(outcome.results, outcome.cover, outcome.notes, export)
