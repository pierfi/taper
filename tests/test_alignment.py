"""Cut accuracy measured on the DECODED audio, not on container metadata.

A signal with a 10 ms click at every whole second is cut at awkward times; the decoded
tracks must contain the clicks where the plan says. Comparing ffprobe durations (what the
code itself uses) cannot catch a cut that starts early or loses its first packet.
"""

import subprocess
from array import array

import pytest

from helpers import CODEC_ARGS, needs_ffmpeg
from taper.core.cut import cut_plan
from taper.models import AlbumMeta, CutPlan, Segment

pytestmark = needs_ffmpeg

RATE = 48000
SECONDS = 12
# Allowed |onset error| per codec in ms (2 codec frames, plus encoder delay for mp3/aac).
TOLERANCE_MS = {"opus": 45, "m4a": 60, "mp3": 70, "flac": 3}


def make_click_track(tmp_path_factory, ext):
    out = tmp_path_factory.mktemp(f"click_{ext}") / f"clicks.{ext}"
    expr = "aevalsrc=exprs=if(lt(mod(t\\,1)\\,0.01)\\,0.9*sin(2*PI*1000*t)\\,0):s=48000"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", f"{expr}:d={SECONDS}", *CODEC_ARGS[ext], str(out)]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"encoder per {ext} non disponibile: {proc.stderr.strip()[-100:]}")
    return out


def onsets_ms(path):
    """Times (ms) at which a click starts in the decoded audio of `path`."""
    decode = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1"]
    raw = subprocess.run([*decode, "-ar", str(RATE), "-"], capture_output=True, check=True).stdout
    samples = array("h")
    samples.frombytes(raw)
    found, last = [], None
    for i, value in enumerate(samples):
        if abs(value) > 8000 and (last is None or i - last > RATE // 2):
            found.append(i * 1000 / RATE)
            last = i
    return found


def expected_onsets(start_ms, end_ms):
    return [k * 1000 - start_ms for k in range(SECONDS) if start_ms <= k * 1000 < end_ms]


@pytest.fixture(scope="module", params=list(CODEC_ARGS))
def clicks(request, tmp_path_factory):
    return request.param, make_click_track(tmp_path_factory, request.param)


def test_clicks_are_where_the_plan_says(clicks, tmp_path):
    ext, source = clicks
    segments = [Segment(0, 3500, "A"), Segment(3500, 7200, "B"), Segment(7200, 11800, "C")]
    results = cut_plan(source, CutPlan("x", AlbumMeta(), segments), tmp_path / "t")

    for r in results:
        want = expected_onsets(r.segment.start_ms, r.segment.end_ms)
        got = onsets_ms(r.path)
        assert len(got) == len(want), (ext, r.path.name, r.mode, got, want)  # no click lost/added
        for g, w in zip(got, want, strict=True):
            assert abs(g - w) <= TOLERANCE_MS[ext], (ext, r.path.name, r.mode, got, want)


def test_first_segment_starting_at_zero_keeps_its_first_packet(clicks, tmp_path):
    """Opus review: '-ss 0' made ffmpeg drop the first packet of the first track."""
    ext, source = clicks
    results = cut_plan(
        source, CutPlan("x", AlbumMeta(), [Segment(0, 2500, "A"), Segment(2500, 5000, "B")]),
        tmp_path / "t",
    )  # fmt: skip
    first = onsets_ms(results[0].path)
    assert first and first[0] <= TOLERANCE_MS[ext], (ext, first)  # the click at t=0 is there
