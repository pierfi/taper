"""High-level operations the CLI (and later the web UI) call. No printing, no prompts."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from taper.config import ensure_library_allowed
from taper.core.cover import CoverImage, find_cover_source, make_square_cover, save_cover_jpg
from taper.core.cut import CutResult, cut_plan
from taper.core.export import COVER_FILENAME, ExportResult, export_to_library
from taper.core.fetch import FetchResult
from taper.core.fetch import fetch as fetch_source
from taper.core.library import file_sha256, find_source
from taper.core.plan import (
    PlanOptions,
    apply_album_override,
    generate_plan,
    load_plan,
    save_plan,
)
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.core.tagging import tags_for_plan, write_tags
from taper.errors import TaperError
from taper.models import AlbumMeta, CutPlan, SourceInfo


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
    emit(on_event, ProgressEvent("tag_done", 1.0, "Tag scritti"))
    return CutAndTagResult(results, cover, notes)


@dataclass
class ApplyResult:
    results: list[CutResult]
    cover: CoverImage | None
    notes: list[str]
    export: ExportResult | None = None  # None when no library was requested
    cover_path: Path | None = None  # the cover.jpg written next to the tracks / in the album


def check_duplicate(source: Path, library: Path, *, allow_duplicate: bool = False) -> str:
    """Hash of `source`; raises if it is already in the library (unless allowed).

    Call it before spending time cutting (and before asking the user to review a plan).
    """
    ensure_library_allowed(library)
    source_hash = file_sha256(source)
    existing = find_source(library, source_hash)
    if existing and not allow_duplicate:
        raise TaperError(
            f"Questa sorgente è già in libreria ('{existing.title}', {existing.track_count} "
            f"brani, aggiunta il {existing.added_at}; es. {existing.first_path}).",
            "Usa --allow-duplicate per esportarla di nuovo in una nuova cartella.",
        )
    return source_hash


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
        source_hash = check_duplicate(source, library, allow_duplicate=allow_duplicate)

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
    if export is not None:
        cover_path = export.cover
    elif outcome.cover is not None:
        # No library: still leave a cover.jpg next to the tracks (never overwriting one).
        cover_path = staging_dir / COVER_FILENAME
        if not cover_path.exists():
            save_cover_jpg(outcome.cover, cover_path)
    else:
        cover_path = None
    emit(on_event, ProgressEvent("done", 1.0, "Fatto"))
    return ApplyResult(outcome.results, outcome.cover, outcome.notes, export, cover_path)


@dataclass
class Prepared:
    """Everything `run` needs to show the plan for review (nothing has been cut yet)."""

    fetch: FetchResult
    plan: CutPlan
    plan_path: Path
    source: str  # "chapters" / "description" / "silence", or "existing" for a reused plan
    notes: list[str]

    @property
    def audio(self) -> Path:
        return self.fetch.audio


def prepare(
    url: str,
    root: Path,
    *,
    options: PlanOptions | None = None,
    album_override: AlbumMeta | None = None,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> Prepared:
    """Download (or reuse) the source and produce its plan file. Never cuts anything.

    An existing `<id>.plan.yaml` is reused, so hand edits are never lost; explicit
    `album_override` values (--artist/--album/--year) are applied to it and saved.
    """
    fetched = fetch_source(url, root, on_event=on_event, cancel=cancel)
    plan_path = fetched.audio.with_name(fetched.audio.stem + ".plan.yaml")
    if plan_path.exists():
        plan = load_plan(plan_path)
        notes = ["Piano esistente riutilizzato (le tue modifiche sono conservate)."]
        if album_override and any(
            (album_override.artist, album_override.album, album_override.year)
        ):
            plan.album = apply_album_override(plan.album, album_override)
            save_plan(plan, plan_path, overwrite=True)
            notes.append("Artista/album/anno forniti da riga di comando applicati al piano.")
        emit(on_event, ProgressEvent("prepared", 1.0, "Piano pronto"))
        return Prepared(fetched, plan, plan_path, "existing", notes)

    result = generate_plan(
        fetched.audio,
        fetched.info,
        fetched.audio_info.duration_ms,
        options,
        album_override=album_override,
        cancel=cancel,
    )
    save_plan(result.plan, plan_path, result.notes)
    emit(on_event, ProgressEvent("prepared", 1.0, "Piano pronto"))
    return Prepared(fetched, result.plan, plan_path, result.source, result.notes)
