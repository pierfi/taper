from taper.models import AlbumMeta, Chapter, CutPlan, Segment, SourceInfo, Track


def test_cutplan_roundtrip():
    plan = CutPlan(
        source_file="a.opus",
        album=AlbumMeta(artist="X", album="Y", year=1999),
        segments=[Segment(0, 1000, "One", "chapters"), Segment(1000, 2500, "Two")],
    )
    assert CutPlan.from_dict(plan.to_dict()) == plan


def test_sourceinfo_roundtrip_and_defaults():
    info = SourceInfo(
        title="T",
        uploader="Fan channel",
        creator="The Band",
        upload_date="20240131",
        chapters=[Chapter(0, 10, "c")],
    )
    assert SourceInfo.from_dict(info.to_dict()) == info
    assert info.default_artist == "The Band"  # artist > creator > uploader
    assert info.default_year == 2024


def test_track_roundtrip():
    t = Track("p", "t", None, None, None, 1, 2, "opus", 128000, 1000)
    assert Track.from_dict(t.to_dict()) == t
