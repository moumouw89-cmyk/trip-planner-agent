from __future__ import annotations

from trip_planner.config import PACE_LABELS
from trip_planner.judge import ItineraryJudge
from trip_planner.models import TripRequest
from trip_planner.planner import TripPlanner


def test_heuristic_judge_returns_five_scores(poi_repo, guide_index) -> None:
    planner = TripPlanner(poi_repo=poi_repo, guide_index=guide_index)
    plan = planner.build(
        TripRequest(
            city="chengdu",
            start_date="2026-11-01",
            days=2,
            budget=5000,
            preferences="美食",
            pace="balanced",
        )
    )
    judge = ItineraryJudge().judge(plan)
    assert set(judge.scores) == {
        "feasibility",
        "pacing",
        "preference_fit",
        "budget",
        "explanation",
    }
    assert 1 <= judge.average <= 5
