"""Cover art: turn a (usually 16:9) thumbnail into a square JPEG."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from taper.errors import SourceError

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_COVER_SIZE = 1200
JPEG_QUALITY = 90


@dataclass(frozen=True)
class CoverImage:
    data: bytes  # JPEG
    width: int
    height: int
    mime: str = "image/jpeg"


def square_crop_box(width: int, height: int) -> tuple[int, int, int, int]:
    """Centered square (left, top, right, bottom) inside a width x height image (pure)."""
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return left, top, left + side, top + side


def make_square_cover(
    image_path: Path, *, max_size: int = MAX_COVER_SIZE, quality: int = JPEG_QUALITY
) -> CoverImage:
    """Centered square crop of `image_path`, never upscaled, encoded as JPEG."""
    try:
        with Image.open(image_path) as img:
            img.load()
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                rgb = flat
            else:
                rgb = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise SourceError(f"Immagine di copertina non leggibile: {image_path} ({exc})") from exc

    square = rgb.crop(square_crop_box(*rgb.size))
    if square.width > max_size:
        square = square.resize((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    square.save(buffer, format="JPEG", quality=quality, optimize=True)
    return CoverImage(buffer.getvalue(), square.width, square.height)


def save_cover_jpg(cover: CoverImage, dest: Path) -> Path:
    """Write `cover` to `dest` atomically."""
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(cover.data)
    tmp.replace(dest)
    return dest


def find_cover_source(source: Path, thumbnail_name: str | None = None) -> Path | None:
    """The image to use as cover for `source`: sidecar thumbnail, `<stem>.<img>` or cover.jpg."""
    folder = source.parent
    candidates = []
    if thumbnail_name:
        candidates.append(folder / thumbnail_name)
    candidates += [folder / f"{source.stem}{ext}" for ext in IMAGE_EXTENSIONS]
    candidates += [folder / "cover.jpg", folder / "cover.png"]
    return next((c for c in candidates if c.is_file()), None)
