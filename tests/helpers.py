"""Shared helpers for tests that need real (synthetic) audio produced by ffmpeg."""

import shutil
import subprocess
from pathlib import Path

import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe non installati")

SOURCE_SECONDS = 60
CODEC_ARGS = {
    "opus": ["-c:a", "libopus", "-b:a", "64k"],
    "m4a": ["-c:a", "aac", "-b:a", "96k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "96k"],
    "flac": ["-c:a", "flac"],
}


def make_audio(tmp_path_factory, ext: str, seconds: int = SOURCE_SECONDS) -> Path:
    path = tmp_path_factory.mktemp(ext) / f"source.{ext}"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        *CODEC_ARGS[ext], str(path),
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"encoder per {ext} non disponibile: {proc.stderr.strip()[-120:]}")
    return path
