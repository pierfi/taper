from pathlib import Path

from taper.core.plan import ensure_valid, load_plan

TEMPLATE = Path(__file__).resolve().parent.parent / "docs" / "templates" / "esempio.plan.yaml"


def test_plan_template_in_docs_is_valid():
    plan = load_plan(TEMPLATE)
    ensure_valid(plan)
    assert [s.title for s in plan.segments] == ["Do", "Mi", "Sol", "Do alto"]
    assert plan.album.artist == "Trio Sintetico"
