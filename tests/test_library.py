import sqlite3
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from helpers import make_audio, needs_ffmpeg
from taper.cli import app
from taper.config import (
    DEFAULT_LIBRARY,
    ENV_ALLOW_WINDOWS,
    ENV_LIBRARY,
    ensure_library_allowed,
    is_windows_mount,
    resolve_library,
)
from taper.core.cover import CoverImage
from taper.core.cut import MODE_COPY, CutResult
from taper.core.export import export_to_library
from taper.core.ffmpeg import AudioInfo
from taper.core.library import (
    SCHEMA_VERSION,
    SourceRecord,
    connect,
    db_path,
    file_sha256,
    find_source,
    list_tracks,
    register,
)
from taper.core.naming import create_unique_dir
from taper.core.pipeline import apply_plan
from taper.core.plan import save_plan
from taper.core.sidecar import save_sidecar
from taper.core.tagging import read_tags
from taper.errors import TaperError
from taper.models import AlbumMeta, CutPlan, Segment, SourceInfo, Track

# ----------------------------------------------------------------------- config


def test_is_windows_mount():
    assert is_windows_mount(Path("/mnt/c/Users/me/Music"))
    assert is_windows_mount(Path("/mnt/d"))
    assert not is_windows_mount(Path("/mnt/wsl/x"))
    assert not is_windows_mount(Path("/home/me/taper-library"))
    assert not is_windows_mount(Path("/mnt"))


def test_default_library_is_in_linux_home():
    assert Path.home() / "taper-library" == DEFAULT_LIBRARY
    assert not is_windows_mount(DEFAULT_LIBRARY)


def test_resolve_precedence(tmp_path):
    env = {ENV_LIBRARY: str(tmp_path / "from-env")}
    assert resolve_library(tmp_path / "opt", env) == tmp_path / "opt"
    assert resolve_library(None, env) == tmp_path / "from-env"
    assert resolve_library(None, {}) == DEFAULT_LIBRARY


def test_windows_drive_refused_unless_allowed(monkeypatch):
    with pytest.raises(TaperError) as exc:
        resolve_library(Path("/mnt/c/Users/me/Music"), {})
    assert ENV_ALLOW_WINDOWS in (exc.value.hint or "")
    # fuori da WSL /mnt non esiste o non e' scrivibile: il test non deve dipendere dal sistema
    monkeypatch.setattr("taper.config.os.access", lambda *args, **kwargs: True)
    assert resolve_library(Path("/mnt/c/x"), {ENV_ALLOW_WINDOWS: "1"}) == Path("/mnt/c/x")
    with pytest.raises(TaperError):
        ensure_library_allowed(Path("/mnt/c/anything"), {})


def test_unwritable_library_is_refused_early(tmp_path):
    import os

    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(TaperError) as exc:
            ensure_library_allowed(locked / "lib", {})
        assert "scrivibile" in exc.value.message
    finally:
        locked.chmod(0o700)
    afile = tmp_path / "afile"
    afile.write_text("x")
    with pytest.raises(TaperError):
        ensure_library_allowed(afile, {})


# ----------------------------------------------------------------------- naming


def test_create_unique_dir(tmp_path):
    first = create_unique_dir(tmp_path / "a" / "2020 - Album")
    second = create_unique_dir(tmp_path / "a" / "2020 - Album")
    third = create_unique_dir(tmp_path / "a" / "2020 - Album")
    assert first.name == "2020 - Album"
    assert second.name == "2020 - Album (2)" and third.name == "2020 - Album (3)"
    long = create_unique_dir(tmp_path / ("é" * 127))  # 254 bytes
    long2 = create_unique_dir(tmp_path / ("é" * 127))
    assert len(long2.name.encode("utf-8")) <= 255 and long2.name.endswith(" (2)")
    assert long != long2


# ---------------------------------------------------------------------- library


def _track(path="A/2020 - X/01 - One.opus", **kw):
    base = dict(
        path=path, title="One", artist="A", album="X", year=2020, number=1, total=2,
        codec="opus", bitrate=128000, duration_ms=1000, reencoded=False,
        source_url="http://u", source_hash="h1",
    )  # fmt: skip
    base.update(kw)
    return Track(**base)


def _touch(root, *tracks):
    for t in tracks:
        f = root / t.path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")


def test_register_and_list_roundtrip(tmp_path):
    record = SourceRecord("h1", "Video", "http://u", "chan", "20240101")
    tracks = [_track(), _track("A/2020 - X/02 - Two.opus", title="Two", number=2, reencoded=True)]
    _touch(tmp_path, *tracks)
    register(tmp_path, record, tracks)
    assert list_tracks(tmp_path) == tracks
    existing = find_source(tmp_path, "h1")
    assert existing and existing.title == "Video" and existing.track_count == 2
    assert existing.first_path == "A/2020 - X/01 - One.opus"
    assert find_source(tmp_path, "nope") is None


def test_schema_version_and_location(tmp_path):
    register(tmp_path, SourceRecord("h", "T"), [_track(source_hash="h")])
    assert db_path(tmp_path) == tmp_path / ".taper" / "library.db"
    raw = sqlite3.connect(db_path(tmp_path))
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert raw.execute("PRAGMA journal_mode").fetchone()[0] != "wal"
    raw.close()


def test_newer_schema_refused(tmp_path):
    register(tmp_path, SourceRecord("h", "T"), [_track()])
    raw = sqlite3.connect(db_path(tmp_path))
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.commit()
    raw.close()
    with pytest.raises(TaperError), connect(tmp_path):
        pass


def test_register_same_source_again_adds_tracks(tmp_path):
    first, second = _track(), _track("B/2020 - X/01 - One.opus")
    _touch(tmp_path, first, second)
    register(tmp_path, SourceRecord("h1", "T"), [first])
    register(tmp_path, SourceRecord("h1", "T"), [second])
    assert len(list_tracks(tmp_path)) == 2
    assert find_source(tmp_path, "h1").track_count == 2


def test_register_is_all_or_nothing(tmp_path):
    one = _track()
    _touch(tmp_path, one)
    register(tmp_path, SourceRecord("h1", "T"), [one])
    dup = _track("Z/a.opus")
    _touch(tmp_path, dup)
    with pytest.raises(TaperError):  # duplicate path inside one batch
        register(tmp_path, SourceRecord("h2", "T"), [dup, dup])
    assert [t.path for t in list_tracks(tmp_path)] == [one.path]
    assert find_source(tmp_path, "h2") is None


def test_files_deleted_by_hand_do_not_block_a_new_export(tmp_path):
    """Opus review: delete an album folder, re-run -> must not be 'already in library'/crash."""
    tracks = [_track(), _track("A/2020 - X/02 - Two.opus", title="Two", number=2)]
    _touch(tmp_path, *tracks)
    register(tmp_path, SourceRecord("h1", "T"), tracks)
    assert find_source(tmp_path, "h1") is not None

    for t in tracks:  # the user removes the folder
        (tmp_path / t.path).unlink()
    assert find_source(tmp_path, "h1") is None  # no longer blocks

    _touch(tmp_path, *tracks)  # same folder/paths are created again
    register(tmp_path, SourceRecord("h1", "T"), tracks)  # no UNIQUE constraint crash
    assert [t.path for t in list_tracks(tmp_path)] == [t.path for t in tracks]
    assert find_source(tmp_path, "h1").track_count == 2


def test_partially_deleted_source_still_counts_remaining_files(tmp_path):
    tracks = [_track(), _track("A/2020 - X/02 - Two.opus", title="Two", number=2)]
    _touch(tmp_path, *tracks)
    register(tmp_path, SourceRecord("h1", "T"), tracks)
    (tmp_path / tracks[0].path).unlink()
    existing = find_source(tmp_path, "h1")
    assert existing and existing.track_count == 1 and existing.first_path == tracks[1].path


def test_database_errors_become_taper_errors(tmp_path):
    (tmp_path / ".taper").mkdir()
    (tmp_path / ".taper" / "library.db").write_bytes(b"this is not an sqlite database" * 20)
    with pytest.raises(TaperError) as exc:
        list_tracks(tmp_path)
    assert "database" in exc.value.message and "copia" in (exc.value.hint or "")


def test_file_sha256(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    assert file_sha256(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ----------------------------------------------------------------------- export


def _staged(tmp_path, n=2, artist="The Band", album="Live: Night", year=1999):
    """Fake cut results: tiny files standing in for tagged tracks."""
    staging = tmp_path / "tracks"
    staging.mkdir(exist_ok=True)
    segments = [Segment(i * 1000, (i + 1) * 1000, f"Song {i + 1}") for i in range(n)]
    plan = CutPlan("src.opus", AlbumMeta(artist, album, year), segments)
    results = []
    for i, seg in enumerate(segments, start=1):
        path = staging / f"{i:02d} - {seg.title}.opus"
        path.write_bytes(b"audio" * i)
        info = AudioInfo("opus", 1000, 128000, 48000, 2)
        results.append(CutResult(i, seg, path, MODE_COPY, info))
    return plan, results


COVER = CoverImage(b"\xff\xd8jpegbytes", 10, 10)


def _export(root, plan, results, **kw):
    kw.setdefault("source_hash", "hash1")
    return export_to_library(root, plan, results, source_title="Video", cover=COVER, **kw)


def test_export_layout_db_cover_and_staging_cleanup(tmp_path):
    plan, results = _staged(tmp_path)
    root = tmp_path / "lib"
    out = _export(root, plan, results, info=SourceInfo("V", url="http://u"))

    album = root / "The Band" / "1999 - Live_ Night"
    assert out.album_dir == album
    assert sorted(p.name for p in album.iterdir()) == [
        "01 - Song 1.opus", "02 - Song 2.opus", "cover.jpg",
    ]  # fmt: skip
    assert (album / "cover.jpg").read_bytes() == COVER.data
    assert not (tmp_path / "tracks").exists()  # staging emptied and removed
    rows = list_tracks(root)
    assert [t.path for t in rows] == [
        "The Band/1999 - Live_ Night/01 - Song 1.opus",
        "The Band/1999 - Live_ Night/02 - Song 2.opus",
    ]
    assert rows[0].source_url == "http://u" and rows[0].codec == "opus" and rows[0].total == 2
    assert not list(root.rglob("*.part"))


def test_export_second_album_never_merges(tmp_path):
    root = tmp_path / "lib"
    plan, results = _staged(tmp_path)
    first = _export(root, plan, results)
    plan2, results2 = _staged(tmp_path)
    second = _export(root, plan2, results2, source_hash="hash2")
    assert second.album_dir.name == first.album_dir.name + " (2)"
    assert len(list(first.album_dir.glob("*.opus"))) == 2  # untouched


def test_export_unknown_artist_and_no_cover(tmp_path):
    plan, results = _staged(tmp_path, artist=None, album=None, year=None)
    root = tmp_path / "lib"
    out = export_to_library(root, plan, results, source_hash="h", source_title="V", cover=None)
    assert out.album_dir == root / "Unknown Artist" / "Unknown Album"
    assert out.cover is None and not (out.album_dir / "cover.jpg").exists()


def test_export_failure_rolls_back_and_keeps_staging(tmp_path, monkeypatch):
    plan, results = _staged(tmp_path)
    root = tmp_path / "lib"

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("taper.core.export.register", boom)
    with pytest.raises(RuntimeError):
        _export(root, plan, results)
    assert not list(root.rglob("*.opus")) and not (root / "The Band").exists()
    assert all(r.path.exists() for r in results)  # staging untouched: nothing lost


def test_export_refuses_windows_drive(tmp_path):
    plan, results = _staged(tmp_path)
    with pytest.raises(TaperError):
        _export(Path("/mnt/c/taper-test"), plan, results)
    assert all(r.path.exists() for r in results)


# -------------------------------------------------------- full pipeline (ffmpeg)


def _source(tmp_path_factory):
    src = make_audio(tmp_path_factory, "opus", seconds=40)
    Image.new("RGB", (320, 180), (10, 120, 200)).save(src.with_name("source.png"))
    info = SourceInfo(title="Video", url="https://example.com/v", thumbnail="source.png")
    save_sidecar(info, src)
    return src, info


def _plan():
    return CutPlan(
        "source.opus",
        AlbumMeta("The Band", "Live 99", 1999),
        [Segment(0, 15_000, "One"), Segment(15_000, 40_000, "Two")],
    )


@needs_ffmpeg
def test_apply_plan_exports_registers_and_blocks_duplicates(tmp_path_factory, tmp_path):
    src, info = _source(tmp_path_factory)
    lib = tmp_path / "lib"
    out = apply_plan(src, _plan(), src.parent / "tracks", library=lib, info=info)

    assert out.export is not None
    album = lib / "The Band" / "1999 - Live 99"
    tags, cover = read_tags(album / "02 - Two.opus")
    assert (tags.title, tags.number, tags.total, tags.year) == ("Two", 2, 2, 1999) and cover
    assert (album / "cover.jpg").exists()
    rows = list_tracks(lib)
    assert [t.number for t in rows] == [1, 2]
    assert rows[0].source_url == "https://example.com/v" and rows[0].reencoded is False

    with pytest.raises(TaperError) as exc:  # same source again: refused BEFORE cutting
        apply_plan(src, _plan(), src.parent / "tracks", library=lib, info=info)
    assert "--allow-duplicate" in (exc.value.hint or "")
    assert not (src.parent / "tracks").exists()

    again = apply_plan(
        src, _plan(), src.parent / "tracks", library=lib, info=info, allow_duplicate=True
    )
    assert again.export.album_dir.name == "1999 - Live 99 (2)"
    assert len(list_tracks(lib)) == 4


@needs_ffmpeg
def test_apply_plan_without_library_keeps_tracks_in_staging(tmp_path_factory):
    src, info = _source(tmp_path_factory)
    out = apply_plan(src, _plan(), src.parent / "tracks", library=None, info=info)
    assert out.export is None
    assert len(list((src.parent / "tracks").glob("*.opus"))) == 2


@needs_ffmpeg
def test_cli_cut_uses_library_env_and_no_library(tmp_path_factory, tmp_path, monkeypatch):
    src, _ = _source(tmp_path_factory)
    plan_path = src.with_name("p.yaml")
    save_plan(_plan(), plan_path)
    lib = tmp_path / "envlib"
    monkeypatch.setenv(ENV_LIBRARY, str(lib))
    runner = CliRunner()

    result = runner.invoke(app, ["cut", str(src), "--plan", str(plan_path)])
    assert result.exit_code == 0, result.output
    assert str(lib) in result.output and "library.db" in result.output
    assert (lib / "The Band" / "1999 - Live 99" / "01 - One.opus").exists()

    dup = runner.invoke(app, ["cut", str(src), "--plan", str(plan_path)])
    assert dup.exit_code == 1 and "già in libreria" in dup.output

    local = runner.invoke(app, ["cut", str(src), "--plan", str(plan_path), "--no-library"])
    assert local.exit_code == 0, local.output
    assert len(list((src.parent / "tracks").glob("*.opus"))) == 2

    bad = runner.invoke(app, ["cut", str(src), "--plan", str(plan_path), "-l", "/mnt/c/Music"])
    assert bad.exit_code == 1 and "disco Windows" in bad.output
