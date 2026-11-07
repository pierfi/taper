"""Pure helpers to build safe file and folder names (Linux, Windows, WSL)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

MAX_COMPONENT_BYTES = 255

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WHITESPACE = re.compile(r"\s+")
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}  # fmt: skip


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """Truncate to at most `max_bytes` of UTF-8 without splitting a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def sanitize_component(
    name: str, *, max_bytes: int = MAX_COMPONENT_BYTES, fallback: str = "_"
) -> str:
    """Make `name` usable as a single path component on any supported OS.

    Replaces forbidden characters, collapses whitespace, strips trailing dots
    and spaces (invalid on Windows), avoids reserved device names and enforces
    the per-component byte limit. Never returns an empty string.
    """
    text = unicodedata.normalize("NFC", name)
    text = _FORBIDDEN.sub("_", text)
    text = _WHITESPACE.sub(" ", text).strip()
    text = _truncate_bytes(text, max_bytes).rstrip(" .")
    if not text:
        return fallback
    if text.split(".")[0].upper() in _RESERVED:
        text = "_" + text
        text = _truncate_bytes(text, max_bytes).rstrip(" .")
    return text


def track_filename(number: int, title: str, ext: str, *, total: int | None = None) -> str:
    """`NN - Titolo.ext`, zero-padded to at least 2 digits (more if total >= 100)."""
    width = max(2, len(str(total))) if total else 2
    ext = ext.lstrip(".")
    suffix = f".{ext}"
    prefix = f"{number:0{width}d} - "
    budget = MAX_COMPONENT_BYTES - len((prefix + suffix).encode("utf-8"))
    return prefix + sanitize_component(title, max_bytes=budget, fallback="Untitled") + suffix


def album_dirname(year: int | None, album: str) -> str:
    """`Anno - Album` (just `Album` when the year is unknown)."""
    label = f"{year} - {album}" if year else album
    return sanitize_component(label, fallback="Unknown Album")


def artist_dirname(artist: str | None) -> str:
    return sanitize_component(artist or "", fallback="Unknown Artist")


def create_unique_dir(path: Path) -> Path:
    """Create `path`, or `path (2)`, `path (3)`... if taken, and return what was created.

    Uses mkdir itself to claim the name, so two runs cannot grab the same folder.
    Never merges into an existing folder and respects the 255-byte limit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        if n == 1:
            candidate = path
        else:
            suffix = f" ({n})"
            room = MAX_COMPONENT_BYTES - len(suffix.encode("utf-8"))
            candidate = path.with_name(_truncate_bytes(path.name, room).rstrip(" .") + suffix)
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            n += 1


def unique_path(path: Path) -> Path:
    """Return `path`, or `path` with ` (2)`, ` (3)`... if it already exists. Never overwrites."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1
