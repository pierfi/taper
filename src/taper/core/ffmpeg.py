"""Thin wrapper around the ffmpeg / ffprobe executables."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taper.errors import CancelledError, SourceError, ToolNotFoundError

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
    start_time_ms: int | None = None  # timestamp of the first packet


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

    start = stream.get("start_time") or fmt.get("start_time")
    try:
        start_time_ms = round(float(start) * 1000) if start is not None else None
    except (TypeError, ValueError):
        start_time_ms = None

    return AudioInfo(
        codec=str(stream.get("codec_name", "unknown")),
        duration_ms=duration_ms,
        bitrate=_to_int(stream.get("bit_rate")) or _to_int(fmt.get("bit_rate")),
        sample_rate=_to_int(stream.get("sample_rate")),
        channels=_to_int(stream.get("channels")),
        format_name=fmt.get("format_name"),
        start_time_ms=start_time_ms,
    )


_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def parse_silencedetect(stderr: str, duration_ms: int | None = None) -> list[tuple[int, int]]:
    """Parse ffmpeg `silencedetect` log output into (start_ms, end_ms) pairs (pure).

    A trailing silence that never ends is closed at `duration_ms` when known.
    """
    silences: list[tuple[int, int]] = []
    start: int | None = None
    for line in stderr.splitlines():
        if m := _SILENCE_START.search(line):
            start = max(0, round(float(m.group(1)) * 1000))
        elif (m := _SILENCE_END.search(line)) and start is not None:
            silences.append((start, round(float(m.group(1)) * 1000)))
            start = None
    if start is not None and duration_ms is not None and duration_ms > start:
        silences.append((start, duration_ms))
    return silences


def detect_silences(
    path: Path, *, noise_db: float, min_silence_s: float, duration_ms: int | None = None
) -> list[tuple[int, int]]:
    """Run ffmpeg silencedetect on `path`."""
    ffmpeg = find_tool("ffmpeg")
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
            "-f",
            "null",
            "-",
        ],  # fmt: skip
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1:] or ["errore sconosciuto"]
        raise SourceError(f"ffmpeg non riesce a leggere '{path}': {detail[0]}")
    return parse_silencedetect(proc.stderr, duration_ms)


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


def run_ffmpeg(args: list[str], *, cancel: threading.Event | None = None) -> None:
    """Run ffmpeg quietly; kill it promptly if `cancel` is set. Raises on failure."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while True:
        try:
            _, stderr = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.communicate()
                raise CancelledError("Operazione annullata.") from None
    if proc.returncode != 0:
        detail = (stderr or "").strip()[-500:] or "errore sconosciuto"
        raise SourceError(f"ffmpeg ha fallito: {detail}")
