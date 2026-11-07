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


def test_ydl_options_have_no_reencoding_postprocessor(tmp_path):
    opts = fetch_mod.build_ydl_options(tmp_path / "100%")
    assert opts["format"] == "bestaudio/best"
    # FFmpegExtractAudio silently re-encodes unknown codecs to mp3: it must never be used.
    assert "postprocessors" not in opts
    assert "100%%" in opts["outtmpl"]["default"]  # % escaped for yt-dlp templates
    assert opts["noplaylist"] is True
    assert opts["no_warnings"] is False  # warnings are forwarded, not swallowed


def test_ydl_warnings_are_forwarded_once(tmp_path):
    events = []
    logger = fetch_mod.build_ydl_options(tmp_path, on_event=events.append)["logger"]
    logger.warning("WARNING: [youtube] falling back to another format")
    logger.warning("WARNING: [youtube] falling back to another format")
    logger.error("ERROR: left to our own message")
    logger.debug("noise")
    assert [(e.stage, e.message) for e in events] == [
        ("warning", "[youtube] falling back to another format")
    ]


def test_native_extension_mapping():
    ne = fetch_mod.native_extension
    assert (ne("opus"), ne("aac"), ne("mp3"), ne("vorbis"), ne("flac")) == (
        ".opus", ".m4a", ".mp3", ".ogg", ".flac",
    )  # fmt: skip
    assert ne("pcm_s16le") == ".wav" and ne("alac") == ".m4a"
    assert ne("ac3") is None and ne("eac3") is None and ne("dts") is None


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

    downloads = 0

    def process_ie_result(self, ie_result, download=True):
        return self.extract_info("process", download=download)

    def extract_info(self, url, download=True):
        if FakeYDL.behavior == "unsupported":
            raise DownloadError(f"ERROR: Unsupported URL: {url}")
        if not download:  # metadata only, nothing on disk
            return dict(YDL_INFO)
        FakeYDL.downloads += 1
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
    FakeYDL.downloads = 0
    monkeypatch.setattr(fetch_mod.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(fetch_mod, "remux_native", lambda path, **kw: path)
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
    assert "download" in stages and stages[-1] == "fetch_done"
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


def test_fetch_reuses_complete_download(patched, tmp_path):
    first = fetch_mod.fetch("https://example.com/watch?v=abc123", tmp_path)
    events = []
    second = fetch_mod.fetch("https://example.com/watch?v=abc123", tmp_path, on_event=events.append)
    assert FakeYDL.downloads == 1  # the second call did not download again
    assert second.audio == first.audio and second.info == first.info
    assert second.thumbnail == first.thumbnail
    assert any("riuso" in e.message for e in events)


def test_fetch_incomplete_download_is_not_reused(patched, tmp_path):
    fetch_mod.fetch("https://example.com/watch?v=abc123", tmp_path)
    (tmp_path / "abc123" / "abc123.taper.json").unlink()  # sidecar missing = incomplete
    assert fetch_mod.find_existing(tmp_path, "abc123") is None
    import shutil

    shutil.rmtree(tmp_path / "abc123")
    fetch_mod.fetch("https://example.com/watch?v=abc123", tmp_path)
    assert FakeYDL.downloads == 2


@pytest.mark.parametrize(
    ("text", "message", "hint_part"),
    [
        ("ERROR: Unsupported URL: http://x", "URL non supportato", "list-extractors"),
        ("ERROR: [generic] 'abc' is not a valid URL", "URL non valido", "https://"),
        (
            "ERROR: [generic] n: Unable to download webpage: HTTP Error 404: Not Found",
            "404",
            "indirizzo",
        ),
        (
            "ERROR: <urlopen error [Errno -3] Temporary failure in name resolution>",
            "Connessione",
            "internet",
        ),
        (
            "ERROR: [youtube] x: Private video. Sign in if you've been granted access",
            "senza accesso",
            "cookie",
        ),
        ("ERROR: [youtube] x: Video unavailable", "non disponibile", "browser"),
        ("ERROR: [youtube] x: n challenge solving failed", "Download fallito", "yt-dlp"),
    ],
)
def test_describe_download_error(text, message, hint_part):
    msg, hint = fetch_mod.describe_download_error(text, "http://u")
    assert message in msg and hint_part in hint
    assert not msg.startswith("ERROR")


def test_update_hint_only_for_unclassified_errors():
    _, hint = fetch_mod.describe_download_error("ERROR: Unsupported URL: x", "x")
    assert "deno" not in hint and "upgrade" not in hint
    assert "deno" in fetch_mod.describe_download_error("ERROR: boom", "x")[1]


# ----------------------------------------------- real remux (stream copy, ffmpeg needed)

import subprocess  # noqa: E402

from helpers import needs_ffmpeg  # noqa: E402


def _make(tmp_path, name, *args):
    out = tmp_path / name
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
           "sine=frequency=440:sample_rate=48000:duration=3", *args, str(out)]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"encoder non disponibile: {proc.stderr.strip()[-100:]}")
    return out


@needs_ffmpeg
@pytest.mark.parametrize(
    ("name", "args", "codec", "ext"),
    [
        ("a.webm", ["-c:a", "libopus", "-b:a", "64k"], "opus", ".opus"),
        ("b.mp4", ["-c:a", "aac", "-b:a", "96k"], "aac", ".m4a"),
        ("c.mkv", ["-c:a", "libmp3lame", "-b:a", "96k"], "mp3", ".mp3"),
        ("d.mka", ["-c:a", "flac"], "flac", ".flac"),
    ],
)
def test_remux_native_is_a_stream_copy(tmp_path, name, args, codec, ext):
    from taper.core.ffmpeg import probe_audio

    src = _make(tmp_path, name, *args)
    before = probe_audio(src)
    out = fetch_mod.remux_native(src)
    after = probe_audio(out)
    assert out.suffix == ext and out.exists() and (not src.exists() or src == out)
    assert after.codec == codec == before.codec  # same codec: nothing was re-encoded
    assert abs(after.duration_ms - before.duration_ms) < 100
    assert not list(tmp_path.glob("*.part*"))


@needs_ffmpeg
def test_remux_native_refuses_to_reencode_unknown_codecs(tmp_path):
    """Opus review: an AC3 source used to become a 64 kbps mp3 with no warning at all."""
    src = _make(tmp_path, "clip.mp4", "-c:a", "ac3", "-b:a", "384k")
    with pytest.raises(SourceError) as exc:
        fetch_mod.remux_native(src)
    assert "ac3" in exc.value.message and "ricodifica" in (exc.value.hint or "")
    assert src.exists() and not list(tmp_path.glob("*.mp3"))  # nothing was converted or deleted


@needs_ffmpeg
def test_remux_native_drops_video_stream(tmp_path):
    from taper.core.ffmpeg import probe_audio

    out = tmp_path / "v.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
           "-f", "lavfi", "-i", "color=c=red:s=64x64:d=2",
           "-c:a", "aac", "-c:v", "mpeg4", "-shortest", str(out)]  # fmt: skip
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        pytest.skip("mpeg4 encoder not available")
    result = fetch_mod.remux_native(out)
    probe = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0"]
    streams = subprocess.run([*probe, str(result)], capture_output=True, text=True).stdout.split()
    assert streams == ["audio"] and probe_audio(result).codec == "aac"
