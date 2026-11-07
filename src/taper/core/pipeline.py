"""High-level operations the CLI (and later the web UI) call. No printing, no prompts."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from taper.core.cover import CoverImage, find_cover_source, make_square_cover
from taper.core.cut import CutResult, cut_plan
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.core.tagging import tags_for_plan, write_tags
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
