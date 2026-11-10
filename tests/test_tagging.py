import io
import shutil

import pytest
from PIL import Image
from typer.testing import CliRunner

from helpers import CODEC_ARGS, make_audio, needs_ffmpeg
from taper.cli import app
from taper.core.cover import (
    find_cover_source,
    make_square_cover,
    save_cover_jpg,
    square_crop_box,
)
from taper.core.pipeline import cut_and_tag
from taper.core.plan import save_plan
from taper.core.sidecar import save_sidecar
from taper.core.tagging import TrackTags, read_tags, tags_for_plan, write_tags
from taper.errors import SourceError
from taper.models import AlbumMeta, CutPlan, Segment, SourceInfo

# ------------------------------------------------------------------------ cover


def _image(path, size, mode="RGB", fmt=None):
    colour = (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)
    Image.new(mode, size, colour).save(path, fmt)
    return path


def test_square_crop_box():
    assert square_crop_box(1280, 720) == (280, 0, 1000, 720)
    assert square_crop_box(720, 1280) == (0, 280, 720, 1000)
    assert square_crop_box(500, 500) == (0, 0, 500, 500)


def test_cover_is_square_jpeg(tmp_path):
    cover = make_square_cover(_image(tmp_path / "t.png", (1280, 720)))
    assert (cover.width, cover.height) == (720, 720)
    img = Image.open(io.BytesIO(cover.data))
    assert img.format == "JPEG" and img.size == (720, 720)


def test_cover_never_upscaled_but_capped(tmp_path):
    small = make_square_cover(_image(tmp_path / "s.png", (160, 90)))
    assert (small.width, small.height) == (90, 90)
    big = make_square_cover(_image(tmp_path / "b.png", (4000, 3000)))
    assert (big.width, big.height) == (1200, 1200)


def test_cover_from_webp_and_transparent_png(tmp_path):
    assert make_square_cover(_image(tmp_path / "t.webp", (320, 180), fmt="WEBP")).width == 180
    flat = make_square_cover(_image(tmp_path / "a.png", (100, 100), mode="RGBA"))
    assert Image.open(io.BytesIO(flat.data)).mode == "RGB"


def test_cover_unreadable(tmp_path):
    bad = tmp_path / "x.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(SourceError):
        make_square_cover(bad)


def test_save_cover_jpg_and_find_source(tmp_path):
    audio = tmp_path / "abc.opus"
    assert find_cover_source(audio) is None
    thumb = _image(tmp_path / "abc.webp", (320, 180), fmt="WEBP")
    assert find_cover_source(audio) == thumb
    assert find_cover_source(audio, "abc.webp") == thumb
    dest = save_cover_jpg(make_square_cover(thumb), tmp_path / "cover.jpg")
    assert Image.open(dest).size == (180, 180)
    assert find_cover_source(tmp_path / "other.mp3") == dest  # falls back to cover.jpg


# ------------------------------------------------------------------------ tags


def _plan(n=3):
    return CutPlan(
        "source",
        AlbumMeta("Beyoncé & Friends", 'Live à Paris: "Night" 日本', 1999),
        [Segment(i * 10_000, (i + 1) * 10_000, f"Song №{i + 1} \u2014 ünï") for i in range(n)],
    )


def test_tags_for_plan():
    t = tags_for_plan(_plan(), 2)
    assert (t.number, t.total, t.year) == (2, 3, 1999)
    assert t.title == "Song №2 \u2014 ünï"
    assert t.artist == t.album_artist == "Beyoncé & Friends"


@needs_ffmpeg
@pytest.mark.parametrize("ext", list(CODEC_ARGS))
def test_tag_roundtrip_with_cover(ext, tmp_path_factory, tmp_path):
    src = make_audio(tmp_path_factory, ext, seconds=5)
    track = tmp_path / f"t.{ext}"
    shutil.copy(src, track)
    cover = make_square_cover(_image(tmp_path / "c.png", (320, 180)))
    tags = tags_for_plan(_plan(), 2)

    write_tags(track, tags, cover)
    got, got_cover = read_tags(track)

    assert got == tags
    assert got_cover == cover.data


@needs_ffmpeg
@pytest.mark.parametrize("ext", list(CODEC_ARGS))
def test_retagging_replaces_and_optional_fields(ext, tmp_path_factory, tmp_path):
    src = make_audio(tmp_path_factory, ext, seconds=5)
    track = tmp_path / f"t.{ext}"
    shutil.copy(src, track)
    cover = make_square_cover(_image(tmp_path / "c.png", (100, 100)))
    write_tags(
        track, TrackTags("Old", "Old artist", "Old album", year=1980, number=9, total=9), cover
    )

    write_tags(track, TrackTags("New"))  # no artist/year/number, no cover

    got, got_cover = read_tags(track)
    assert got == TrackTags("New")
    assert got_cover is None


def test_unsupported_extension(tmp_path):
    f = tmp_path / "x.wav"
    f.write_bytes(b"")
    with pytest.raises(SourceError):
        write_tags(f, TrackTags("x"))


# --------------------------------------------------------------------- pipeline


def _prepare_source(tmp_path_factory, with_thumb=True, ext="opus"):
    src = make_audio(tmp_path_factory, ext, seconds=40)
    if with_thumb:
        _image(src.with_name("source.webp"), (320, 180), fmt="WEBP")
    save_sidecar(SourceInfo(title="Video", thumbnail="source.webp" if with_thumb else None), src)
    return src


def _plan3():
    return CutPlan(
        "source.opus",
        AlbumMeta("The Band", "Live 99", 1999),
        [
            Segment(0, 10_000, "One"),
            Segment(10_000, 25_000, "Two"),
            Segment(25_000, 40_000, "Three"),
        ],
    )


@needs_ffmpeg
def test_cut_and_tag_numbers_and_covers(tmp_path_factory, tmp_path):
    src = _prepare_source(tmp_path_factory)
    out = cut_and_tag(src, _plan3(), tmp_path / "t", info=SourceInfo("V", thumbnail="source.webp"))
    assert out.cover is not None and out.notes == []
    for r in out.results:
        tags, cover = read_tags(r.path)
        assert (tags.number, tags.total) == (r.index, 3)
        assert tags.title == r.segment.title and tags.album == "Live 99" and tags.year == 1999
        assert cover == out.cover.data
    assert read_tags(out.results[1].path)[0].title == "Two"


@needs_ffmpeg
def test_cut_and_tag_without_cover_or_artist(tmp_path_factory, tmp_path):
    src = _prepare_source(tmp_path_factory, with_thumb=False)
    plan = _plan3()
    plan.album.artist = None
    out = cut_and_tag(src, plan, tmp_path / "t")
    assert out.cover is None
    assert any("copertina" in n for n in out.notes) and any("artista" in n for n in out.notes)
    tags, cover = read_tags(out.results[0].path)
    assert tags.artist is None and cover is None


@needs_ffmpeg
def test_no_cover_option_ignores_available_image(tmp_path_factory, tmp_path):
    src = _prepare_source(tmp_path_factory)
    out = cut_and_tag(src, _plan3(), tmp_path / "t", embed_cover=False)
    assert out.cover is None and read_tags(out.results[0].path)[1] is None


@needs_ffmpeg
def test_cli_cut_writes_tags(tmp_path_factory):
    src = _prepare_source(tmp_path_factory)
    plan_path = src.with_name("p.yaml")
    save_plan(_plan3(), plan_path)
    result = CliRunner().invoke(app, ["cut", str(src), "--plan", str(plan_path), "--no-library"])
    assert result.exit_code == 0, result.output
    assert "con copertina" in result.output
    tags, cover = read_tags(src.parent / "tracks" / "02 - Two.opus")
    assert (tags.title, tags.number, tags.total, tags.artist) == ("Two", 2, 3, "The Band")
    assert cover is not None
