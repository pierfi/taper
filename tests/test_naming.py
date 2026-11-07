from taper.core.naming import (
    album_dirname,
    artist_dirname,
    sanitize_component,
    track_filename,
    unique_path,
)


def test_forbidden_chars_replaced():
    assert sanitize_component('AC/DC: "Live" <1>?') == "AC_DC_ _Live_ _1__"


def test_trailing_dots_and_spaces_stripped():
    assert sanitize_component("Title . .") == "Title"


def test_reserved_names_prefixed():
    assert sanitize_component("CON") == "_CON"
    assert sanitize_component("nul.txt") == "_nul.txt"


def test_empty_gets_fallback():
    assert sanitize_component("   ") == "_"
    assert sanitize_component("...", fallback="X") == "X"


def test_truncation_by_utf8_bytes():
    name = sanitize_component("è" * 300)
    assert len(name.encode("utf-8")) <= 255
    assert set(name) == {"è"}


def test_track_filename_padding_and_ext():
    assert track_filename(3, "Intro", ".opus") == "03 - Intro.opus"
    assert track_filename(7, "X", "m4a", total=120) == "007 - X.m4a"


def test_track_filename_long_title_fits():
    assert len(track_filename(1, "a" * 400, "flac").encode("utf-8")) <= 255


def test_dirnames():
    assert album_dirname(1991, "Live at Wembley") == "1991 - Live at Wembley"
    assert album_dirname(None, "Live") == "Live"
    assert artist_dirname(None) == "Unknown Artist"


def test_unique_path_never_overwrites(tmp_path):
    p = tmp_path / "a.opus"
    assert unique_path(p) == p
    p.write_bytes(b"x")
    assert unique_path(p) == tmp_path / "a (2).opus"
    (tmp_path / "a (2).opus").write_bytes(b"x")
    assert unique_path(p) == tmp_path / "a (3).opus"


def test_leading_dots_do_not_make_hidden_folders():
    assert sanitize_component("...And You Will Know Us") == "And You Will Know Us"
    assert sanitize_component(".hidden") == "hidden"
    assert artist_dirname("...And You Will Know Us") == "And You Will Know Us"
    assert sanitize_component("...", fallback="X") == "X"
