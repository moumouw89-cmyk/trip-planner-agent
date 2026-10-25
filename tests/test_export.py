from __future__ import annotations

from trip_planner.export import to_ics, to_markdown
from trip_planner.models import TripRequest
from trip_planner.planner import TripPlanner


def test_exports_include_itinerary_and_calendar(poi_repo, guide_index) -> None:
    planner = TripPlanner(poi_repo=poi_repo, guide_index=guide_index)
    plan = planner.build(
        TripRequest(
            city="chengdu",
            start_date="2026-11-01",
            days=2,
            budget=5000,
            preferences="美食",
        )
    )
    markdown = to_markdown(plan)
    ics = to_ics(plan)
    assert "每日行程" in markdown
    assert "BEGIN:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
