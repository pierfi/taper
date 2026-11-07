import threading

import pytest
from yt_dlp.utils import DownloadError

from taper.core import fetch as fetch_mod
from taper.core.ffmpeg import AudioInfo
from taper.core.sidecar import load_sidecar, save_sidecar, sidecar_path
from taper.errors import CancelledError, SourceError, ToolNotFoundError
from taper.models import Chapter

YDL_INFO = {
    "id": "abc123",
    "title": "Band - Live 1999",
    "webpage_url": "https://example.com/watch?v=abc123",
    "uploader": "Fan channel",
    "upload_date": "20240131",
    "description": "00:00 Intro\n03:10 Song",
    "duration": 600.5,
    "chapters": [
        {"start_time": 0, "end_time": 190.0, "title": "Intro"},
        {"start_time": 190.0, "end_time": 600.5, "title": "Song"},
        {"start_time": None, "end_time": 1, "title": "broken"},
    ],
}

AUDIO_INFO = AudioInfo("opus", 600500, 128000, 48000, 2)


def test_source_info_mapping():
    info = fetch_mod.source_info_from_ydl(YDL_INFO, thumbnail="abc123.webp")
    assert info.title == "Band - Live 1999"
    assert info.duration_ms == 600500
    assert info.chapters == [Chapter(0, 190000, "Intro"), Chapter(190000, 600500, "Song")]
    assert info.thumbnail == "abc123.webp"
    assert info.default_year == 2024


def test_ydl_options_keep_native_codec(tmp_path):
    opts = fetch_mod.build_ydl_options(tmp_path / "100%")
    assert opts["format"] == "bestaudio/best"
    pp = opts["postprocessors"][0]
    assert pp == {"key": "FFmpegExtractAudio", "preferredcodec": "best"}
    assert "100%%" in opts["outtmpl"]["default"]  # % escaped for yt-dlp templates
    assert opts["noplaylist"] is True


def test_sidecar_roundtrip(tmp_path):
    audio = tmp_path / "abc.opus"
    info = fetch_mod.source_info_from_ydl(YDL_INFO)
    save_sidecar(info, audio)
    assert sidecar_path(audio).name == "abc.taper.json"
    assert load_sidecar(audio) == info
    assert load_sidecar(tmp_path / "other.mp3") is None


def test_sidecar_invalid(tmp_path):
    audio = tmp_path / "abc.opus"
    sidecar_path(audio).write_text("{not json", encoding="utf-8")
    with pytest.raises(SourceError):
        load_sidecar(audio)


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: creates the files yt-dlp would have produced."""

    behavior = "ok"
    options: dict = {}

    def __init__(self, options):
        FakeYDL.options = options
        self.hooks = options["progress_hooks"]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if FakeYDL.behavior == "unsupported":
            raise DownloadError(f"ERROR: Unsupported URL: {url}")
        for status in (
            {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100},
            {"status": "finished"},
        ):
            for hook in self.hooks:
                hook(status)
        root = FakeYDL.options["outtmpl"]["default"].split("/%(id)s")[0]
        from pathlib import Path

        workdir = Path(root) / "abc123"
        workdir.mkdir(parents=True)
        audio = workdir / "abc123.opus"
        audio.write_bytes(b"fake")
        (workdir / "abc123.webp").write_bytes(b"img")
        return {**YDL_INFO, "requested_downloads": [{"filepath": str(audio)}]}


@pytest.fixture
def patched(monkeypatch):
    FakeYDL.behavior = "ok"
    monkeypatch.setattr(fetch_mod.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(fetch_mod, "find_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(fetch_mod, "probe_audio", lambda path: AUDIO_INFO)


def test_fetch_happy_path(patched, tmp_path):
    events = []
    result = fetch_mod.fetch("https://example.com/watch?v=abc123", tmp_path, on_event=events.append)
    assert result.audio == tmp_path / "abc123" / "abc123.opus"
    assert result.thumbnail == tmp_path / "abc123" / "abc123.webp"
    assert result.sidecar.exists()
    assert load_sidecar(result.audio) == result.info
    assert result.info.thumbnail == "abc123.webp"
    assert result.audio_info.codec == "opus"
    stages = [e.stage for e in events]
    assert "download" in stages and stages[-1] == "done"
    assert events[0].fraction == 0.5


def test_fetch_unsupported_url(patched, tmp_path):
    FakeYDL.behavior = "unsupported"
    with pytest.raises(SourceError) as exc:
        fetch_mod.fetch("http://nope.invalid/x", tmp_path)
    assert "non supportato" in exc.value.message


def test_fetch_cancel_in_hook(patched, tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CancelledError):
        fetch_mod.fetch("https://example.com/x", tmp_path, cancel=cancel)


def test_fetch_requires_ffmpeg(monkeypatch, tmp_path):
    def missing(name):
        raise ToolNotFoundError(f"{name} mancante")

    monkeypatch.setattr(fetch_mod, "find_tool", missing)
    with pytest.raises(ToolNotFoundError):
        fetch_mod.fetch("https://example.com/x", tmp_path)
