from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from taper.cli import app
from taper.core import plan as plan_mod
from taper.core.ffmpeg import AudioInfo, parse_silencedetect
from taper.core.plan import (
    PlanOptions,
    dump_plan,
    generate_plan,
    load_plan,
    plan_from_data,
    save_plan,
    segments_from_chapters,
    segments_from_description,
    segments_from_silences,
    validate_plan,
)
from taper.core.sidecar import save_sidecar
from taper.errors import InvalidPlanError, TaperError
from taper.models import AlbumMeta, Chapter, CutPlan, Segment, SourceInfo

DURATION = 600_000


def _info(**kw):
    base = dict(title="Band Live", uploader="Fan channel", upload_date="20240131")
    base.update(kw)
    return SourceInfo(**base)


# ----------------------------------------------------------------- segment sources


def test_chapters_clamped_and_titled():
    chapters = [Chapter(0, 100_000, "A"), Chapter(100_000, 900_000, " "), Chapter(5, 5, "z")]
    segs = segments_from_chapters(chapters, DURATION)
    assert [(s.start_ms, s.end_ms, s.title) for s in segs] == [
        (0, 100_000, "A"),
        (100_000, DURATION, "Track 02"),
    ]
    assert all(s.source == "chapters" for s in segs)


def test_single_chapter_is_not_a_split():
    assert segments_from_chapters([Chapter(0, DURATION, "All")], DURATION) == []


def test_description_contiguous_last_ends_at_duration():
    segs = segments_from_description("00:00 A\n03:00 B\n07:00 C", DURATION)
    assert [(s.start_ms, s.end_ms) for s in segs] == [
        (0, 180_000),
        (180_000, 420_000),
        (420_000, DURATION),
    ]


def test_description_drops_entries_past_duration():
    segs = segments_from_description("00:00 A\n03:00 B\n20:00 C", DURATION)
    assert [s.title for s in segs] == ["A", "B"]
    assert segs[-1].end_ms == DURATION


def test_description_range_end_honoured():
    segs = segments_from_description("00:00 - 02:00 A\n03:00 - 05:00 B", DURATION)
    assert [(s.start_ms, s.end_ms) for s in segs] == [(0, 120_000), (180_000, 300_000)]


def test_parse_silencedetect():
    log = """
[silencedetect @ 0x1] silence_start: 10.5
[silencedetect @ 0x1] silence_end: 12.5 | silence_duration: 2
[silencedetect @ 0x1] silence_start: 100
"""
    assert parse_silencedetect(log) == [(10_500, 12_500)]
    assert parse_silencedetect(log, duration_ms=120_000) == [(10_500, 12_500), (100_000, 120_000)]


def test_silences_cut_in_the_middle_and_merge_short():
    silences = [(59_000, 61_000), (70_000, 72_000), (130_000, 132_000)]
    segs = segments_from_silences(silences, DURATION, min_segment_ms=30_000)
    # 70-72s would give a 10s segment: skipped
    assert [(s.start_ms, s.end_ms) for s in segs] == [
        (0, 60_000),
        (60_000, 131_000),
        (131_000, DURATION),
    ]
    assert [s.title for s in segs] == ["Track 01", "Track 02", "Track 03"]


def test_silences_short_tail_merged():
    segs = segments_from_silences([(59_000, 61_000), (595_000, 597_000)], DURATION, 30_000)
    assert [(s.start_ms, s.end_ms) for s in segs] == [(0, 60_000), (60_000, DURATION)]


def test_no_silence_gives_single_segment():
    segs = segments_from_silences([], DURATION, 30_000)
    assert [(s.start_ms, s.end_ms) for s in segs] == [(0, DURATION)]


# ------------------------------------------------------------------ generate_plan


def _no_silence(*a, **k):
    raise AssertionError("silence detection must not run")


def test_priority_chapters_first():
    info = _info(
        chapters=[Chapter(0, 300_000, "A"), Chapter(300_000, DURATION, "B")],
        description="00:00 X\n01:00 Y",
    )
    res = generate_plan(Path("a.opus"), info, DURATION, detector=_no_silence)
    assert res.source == "chapters"
    assert [s.title for s in res.plan.segments] == ["A", "B"]


def test_falls_back_to_description():
    info = _info(description="00:00 X\n01:00 Y")
    res = generate_plan(Path("a.opus"), info, DURATION, detector=_no_silence)
    assert res.source == "description"


def test_falls_back_to_silence_and_warns_when_none():
    res = generate_plan(Path("a.opus"), None, DURATION, detector=lambda *a, **k: [])
    assert res.source == "silence"
    assert len(res.plan.segments) == 1
    assert any("un solo segmento" in n for n in res.notes)
    assert res.plan.album.album == "a"  # local file: album from the file stem


def test_forced_source_unavailable():
    with pytest.raises(TaperError):
        generate_plan(
            Path("a.opus"), _info(), DURATION, PlanOptions(source="chapters"), detector=_no_silence
        )


def test_invalid_source_name():
    with pytest.raises(TaperError):
        generate_plan(Path("a.opus"), _info(), DURATION, PlanOptions(source="bogus"))


def test_notes_flag_guessed_artist_and_year():
    info = _info(description="00:00 X\n01:00 Y")
    res = generate_plan(Path("a.opus"), info, DURATION)
    assert res.plan.album.artist == "Fan channel"
    assert res.plan.album.year == 2024
    text = " ".join(res.notes)
    assert "Fan channel" in text and "20240131" in text


def test_uncovered_start_noted():
    res = generate_plan(Path("a.opus"), _info(description="00:30 X\n03:00 Y"), DURATION)
    assert any("non sono coperti" in n for n in res.notes)


# ------------------------------------------------------------------------- YAML


def _plan():
    return CutPlan(
        source_file="a.opus",
        album=AlbumMeta("John Mayer", 'Live: "Talkhouse"', 2026),
        segments=[
            Segment(0, 268_000, "No", "chapters"),
            Segment(268_000, 3_753_000, "I Don't Trust Myself (With Loving You)", "manual"),
            Segment(3_753_000, 3_800_500, "日本語 🎸", "description"),
        ],
    )


def test_yaml_roundtrip_tricky_values(tmp_path):
    plan = _plan()
    path = save_plan(plan, tmp_path / "p.yaml", ["nota"])
    assert load_plan(path) == plan
    assert "DA VERIFICARE" in path.read_text(encoding="utf-8")


def test_dump_always_quotes_times_and_titles():
    data = yaml.safe_load(dump_plan(_plan()))
    assert data["segments"][0]["title"] == "No"  # str, not bool
    assert isinstance(data["segments"][1]["start"], str)


def test_save_never_overwrites(tmp_path):
    path = tmp_path / "p.yaml"
    save_plan(_plan(), path)
    with pytest.raises(TaperError):
        save_plan(_plan(), path)
    save_plan(_plan(), path, overwrite=True)


def test_load_accepts_unquoted_sexagesimal_times(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text(
        'version: 1\nsource_file: "a.opus"\nalbum: {artist: X, album: Y, year: 1999}\n'
        "segments:\n"
        '  - {start: 00:00, end: 1:02:33, title: "A"}\n'
        '  - {start: 1:02:33.5, end: 5000, title: "B"}\n',
        encoding="utf-8",
    )
    plan = load_plan(path)
    assert [(s.start_ms, s.end_ms) for s in plan.segments] == [
        (0, 3_753_000),
        (3_753_500, 5_000_000),
    ]


def test_load_collects_all_problems(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text(
        "version: 1\nsource_file: a.opus\nalbum: {year: abc}\n"
        "segments:\n"
        "  - {start: 0, end: 10, title: No}\n"  # bool title
        "  - {start: nope, end: 20, title: B}\n"
        "  - {start: 5}\n",
        encoding="utf-8",
    )
    with pytest.raises(InvalidPlanError) as exc:
        load_plan(path)
    text = "\n".join(exc.value.problems)
    assert "album.year" in text
    assert "segmento 1" in text and "title" in text
    assert "segmento 2" in text and "start" in text
    assert "segmento 3" in text and "end" in text


def test_load_broken_yaml_and_wrong_shape(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(InvalidPlanError):
        load_plan(bad)
    with pytest.raises(InvalidPlanError):
        plan_from_data(["not", "a", "map"])
    with pytest.raises(TaperError):
        load_plan(tmp_path / "missing.yaml")


# --------------------------------------------------------------------- validation


def test_validate_ok():
    assert validate_plan(_plan(), duration_ms=4_000_000) == []


def test_validate_reports_every_problem_with_index():
    plan = CutPlan(
        "a.opus",
        AlbumMeta(year=99999),
        [
            Segment(0, 100_000, "A"),
            Segment(50_000, 40_000, "  "),
            Segment(90_000, 700_000, "C"),
        ],
    )
    problems = validate_plan(plan, duration_ms=600_000)
    text = "\n".join(problems)
    assert "segmento 2" in text and "titolo vuoto" in text and "deve essere dopo start" in text
    assert "inizia a" in text  # overlap
    assert "segmento 3" in text and "oltre la durata" in text
    assert "album.year" in text


def test_validate_empty_plan():
    assert validate_plan(CutPlan("a.opus")) == ["il piano non ha segmenti"]


def test_validate_gaps_are_allowed():
    plan = CutPlan("a", segments=[Segment(0, 10_000, "A"), Segment(20_000, 30_000, "B")])
    assert validate_plan(plan) == []


# ---------------------------------------------------------------------------- CLI

runner = CliRunner()


def test_cli_plan_from_sidecar(tmp_path, monkeypatch):
    audio = tmp_path / "x.opus"
    audio.write_bytes(b"fake")
    save_sidecar(_info(description="00:00 Intro\n03:10 Song"), audio)
    monkeypatch.setattr(
        "taper.core.ffmpeg.probe_audio", lambda p: AudioInfo("opus", DURATION, 128000, 48000, 2)
    )
    result = runner.invoke(app, ["plan", str(audio)])
    assert result.exit_code == 0, result.output
    assert "description" in result.output and "Intro" in result.output
    plan = load_plan(tmp_path / "x.plan.yaml")
    assert [s.title for s in plan.segments] == ["Intro", "Song"]

    again = runner.invoke(app, ["plan", str(audio)])
    assert again.exit_code == 1 and "esiste già" in again.output
    assert runner.invoke(app, ["plan", str(audio), "--force"]).exit_code == 0


def test_module_exports():
    assert plan_mod.SOURCE_CHOICES[0] == "auto"


def test_album_override_wins_and_drops_matching_notes():
    info = _info(description="00:00 X\n01:00 Y")
    plain = generate_plan(Path("a.opus"), info, DURATION)
    over = generate_plan(
        Path("a.opus"), info, DURATION, album_override=AlbumMeta("The Band", "Live 99", 1999)
    )
    assert over.plan.album == AlbumMeta("The Band", "Live 99", 1999)
    assert len(plain.notes) == 3 and over.notes == []
    partial = generate_plan(Path("a.opus"), info, DURATION, album_override=AlbumMeta(artist="Me"))
    assert partial.plan.album.artist == "Me" and partial.plan.album.year == 2024
    assert len(partial.notes) == 2  # the artist note is gone, year/album notes remain


def test_too_short_segment_is_invalid():
    plan = CutPlan("a", segments=[Segment(0, 10, "tiny"), Segment(10, 20_000, "ok")])
    problems = validate_plan(plan)
    assert len(problems) == 1 and "troppo breve" in problems[0] and "segmento 1" in problems[0]


@pytest.mark.parametrize("value", [".inf", "inf", "-.inf", ".nan"])
def test_load_plan_rejects_infinite_times(tmp_path, value):
    path = tmp_path / "p.yaml"
    segment = f'  - {{start: {value}, end: 5, title: "A"}}'
    path.write_text(f'version: 1\nsource_file: "a.opus"\nsegments:\n{segment}\n', encoding="utf-8")
    with pytest.raises(InvalidPlanError) as exc:
        load_plan(path)
    assert "segmento 1" in "\n".join(exc.value.problems)


def test_yaml_roundtrip_non_portable_characters(tmp_path):
    title = "a\x7fb\x85c\x9fd e﻿f\ttab"
    plan = CutPlan("a.opus", AlbumMeta("x\x85y", None, None), [Segment(0, 1000, title)])
    path = save_plan(plan, tmp_path / "p.yaml")
    loaded = load_plan(path)
    assert loaded.segments[0].title == title and loaded.album.artist == "x\x85y"
