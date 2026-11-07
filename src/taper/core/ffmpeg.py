"""Thin wrapper around the ffmpeg / ffprobe executables."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taper.errors import SourceError, ToolNotFoundError

_INSTALL_HINT = (
    "Installa ffmpeg: 'sudo apt install ffmpeg' (Debian/Ubuntu/WSL), "
    "'brew install ffmpeg' (macOS), 'winget install ffmpeg' (Windows); "
    "poi verifica che sia nel PATH."
)


@dataclass(frozen=True)
class AudioInfo:
    """What ffprobe tells us about an audio file."""

    codec: str  # e.g. "opus", "aac", "mp3", "flac"
    duration_ms: int
    bitrate: int | None  # bits per second
    sample_rate: int | None
    channels: int | None
    format_name: str | None = None


def find_tool(name: str) -> str:
    """Absolute path of `name` in PATH, or a clear ToolNotFoundError."""
    path = shutil.which(name)
    if path is None:
        raise ToolNotFoundError(f"'{name}' non trovato nel PATH.", _INSTALL_HINT)
    return path


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_probe(data: dict[str, Any]) -> AudioInfo:
    """Build an AudioInfo from ffprobe's `-print_format json` output (pure)."""
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise SourceError("Nessuna traccia audio trovata nel file.")
    stream = streams[0]
    fmt = data.get("format", {})

    duration = stream.get("duration") or fmt.get("duration")
    try:
        duration_ms = round(float(duration) * 1000)
    except (TypeError, ValueError):
        raise SourceError("Impossibile determinare la durata del file audio.") from None

    return AudioInfo(
        codec=str(stream.get("codec_name", "unknown")),
        duration_ms=duration_ms,
        bitrate=_to_int(stream.get("bit_rate")) or _to_int(fmt.get("bit_rate")),
        sample_rate=_to_int(stream.get("sample_rate")),
        channels=_to_int(stream.get("channels")),
        format_name=fmt.get("format_name"),
    )


def probe_audio(path: Path) -> AudioInfo:
    """Run ffprobe on `path` and return its audio info."""
    ffprobe = find_tool("ffprobe")
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],  # fmt: skip
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or "errore sconosciuto"
        raise SourceError(f"ffprobe non riesce a leggere '{path}': {detail}")
    return parse_probe(json.loads(proc.stdout))
