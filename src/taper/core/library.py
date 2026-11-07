"""SQLite catalogue of everything exported to the library.

The database lives INSIDE the library (`<root>/.taper/library.db`) and stores paths relative
to the root with forward slashes, so the library can be moved or opened from another OS.
One connection per call, no global state (the web UI will call this from threads).
No WAL: it misbehaves on network/Windows-mounted drives.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from taper.errors import TaperError
from taper.models import Track

SCHEMA_VERSION = 1
DB_DIRNAME = ".taper"
DB_FILENAME = "library.db"

_SCHEMA = """
CREATE TABLE sources (
    id          INTEGER PRIMARY KEY,
    hash        TEXT NOT NULL UNIQUE,
    url         TEXT,
    title       TEXT NOT NULL,
    uploader    TEXT,
    upload_date TEXT,
    added_at    TEXT NOT NULL
);
CREATE TABLE tracks (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    path        TEXT NOT NULL UNIQUE,
    number      INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    title       TEXT NOT NULL,
    artist      TEXT,
    album       TEXT,
    year        INTEGER,
    codec       TEXT NOT NULL,
    bitrate     INTEGER,
    duration_ms INTEGER NOT NULL,
    reencoded   INTEGER NOT NULL DEFAULT 0,
    added_at    TEXT NOT NULL
);
CREATE INDEX tracks_source ON tracks(source_id);
"""


@dataclass(frozen=True)
class SourceRecord:
    hash: str  # sha256 of the source audio file (idempotency key; also works for local files)
    title: str
    url: str | None = None
    uploader: str | None = None
    upload_date: str | None = None


@dataclass(frozen=True)
class ExistingSource:
    title: str
    added_at: str
    track_count: int
    first_path: str | None


def db_path(root: Path) -> Path:
    return root / DB_DIRNAME / DB_FILENAME


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def connect(root: Path, *, create: bool = True) -> Iterator[sqlite3.Connection]:
    """Open (and migrate) the library DB; commit on success, roll back on error."""
    path = db_path(root)
    if not create and not path.exists():
        raise TaperError(f"Nessuna libreria in '{root}'.")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _migrate(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise TaperError(
            f"La libreria è stata creata da una versione più recente di taper (schema {version}).",
            "Aggiorna taper.",
        )
    if version < 1:
        with conn:  # one transaction for schema + version
            for statement in filter(None, (s.strip() for s in _SCHEMA.split(";"))):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def find_source(root: Path, source_hash: str) -> ExistingSource | None:
    """The source already registered with this hash, if any."""
    if not db_path(root).exists():
        return None
    with connect(root) as conn:
        row = conn.execute(
            "SELECT id, title, added_at FROM sources WHERE hash = ?", (source_hash,)
        ).fetchone()
        if row is None:
            return None
        count, first = conn.execute(
            "SELECT COUNT(*), MIN(path) FROM tracks WHERE source_id = ?", (row[0],)
        ).fetchone()
        return ExistingSource(row[1], row[2], count, first)


def register(root: Path, source: SourceRecord, tracks: list[Track]) -> None:
    """Record a source and its tracks in ONE transaction (all or nothing).

    Registering a source whose hash is already known adds the tracks to that source.

    `Track.path` must already be relative to the library root, with forward slashes.
    """
    now = _now()
    with connect(root) as conn:
        row = conn.execute("SELECT id FROM sources WHERE hash = ?", (source.hash,)).fetchone()
        if row:  # same source exported again (--allow-duplicate): attach the new tracks to it
            source_id = row[0]
        else:
            source_id = conn.execute(
                "INSERT INTO sources (hash, url, title, uploader, upload_date, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (source.hash, source.url, source.title, source.uploader, source.upload_date, now),
            ).lastrowid
        conn.executemany(
            "INSERT INTO tracks (source_id, path, number, total, title, artist, album, year, "
            "codec, bitrate, duration_ms, reencoded, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    source_id,
                    t.path,
                    t.number,
                    t.total,
                    t.title,
                    t.artist,
                    t.album,
                    t.year,
                    t.codec,
                    t.bitrate,
                    t.duration_ms,
                    int(t.reencoded),
                    now,
                )  # fmt: skip
                for t in tracks
            ],
        )


def list_tracks(root: Path) -> list[Track]:
    """All tracks, ordered by album folder and number. Paths are relative to the root."""
    if not db_path(root).exists():
        return []
    with connect(root) as conn:
        rows = conn.execute(
            "SELECT t.path, t.title, t.artist, t.album, t.year, t.number, t.total, t.codec, "
            "t.bitrate, t.duration_ms, t.reencoded, s.url, s.hash "
            "FROM tracks t JOIN sources s ON s.id = t.source_id ORDER BY t.path"
        ).fetchall()
    return [
        Track(
            path=r[0],
            title=r[1],
            artist=r[2],
            album=r[3],
            year=r[4],
            number=r[5],
            total=r[6],
            codec=r[7],
            bitrate=r[8],
            duration_ms=r[9],
            reencoded=bool(r[10]),
            source_url=r[11],
            source_hash=r[12],
        )  # fmt: skip
        for r in rows
    ]
