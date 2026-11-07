import pytest

from taper.core.timestamps import (
    format_short,
    format_time,
    parse_description_timestamps,
    parse_time,
)

REAL_DESCRIPTION = """Credits: SiriusXm
I do not own any of this content. All credits belong to SiriusXm channel.

00:00 Last Train Home
04:28 Queen of California
10:29 Who Says
13:52 Love on the Weekend
18:40 Something Like Olivia
23:54 Belief
31:16 I Don't Trust Myself (With Loving You)
38:25 I Guess I Just Feel Like
45:45 Wild Blue
50:53 In the Blood
55:08 Slow Dancing in a Burning Room
01:03:08 New Light
01:06:58 Free Fallin'
01:11:50 Gravity
01:22:40 Outro"""


@pytest.mark.parametrize(
    ("text", "ms"),
    [
        ("0:00", 0),
        ("00:00", 0),
        ("4:12", 252_000),
        ("1:02:33", 3_753_000),
        ("0:04:28.500", 268_500),
        ("120:30", 7_230_000),
        ("90", 90_000),
        ("90.5", 90_500),
    ],
)
def test_parse_time(text, ms):
    assert parse_time(text) == ms


@pytest.mark.parametrize("text", ["", "abc", "1:99", "1:75:00", "-5", "1:2:3:4", "1:-2"])
def test_parse_time_invalid(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_format_roundtrip():
    for ms in (0, 999, 268_500, 3_753_000, 4_975_000):
        assert parse_time(format_time(ms)) == ms
    assert format_time(3_753_000) == "1:02:33.000"
    assert format_short(268_000) == "4:28"
    assert format_short(3_753_000) == "1:02:33"


def test_real_description():
    entries = parse_description_timestamps(REAL_DESCRIPTION)
    assert len(entries) == 15
    assert (entries[0].start_ms, entries[0].title) == (0, "Last Train Home")
    assert entries[7].title == "I Guess I Just Feel Like"
    assert entries[11].start_ms == 3_788_000  # 1:03:08
    assert entries[-1].title == "Outro"


@pytest.mark.parametrize(
    "text",
    [
        "00:00 Intro\n03:10 Song",
        "0:00 - Intro\n3:10 - Song",
        "[00:00] Intro\n[03:10] Song",
        "(0:00) Intro\n(3:10) Song",
        "1. 00:00 Intro\n2. 03:10 Song",
        "01) 00:00 Intro\n02) 03:10 Song",
        "- 00:00 Intro\n- 03:10 Song",
        "00:00: Intro\n03:10: Song",
        "00:00 — Intro\n03:10 — Song",
        "Intro 00:00\nSong 03:10",
        "Intro - 00:00\nSong - 03:10",
        "Intro (00:00)\nSong (03:10)",
    ],
)
def test_formats(text):
    entries = parse_description_timestamps(text)
    assert [(e.start_ms, e.title) for e in entries] == [(0, "Intro"), (190_000, "Song")]


def test_range_format_second_time_is_end():
    entries = parse_description_timestamps("00:00 - 04:12 Intro\n04:12 - 09:00 Song")
    assert [(e.start_ms, e.end_ms, e.title) for e in entries] == [
        (0, 252_000, "Intro"),
        (252_000, 540_000, "Song"),
    ]


def test_needs_at_least_two():
    assert parse_description_timestamps("00:00 Only one") == []
    assert parse_description_timestamps("no timestamps here") == []


def test_stray_timestamps_do_not_pollute():
    text = "Great show!\n00:00 Intro\n03:10 Song\n05:00 Other\nloved the solo at 1:23 so much"
    entries = parse_description_timestamps(text)
    assert [e.title for e in entries] == ["Intro", "Song", "Other"]


def test_non_increasing_entries_dropped():
    entries = parse_description_timestamps("00:00 A\n05:00 B\n02:00 C\n08:00 D")
    assert [e.title for e in entries] == ["A", "B", "D"]


def test_title_with_digits_and_parentheses():
    entries = parse_description_timestamps("00:00 (Intro) 2000\n03:10 Song (Live)")
    assert entries[0].title == "(Intro) 2000"
    assert entries[1].title == "Song (Live)"


@pytest.mark.parametrize(
    "text",
    [
        "🎵 00:00 Intro\n🎵 03:10 Song",
        "▶ 0:00 Intro\n▶ 3:10 Song",
        "#1 0:00 Intro\n#2 3:10 Song",
        "• 00:00 Intro\n• 03:10 Song",
        "1. Intro 0:00\n2. Song 3:10",  # list number must not leak into the title
        "#1 Intro 0:00\n#2 Song 3:10",
    ],
)
def test_emoji_hash_and_trailing_numbering(text):
    entries = parse_description_timestamps(text)
    assert [(e.start_ms, e.title) for e in entries] == [(0, "Intro"), (190_000, "Song")]


@pytest.mark.parametrize("text", ["inf", "-inf", "nan", "1e999", "0:inf"])
def test_parse_time_non_finite(text):
    with pytest.raises(ValueError):
        parse_time(text)
