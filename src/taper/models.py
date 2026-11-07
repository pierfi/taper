"""Plain, serializable data models shared by core, CLI and (later) the web UI.

All times are integer milliseconds. Every model round-trips through
``to_dict`` / ``from_dict`` so it can be stored as JSON/YAML or sent over HTTP.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PLAN_VERSION = 1
SIDECAR_VERSION = 1

# Where a segment boundary came from (written in the plan so it can be reviewed).
SOURCE_CHAPTERS = "chapters"
SOURCE_DESCRIPTION = "description"
SOURCE_SILENCE = "silence"
SOURCE_MANUAL = "manual"


@dataclass(frozen=True)
class Chapter:
    start_ms: int
    end_ms: int
    title: str


@dataclass
class SourceInfo:
    """Metadata of a downloaded source (the `<stem>.taper.json` sidecar)."""

    title: str
    url: str | None = None
    uploader: str | None = None
    artist: str | None = None
    creator: str | None = None
    upload_date: str | None = None  # YYYYMMDD
    description: str = ""
    duration_ms: int | None = None
    chapters: list[Chapter] = field(default_factory=list)
    thumbnail: str | None = None  # file name relative to the work dir
    version: int = SIDECAR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceInfo:
        data = dict(data)
        data["chapters"] = [Chapter(**c) for c in data.get("chapters", [])]
        return cls(**data)

    @property
    def default_artist(self) -> str | None:
        return self.artist or self.creator or self.uploader

    @property
    def default_year(self) -> int | None:
        if self.upload_date and len(self.upload_date) >= 4 and self.upload_date[:4].isdigit():
            return int(self.upload_date[:4])
        return None


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    title: str
    source: str = SOURCE_MANUAL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        return cls(**data)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass
class AlbumMeta:
    artist: str | None = None
    album: str | None = None
    year: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlbumMeta:
        return cls(**data)


@dataclass
class CutPlan:
    source_file: str
    album: AlbumMeta = field(default_factory=AlbumMeta)
    segments: list[Segment] = field(default_factory=list)
    version: int = PLAN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CutPlan:
        return cls(
            source_file=data["source_file"],
            album=AlbumMeta.from_dict(data.get("album", {})),
            segments=[Segment.from_dict(s) for s in data.get("segments", [])],
            version=data.get("version", PLAN_VERSION),
        )


@dataclass
class Track:
    """A produced track, as registered in the library."""

    path: str
    title: str
    artist: str | None
    album: str | None
    year: int | None
    number: int
    total: int
    codec: str
    bitrate: int | None
    duration_ms: int
    reencoded: bool = False
    source_url: str | None = None
    source_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Track:
        return cls(**data)
