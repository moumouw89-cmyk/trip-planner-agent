from __future__ import annotations

from trip_planner.agent import TripAgent
from trip_planner.planner import TripPlanner
from trip_planner.tripdb import TripRepository


def test_rule_parser_builds_plan(poi_repo, guide_index, tmp_path) -> None:
    planner = TripPlanner(poi_repo=poi_repo, guide_index=guide_index)
    agent = TripAgent(planner, TripRepository(tmp_path / "trips"))
    plan = agent.plan_from_text("11月1-4日成都，预算5000，喜欢美食和自然，不想太赶")
    assert plan.request.city == "chengdu"
    assert plan.request.days == 4
    assert plan.request.pace == "relaxed"
    assert len(plan.days) == 4
    assert any(step["step"] == "save" for step in plan.trace)
    assert plan.db_path


def test_explicit_request(poi_repo, guide_index, tmp_path) -> None:
    from trip_planner.models import TripRequest

    planner = TripPlanner(poi_repo=poi_repo, guide_index=guide_index)
    agent = TripAgent(planner, TripRepository(tmp_path / "trips"))
    plan = agent.plan(
        TripRequest(
            city="xiamen",
            start_date="2026-11-01",
            days=3,
            budget=4000,
            preferences="海边",
        )
    )
    assert plan.request.city == "xiamen"
    assert plan.total_cost > 0
