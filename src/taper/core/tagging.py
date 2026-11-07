"""Write (and read back) tags and embedded cover art for opus, ogg, m4a, mp3 and flac."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from taper.core.cover import CoverImage
from taper.errors import SourceError
from taper.models import CutPlan

SUPPORTED_EXTENSIONS = (".opus", ".ogg", ".m4a", ".mp3", ".flac")
_PICTURE_TYPE_FRONT_COVER = 3


@dataclass(frozen=True)
class TrackTags:
    title: str
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    number: int | None = None
    total: int | None = None


def tags_for_plan(plan: CutPlan, index: int) -> TrackTags:
    """Tags of the `index`-th (1-based) segment of the plan (pure)."""
    seg = plan.segments[index - 1]
    return TrackTags(
        title=seg.title,
        artist=plan.album.artist,
        album=plan.album.album,
        album_artist=plan.album.artist,
        year=plan.album.year,
        number=index,
        total=len(plan.segments),
    )


def _picture(cover: CoverImage) -> Picture:
    pic = Picture()
    pic.type = _PICTURE_TYPE_FRONT_COVER
    pic.mime = cover.mime
    pic.desc = "Cover"
    pic.width, pic.height, pic.depth = cover.width, cover.height, 24
    pic.data = cover.data
    return pic


def _vorbis_comments(tags: TrackTags) -> dict[str, list[str]]:
    fields: dict[str, str | None] = {
        "title": tags.title,
        "artist": tags.artist,
        "album": tags.album,
        "albumartist": tags.album_artist,
        "date": str(tags.year) if tags.year else None,
        "tracknumber": str(tags.number) if tags.number else None,
        "tracktotal": str(tags.total) if tags.total else None,
        "totaltracks": str(tags.total) if tags.total else None,
    }
    return {k: [v] for k, v in fields.items() if v}


def _write_vorbis_like(audio, tags: TrackTags, cover: CoverImage | None, *, base64_pic: bool):
    if audio.tags is None:
        audio.add_tags()
    audio.tags.clear()
    for key, values in _vorbis_comments(tags).items():
        audio[key] = values
    if not base64_pic:
        audio.clear_pictures()  # FLAC keeps pictures outside the comments: drop stale ones
    if cover is not None:
        pic = _picture(cover)
        if base64_pic:  # Ogg (opus/vorbis): METADATA_BLOCK_PICTURE
            audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        else:  # FLAC: native picture block
            audio.add_picture(pic)
    audio.save()


def _write_mp3(path: Path, tags: TrackTags, cover: CoverImage | None) -> None:
    id3 = ID3()  # fresh tag: replaces whatever was in the file
    id3.add(TIT2(encoding=3, text=tags.title))
    if tags.artist:
        id3.add(TPE1(encoding=3, text=tags.artist))
    if tags.album_artist:
        id3.add(TPE2(encoding=3, text=tags.album_artist))
    if tags.album:
        id3.add(TALB(encoding=3, text=tags.album))
    if tags.year:
        id3.add(TDRC(encoding=3, text=str(tags.year)))
    if tags.number:
        id3.add(
            TRCK(encoding=3, text=f"{tags.number}/{tags.total}" if tags.total else str(tags.number))
        )
    if cover is not None:
        id3.add(
            APIC(
                encoding=3,
                mime=cover.mime,
                type=_PICTURE_TYPE_FRONT_COVER,
                desc="Cover",
                data=cover.data,
            )  # fmt: skip
        )
    id3.save(path, v2_version=4)


def _write_m4a(path: Path, tags: TrackTags, cover: CoverImage | None) -> None:
    mp4 = MP4(path)
    if mp4.tags is None:
        mp4.add_tags()
    mp4.tags.clear()
    mp4["\xa9nam"] = [tags.title]
    if tags.artist:
        mp4["\xa9ART"] = [tags.artist]
    if tags.album_artist:
        mp4["aART"] = [tags.album_artist]
    if tags.album:
        mp4["\xa9alb"] = [tags.album]
    if tags.year:
        mp4["\xa9day"] = [str(tags.year)]
    if tags.number:
        mp4["trkn"] = [(tags.number, tags.total or 0)]
    if cover is not None:
        mp4["covr"] = [MP4Cover(cover.data, imageformat=MP4Cover.FORMAT_JPEG)]
    mp4.save()


def write_tags(path: Path, tags: TrackTags, cover: CoverImage | None = None) -> None:
    """Write tags (and cover) into `path` in place, replacing any existing tags."""
    ext = path.suffix.lower()
    if ext == ".opus":
        _write_vorbis_like(OggOpus(path), tags, cover, base64_pic=True)
    elif ext == ".ogg":
        _write_vorbis_like(OggVorbis(path), tags, cover, base64_pic=True)
    elif ext == ".flac":
        _write_vorbis_like(FLAC(path), tags, cover, base64_pic=False)
    elif ext == ".mp3":
        _write_mp3(path, tags, cover)
    elif ext == ".m4a":
        _write_m4a(path, tags, cover)
    else:
        raise SourceError(
            f"Formato non supportato per i tag: '{ext}'.",
            f"Formati gestiti: {', '.join(SUPPORTED_EXTENSIONS)}.",
        )


# ------------------------------------------------------------------------- reading


def _int(value: object) -> int | None:
    try:
        return int(str(value).split("/")[0])
    except (TypeError, ValueError):
        return None


def _first(mapping, key: str) -> str | None:
    values = mapping.get(key)
    return str(values[0]) if values else None


def read_tags(path: Path) -> tuple[TrackTags, bytes | None]:
    """Tags and embedded cover bytes (None if absent) of `path`."""
    ext = path.suffix.lower()
    cover: bytes | None = None
    if ext in (".opus", ".ogg", ".flac"):
        audio = {".opus": OggOpus, ".ogg": OggVorbis, ".flac": FLAC}[ext](path)
        t = audio.tags or {}
        number_raw = _first(t, "tracknumber")
        total = _int(_first(t, "tracktotal") or _first(t, "totaltracks"))
        if total is None and number_raw and "/" in number_raw:
            total = _int(number_raw.split("/")[1])
        if ext == ".flac":
            cover = audio.pictures[0].data if audio.pictures else None
        elif pics := t.get("metadata_block_picture"):
            cover = Picture(base64.b64decode(pics[0])).data
        tags = TrackTags(
            title=_first(t, "title") or "",
            artist=_first(t, "artist"),
            album=_first(t, "album"),
            album_artist=_first(t, "albumartist"),
            year=_int(_first(t, "date")),
            number=_int(number_raw),
            total=total,
        )
    elif ext == ".mp3":
        id3 = ID3(path)
        trck = str(id3["TRCK"].text[0]) if "TRCK" in id3 else None
        apic = id3.getall("APIC")
        cover = apic[0].data if apic else None
        tags = TrackTags(
            title=str(id3["TIT2"].text[0]) if "TIT2" in id3 else "",
            artist=str(id3["TPE1"].text[0]) if "TPE1" in id3 else None,
            album=str(id3["TALB"].text[0]) if "TALB" in id3 else None,
            album_artist=str(id3["TPE2"].text[0]) if "TPE2" in id3 else None,
            year=_int(id3["TDRC"].text[0]) if "TDRC" in id3 else None,
            number=_int(trck),
            total=_int(trck.split("/")[1]) if trck and "/" in trck else None,
        )
    elif ext == ".m4a":
        mp4 = MP4(path)
        t = mp4.tags or {}
        number, total = t["trkn"][0] if "trkn" in t else (None, None)
        covr = t.get("covr")
        cover = bytes(covr[0]) if covr else None
        tags = TrackTags(
            title=_first(t, "\xa9nam") or "",
            artist=_first(t, "\xa9ART"),
            album=_first(t, "\xa9alb"),
            album_artist=_first(t, "aART"),
            year=_int(_first(t, "\xa9day")),
            number=number or None,
            total=total or None,
        )
    else:
        raise SourceError(f"Formato non supportato: '{ext}'.")
    return tags, cover
