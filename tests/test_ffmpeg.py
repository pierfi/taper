import pytest

from taper.core import ffmpeg
from taper.errors import SourceError, ToolNotFoundError

PROBE_OPUS = {
    "streams": [
        {
            "codec_type": "audio",
            "codec_name": "opus",
            "sample_rate": "48000",
            "channels": 2,
            "bit_rate": "131072",
        }
    ],
    "format": {"format_name": "ogg", "duration": "245.678000", "bit_rate": "135000"},
}


def test_parse_probe_opus():
    info = ffmpeg.parse_probe(PROBE_OPUS)
    assert info.codec == "opus"
    assert info.duration_ms == 245678
    assert info.bitrate == 131072
    assert info.sample_rate == 48000
    assert info.channels == 2


def test_parse_probe_falls_back_to_format_values():
    data = {
        "streams": [{"codec_type": "audio", "codec_name": "flac"}],
        "format": {"duration": "10", "bit_rate": "900000"},
    }
    info = ffmpeg.parse_probe(data)
    assert info.duration_ms == 10000
    assert info.bitrate == 900000


def test_parse_probe_no_audio_stream():
    with pytest.raises(SourceError):
        ffmpeg.parse_probe({"streams": [{"codec_type": "video"}], "format": {}})


def test_parse_probe_no_duration():
    with pytest.raises(SourceError):
        ffmpeg.parse_probe({"streams": [{"codec_type": "audio", "codec_name": "mp3"}]})


def test_find_tool_missing(monkeypatch):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    with pytest.raises(ToolNotFoundError) as exc:
        ffmpeg.find_tool("ffmpeg")
    assert exc.value.hint and "ffmpeg" in exc.value.hint
