from types import SimpleNamespace

import pytest
from PIL import Image
from typer.testing import CliRunner

from helpers import make_audio, needs_ffmpeg
from taper import cli
from taper.cli import app
from taper.config import ENV_LIBRARY
from taper.core.fetch import FetchResult
from taper.core.ffmpeg import probe_audio
from taper.core.library import list_tracks
from taper.core.sidecar import save_sidecar, sidecar_path
from taper.models import Chapter, SourceInfo

pytestmark = needs_ffmpeg
URL = "https://example.com/watch?v=abc123"
runner = CliRunner()


@pytest.fixture
def fake_source(tmp_path_factory, monkeypatch):
    """A synthetic 'downloaded' source; `fetch` is replaced so nothing touches the network."""
    src = make_audio(tmp_path_factory, "opus", seconds=40)
    Image.new("RGB", (320, 180), (10, 120, 200)).save(src.with_name("source.png"))
    info = SourceInfo(
        title="Video title (HD AUDIO)!",
        url=URL,
        uploader="Fan channel",
        upload_date="20260910",
        chapters=[Chapter(0, 15_000, "One"), Chapter(15_000, 40_000, "Two")],
        thumbnail="source.png",
    )
    save_sidecar(info, src)
    result = FetchResult(
        src.parent, src, sidecar_path(src), src.with_name("source.png"), info, probe_audio(src)
    )
    calls = []

    def fake_fetch(url, root, **kwargs):
        calls.append(url)
        return result

    monkeypatch.setattr("taper.core.pipeline.fetch_source", fake_fetch)
    return SimpleNamespace(audio=src, workdir=src.parent, calls=calls)


def run(*args, input=None):
    return runner.invoke(app, ["run", URL, *args], input=input)


def plan_file(fs):
    return fs.audio.with_name("source.plan.yaml")


def test_yes_runs_everything_with_overrides(fake_source, tmp_path):
    lib = tmp_path / "lib"
    r = run("--yes", "-l", str(lib), "--artist", "The Band", "--album", "Live 99", "--year", "1999")
    assert r.exit_code == 0, r.output
    album = lib / "The Band" / "1999 - Live 99"
    assert (album / "01 - One.opus").exists() and (album / "02 - Two.opus").exists()
    assert (album / "cover.jpg").exists()
    assert plan_file(fake_source).exists()
    assert [t.title for t in list_tracks(lib)] == ["One", "Two"]
    assert "canale" not in r.output  # artist given: no 'guessed from channel' hint


def test_review_continue(fake_source, tmp_path):
    lib = tmp_path / "lib"
    r = run("-l", str(lib), input="c\n")
    assert r.exit_code == 0, r.output
    assert "Fan channel" in r.output and "2026" in r.output  # shows what was guessed
    assert "canale" in r.output  # ...and warns about it
    assert (lib / "Fan channel" / "2026 - Video title (HD AUDIO)!" / "01 - One.opus").exists()


def test_review_default_answer_is_continue(fake_source, tmp_path):
    r = run("-l", str(tmp_path / "lib"), input="\n")
    assert r.exit_code == 0, r.output
    assert len(list_tracks(tmp_path / "lib")) == 2


def test_review_abort_cuts_nothing_and_keeps_plan(fake_source, tmp_path):
    lib = tmp_path / "lib"
    r = run("-l", str(lib), input="a\n")
    assert r.exit_code == 1
    assert plan_file(fake_source).exists()
    assert not lib.exists() and not (fake_source.workdir / "tracks").exists()


def test_review_edit_then_continue(fake_source, tmp_path, monkeypatch):
    def edit(path):
        path.write_text(
            path.read_text(encoding="utf-8").replace('"Fan channel"', '"Edited Artist"'),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli, "_edit_file", edit)
    lib = tmp_path / "lib"
    r = run("-l", str(lib), input="e\nc\n")
    assert r.exit_code == 0, r.output
    assert [t.artist for t in list_tracks(lib)] == ["Edited Artist"] * 2


def test_invalid_edit_blocks_continue_until_fixed(fake_source, tmp_path, monkeypatch):
    edits = []

    def edit(path):
        text = path.read_text(encoding="utf-8")
        if not edits:  # first edit breaks the plan: segment 2 ends before it starts
            text = text.replace('end: "0:00:40.000"', 'end: "0:00:05.000"')
        else:  # second edit repairs it
            text = text.replace('end: "0:00:05.000"', 'end: "0:00:40.000"')
        edits.append(1)
        path.write_text(text, encoding="utf-8")

    monkeypatch.setattr(cli, "_edit_file", edit)
    lib = tmp_path / "lib"
    r = run("-l", str(lib), input="e\nc\ne\nc\n")
    assert r.exit_code == 0, r.output
    assert "✗" in r.output  # problems are listed
    assert "Risposta non valida" in r.output  # 'c' is refused while the plan is invalid
    assert len(list_tracks(lib)) == 2


def test_existing_plan_is_reused_with_hand_edits(fake_source, tmp_path):
    first = run("--yes", "--no-library")
    assert first.exit_code == 0, first.output
    path = plan_file(fake_source)
    path.write_text(path.read_text(encoding="utf-8").replace('"One"', '"First Song"'), "utf-8")

    second = run("--yes", "--no-library", "--force")
    assert second.exit_code == 0, second.output
    assert "riutilizzato" in second.output
    assert (fake_source.workdir / "tracks" / "01 - First Song.opus").exists()


def test_override_applies_to_existing_plan(fake_source, tmp_path):
    assert run("--yes", "--no-library").exit_code == 0
    again = run("--yes", "--no-library", "--force", "--artist", "New Artist")
    assert again.exit_code == 0, again.output
    assert "New Artist" in plan_file(fake_source).read_text(encoding="utf-8")


def test_duplicate_refused_before_review(fake_source, tmp_path):
    lib = tmp_path / "lib"
    assert run("--yes", "-l", str(lib)).exit_code == 0
    second = run("-l", str(lib))  # no input: if it asked for a review it would abort differently
    assert second.exit_code == 1
    assert "già in libreria" in second.output and "Piano:" not in second.output
    allowed = run("--yes", "-l", str(lib), "--allow-duplicate")
    assert allowed.exit_code == 0, allowed.output
    assert len(list_tracks(lib)) == 4


def test_no_terminal_and_no_yes_does_nothing(fake_source, tmp_path):
    lib = tmp_path / "lib"
    r = run("-l", str(lib))  # stdin is empty: the prompt cannot be answered
    assert r.exit_code != 0
    assert not lib.exists()


def test_yes_with_invalid_existing_plan_fails(fake_source, tmp_path):
    assert run("--yes", "--no-library").exit_code == 0
    path = plan_file(fake_source)
    path.write_text(path.read_text(encoding="utf-8").replace('"One"', '""'), encoding="utf-8")
    r = run("--yes", "--no-library", "--force")
    assert r.exit_code == 1 and "titolo vuoto" in r.output


def test_windows_library_rejected_before_downloading(fake_source):
    r = run("--yes", "-l", "/mnt/c/Music")
    assert r.exit_code == 1 and "disco Windows" in r.output
    assert fake_source.calls == []  # nothing was fetched


def test_default_library_comes_from_env(fake_source, tmp_path, monkeypatch):
    lib = tmp_path / "from-env"
    monkeypatch.setenv(ENV_LIBRARY, str(lib))
    assert run("--yes").exit_code == 0
    assert (lib / ".taper" / "library.db").exists()


def test_plan_command_overrides(fake_source, tmp_path):
    r = runner.invoke(
        app,
        ["plan", str(fake_source.audio), "--artist", "A", "--album", "B", "--year", "2001",
         "-o", str(tmp_path / "p.yaml")],
    )  # fmt: skip
    assert r.exit_code == 0, r.output
    text = (tmp_path / "p.yaml").read_text(encoding="utf-8")
    assert 'artist: "A"' in text and 'album: "B"' in text and "year: 2001" in text


# ------------------------------------------------ errors and cover (Opus review)


def _locked_dir(tmp_path):
    import os

    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    return locked


def test_unwritable_library_fails_before_downloading(fake_source, tmp_path):
    locked = _locked_dir(tmp_path)
    try:
        r = run("--yes", "-l", str(locked / "lib"))
        assert r.exit_code == 1 and "scrivibile" in r.output
        assert "Traceback" not in r.output and fake_source.calls == []  # nothing was fetched
    finally:
        locked.chmod(0o700)


def test_unwritable_output_folder_is_a_clean_error(fake_source, tmp_path):
    locked = _locked_dir(tmp_path)
    plan_path = fake_source.audio.with_name("p.yaml")
    from taper.core.plan import save_plan

    save_plan(_plan_for_cut(), plan_path)
    try:
        r = runner.invoke(
            app,
            ["cut", str(fake_source.audio), "--plan", str(plan_path), "--no-library",
             "-o", str(locked / "tracks")],
        )  # fmt: skip
        assert r.exit_code == 1 and "Errore di accesso ai file" in r.output
        assert "Traceback" not in r.output
    finally:
        locked.chmod(0o700)


def _plan_for_cut():
    from taper.models import AlbumMeta, CutPlan, Segment

    return CutPlan(
        "source.opus",
        AlbumMeta("A", "B", 2000),
        [Segment(0, 15_000, "One"), Segment(15_000, 40_000, "Two")],
    )


def test_no_library_still_writes_cover_jpg_next_to_tracks(fake_source):
    r = run("--yes", "--no-library")
    assert r.exit_code == 0, r.output
    cover = fake_source.workdir / "tracks" / "cover.jpg"
    assert cover.exists() and "Copertina:" in r.output
    # a second run must not clobber it (never overwrite), and must not crash on it
    before = cover.read_bytes()
    again = run("--yes", "--no-library", "--force")
    assert again.exit_code == 0 and cover.read_bytes() == before


def test_library_export_removed_by_hand_can_be_exported_again(fake_source, tmp_path):
    """Opus review: delete the album folder, run again -> no 'already in library' / traceback."""
    import shutil

    lib = tmp_path / "lib"
    assert run("--yes", "-l", str(lib)).exit_code == 0
    shutil.rmtree(next((lib / "Fan channel").iterdir()))  # the user deletes the album folder
    again = run("--yes", "-l", str(lib))
    assert again.exit_code == 0, again.output
    assert "Traceback" not in again.output and len(list_tracks(lib)) == 2
