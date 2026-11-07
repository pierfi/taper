"""Move finished tracks into the library as `Artist/Year - Album/NN - Title.ext`.

Nothing is ever overwritten or merged: an album folder that already exists gets a
` (2)` suffix. Files are copied to `.part` and renamed; the staging copies are deleted only
after the database registration succeeded, and a failure rolls everything back.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from taper.config import ensure_library_allowed
from taper.core.cover import CoverImage, save_cover_jpg
from taper.core.cut import CutResult
from taper.core.library import SourceRecord, register
from taper.core.naming import album_dirname, artist_dirname, create_unique_dir
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.models import CutPlan, SourceInfo, Track

COVER_FILENAME = "cover.jpg"


@dataclass(frozen=True)
class ExportResult:
    album_dir: Path
    tracks: list[Track]
    cover: Path | None


def _copy_atomic(src: Path, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".part")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def export_to_library(
    root: Path,
    plan: CutPlan,
    results: list[CutResult],
    *,
    source_hash: str,
    source_title: str,
    info: SourceInfo | None = None,
    cover: CoverImage | None = None,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> ExportResult:
    ensure_library_allowed(root)
    root.mkdir(parents=True, exist_ok=True)

    artist_dir = root / artist_dirname(plan.album.artist)
    album_dir = create_unique_dir(
        artist_dir / album_dirname(plan.album.year, plan.album.album or "Unknown Album")
    )
    placed: list[Path] = []
    cover_path: Path | None = None
    total = len(results)
    try:
        for r in results:
            check_cancelled(cancel)
            emit(
                on_event,
                ProgressEvent("export", (r.index - 1) / total, f"{r.index}/{total} {r.path.name}"),
            )
            dest = album_dir / r.path.name
            _copy_atomic(r.path, dest)
            placed.append(dest)
        if cover is not None:
            cover_path = save_cover_jpg(cover, album_dir / COVER_FILENAME)

        tracks = [
            Track(
                path=(album_dir / r.path.name).relative_to(root).as_posix(),
                title=r.segment.title,
                artist=plan.album.artist,
                album=plan.album.album,
                year=plan.album.year,
                number=r.index,
                total=total,
                codec=r.audio_info.codec,
                bitrate=r.audio_info.bitrate,
                duration_ms=r.audio_info.duration_ms,
                reencoded=r.reencoded,
                source_url=info.url if info else None,
                source_hash=source_hash,
            )
            for r in results
        ]
        record = SourceRecord(
            hash=source_hash,
            title=source_title,
            url=info.url if info else None,
            uploader=info.uploader if info else None,
            upload_date=info.upload_date if info else None,
        )
        register(root, record, tracks)
    except BaseException:
        for path in [*placed, *([cover_path] if cover_path else [])]:
            path.unlink(missing_ok=True)
        for folder in (album_dir, artist_dir):  # only removed if left empty
            with contextlib.suppress(OSError):
                folder.rmdir()
        raise

    # Success: the staging copies are no longer needed.
    for r in results:
        r.path.unlink(missing_ok=True)
    with contextlib.suppress(OSError):  # staging folder may hold other files: then leave it
        results[0].path.parent.rmdir()
    emit(on_event, ProgressEvent("export_done", 1.0, "Export completato"))
    return ExportResult(album_dir, tracks, cover_path)
