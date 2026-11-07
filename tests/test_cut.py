import hashlib
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from helpers import CODEC_ARGS, SOURCE_SECONDS, make_audio, needs_ffmpeg
from taper.cli import app
from taper.core import cut as cut_mod
from taper.core.cut import (
    MODE_COPY,
    MODE_LOSSLESS,
    MODE_REENCODE,
    copy_deviation,
    cut_plan,
    profile_for,
    tolerance_ms,
)
from taper.core.ffmpeg import AudioInfo, probe_audio
from taper.core.plan import save_plan
from taper.errors import CancelledError, InvalidPlanError, SourceError, TaperError
from taper.models import AlbumMeta, CutPlan, Segment

# ------------------------------------------------------------------- pure pieces


def _info(duration_ms, start=0):
    return AudioInfo("opus", duration_ms, 128000, 48000, 2, start_time_ms=start)


def test_profile_for_codecs():
    assert profile_for("opus").ext == "opus"
    assert profile_for("aac").ext == "m4a"
    assert profile_for("mp3").encoder == "libmp3lame"
    for lossless in ("flac", "alac", "pcm_s16le"):
        p = profile_for(lossless)
        assert p.lossless and p.ext == "flac"
    with pytest.raises(SourceError):
        profile_for("wmav2")


def test_tolerance_is_two_frames():
    assert tolerance_ms(profile_for("opus"), 48000) == 40.0
    assert tolerance_ms(profile_for("aac"), 44100) == pytest.approx(2 * 1024 / 44100 * 1000)
    assert tolerance_ms(profile_for("mp3"), 44100) == pytest.approx(2 * 1152 / 44100 * 1000)


def test_copy_deviation():
    assert copy_deviation(10_000, _info(10_020, start=17), 40) is None
    assert "durata" in copy_deviation(10_000, _info(10_100), 40)
    # The exact failure seen with input-side -ss: duration is right but the start is 123 ms early.
    assert "inizio" in copy_deviation(10_000, _info(10_000, start=-123), 40)
    assert copy_deviation(10_000, _info(10_000, start=None), 40) is None


# --------------------------------------------------- real ffmpeg with synthetic audio


@pytest.fixture(scope="module", params=list(CODEC_ARGS))
def source(request, tmp_path_factory):
    return make_audio(tmp_path_factory, request.param)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def three_segments() -> CutPlan:
    # Deliberately non-integer boundaries: this is where input-side seeking goes wrong.
    return CutPlan(
        source_file="source",
        album=AlbumMeta("A", "B", 2000),
        segments=[
            Segment(0, 10_123, "One"),
            Segment(10_123, 33_456, "Two: the/second?"),
            Segment(33_456, 60_000, "Three"),
        ],
    )


@needs_ffmpeg
def test_cut_precision_and_original_untouched(source, tmp_path):
    before = sha(source)
    out = tmp_path / "tracks"
    results = cut_plan(source, three_segments(), out)

    assert sha(source) == before  # never modifies the original
    assert len(results) == 3
    expected = [10_123, 23_333, 26_544]
    profile = profile_for(probe_audio(source).codec)
    tol = tolerance_ms(profile, 48000) + (30 if profile.lossless else 0)
    for r, want in zip(results, expected, strict=True):
        assert r.path.exists() and r.path.parent == out
        assert abs(r.audio_info.duration_ms - want) <= max(tol, 60), (r.path.name, r.mode)
        assert not list(out.glob("*.part.*"))  # no temp files left behind
    assert [r.path.name for r in results][1] == f"02 - Two_ the_second_.{profile.ext}"
    # Contiguous plan -> total length preserved (gapless).
    assert abs(sum(r.audio_info.duration_ms for r in results) - SOURCE_SECONDS * 1000) < 200


@needs_ffmpeg
def test_modes_by_codec(source, tmp_path):
    results = cut_plan(source, three_segments(), tmp_path / "t")
    codec = probe_audio(source).codec
    if codec == "flac":
        assert {r.mode for r in results} == {MODE_LOSSLESS}
        assert not any(r.reencoded for r in results)  # lossless -> flac is not a quality loss
    else:
        assert {r.mode for r in results} <= {MODE_COPY, MODE_REENCODE}
        for r in results:
            assert r.reencoded == (r.mode == MODE_REENCODE)
            assert bool(r.warnings) == r.reencoded


@needs_ffmpeg
def test_opus_copy_is_really_stream_copy(tmp_path_factory, tmp_path):
    src = make_audio(tmp_path_factory, "opus")
    results = cut_plan(src, three_segments(), tmp_path / "t")
    assert {r.mode for r in results} == {MODE_COPY}
    assert all(r.audio_info.codec == "opus" for r in results)


@needs_ffmpeg
def test_forced_reencode_warns(tmp_path_factory, tmp_path, monkeypatch):
    src = make_audio(tmp_path_factory, "opus")
    monkeypatch.setattr(cut_mod, "copy_deviation", lambda *a, **k: "durata di prova")
    results = cut_plan(src, three_segments(), tmp_path / "t")
    assert all(r.mode == MODE_REENCODE and r.reencoded for r in results)
    assert all(r.audio_info.codec == "opus" for r in results)  # same codec, not transcoded
    assert "durata di prova" in results[0].warnings[0]
    assert "perdita di qualità" in results[0].warnings[0]
    assert abs(results[0].audio_info.duration_ms - 10_123) < 60


@needs_ffmpeg
def test_never_overwrites_without_force(tmp_path_factory, tmp_path):
    src = make_audio(tmp_path_factory, "opus")
    out = tmp_path / "t"
    cut_plan(src, three_segments(), out)
    with pytest.raises(TaperError) as exc:
        cut_plan(src, three_segments(), out)
    assert "--force" in (exc.value.hint or "")
    assert len(cut_plan(src, three_segments(), out, overwrite=True)) == 3


@needs_ffmpeg
def test_invalid_plan_creates_nothing(tmp_path_factory, tmp_path):
    src = make_audio(tmp_path_factory, "opus")
    bad = CutPlan("x", segments=[Segment(0, 5_000, "A"), Segment(4_000, 99_999_000, "B")])
    out = tmp_path / "t"
    with pytest.raises(InvalidPlanError) as exc:
        cut_plan(src, bad, out)
    assert len(exc.value.problems) == 2
    assert not out.exists()


@needs_ffmpeg
def test_cancel(tmp_path_factory, tmp_path):
    src = make_audio(tmp_path_factory, "opus")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CancelledError):
        cut_plan(src, three_segments(), tmp_path / "t", cancel=cancel)


@needs_ffmpeg
def test_refuses_to_write_over_original(tmp_path_factory):
    src = make_audio(tmp_path_factory, "opus")
    named = src.with_name("01 - One.opus")
    src.rename(named)
    plan = CutPlan("x", segments=[Segment(0, 5_000, "One"), Segment(5_000, 9_000, "Two")])
    with pytest.raises(TaperError):
        cut_plan(named, plan, named.parent, overwrite=True)
    assert named.exists()


@needs_ffmpeg
def test_cli_cut_end_to_end(tmp_path_factory):
    src = make_audio(tmp_path_factory, "opus")
    plan_path = src.with_name("p.yaml")
    save_plan(three_segments(), plan_path)
    runner = CliRunner()
    result = runner.invoke(app, ["cut", str(src), "--plan", str(plan_path), "--no-library"])
    assert result.exit_code == 0, result.output
    assert "Tagliati 3 brani" in result.output and "Nessuna perdita di qualità" in result.output
    assert len(list((src.parent / "tracks").glob("*.opus"))) == 3
    again = runner.invoke(app, ["cut", str(src), "--plan", str(plan_path), "--no-library"])
    assert again.exit_code == 1 and "--force" in again.output
