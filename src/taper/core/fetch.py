"""Download the best audio stream with yt-dlp, keeping the NATIVE codec (no re-encoding)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from taper.core.ffmpeg import AudioInfo, find_tool, probe_audio
from taper.core.progress import ProgressCallback, ProgressEvent, check_cancelled, emit
from taper.core.sidecar import save_sidecar
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


def build_ydl_options(root: Path, progress_hooks: list[Any] | None = None) -> dict[str, Any]:
    """yt-dlp options: best audio, native codec, one work dir per video id."""
    root_escaped = str(root).replace("%", "%%")  # outtmpl treats % specially
    return {
        "format": "bestaudio/best",
        "outtmpl": {"default": f"{root_escaped}/%(id)s/%(id)s.%(ext)s"},
        "noplaylist": True,
        "writethumbnail": True,
        # "best" = stream copy into the matching container (webm/opus -> .opus, m4a -> .m4a)
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
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


def fetch(
    url: str,
    root: Path,
    *,
    on_event: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> FetchResult:
    """Download `url` into `root/<video id>/` and write the metadata sidecar."""
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
                on_event, ProgressEvent("postprocess", None, "Estrazione audio (senza ricodifica)")
            )

    options = build_ydl_options(root, [hook])
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=True)
    except CancelledError:
        raise
    except DownloadError as exc:
        check_cancelled(cancel)  # yt-dlp may wrap an exception raised by our hook
        text = str(exc)
        if "Unsupported URL" in text:
            raise SourceError(
                f"URL non supportato: {url}",
                "Controlla l'URL o usa 'yt-dlp --list-extractors' per le fonti supportate.",
            ) from exc
        raise SourceError(
            f"Download fallito: {text}",
            "Aggiorna yt-dlp ('uv lock --upgrade-package yt-dlp'); "
            "per YouTube può servire anche un runtime JS (es. deno).",
        ) from exc

    if data is None:
        raise SourceError(f"Nessun risultato per {url}")

    audio = _audio_path_from(data)
    workdir = audio.parent
    thumb = find_thumbnail(workdir, audio.stem)
    info = source_info_from_ydl(data, thumbnail=thumb.name if thumb else None, url=url)
    sidecar = save_sidecar(info, audio)
    audio_info = probe_audio(audio)
    emit(on_event, ProgressEvent("done", 1.0, "Download completato"))
    return FetchResult(workdir, audio, sidecar, thumb, info, audio_info)
