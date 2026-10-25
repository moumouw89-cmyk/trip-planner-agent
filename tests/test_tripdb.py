from __future__ import annotations

from trip_planner.models import TripRequest
from trip_planner.planner import TripPlanner
from trip_planner.tripdb import TripDatabase, TripRepository


def test_trip_db_created_with_schema(poi_repo, guide_index, tmp_path) -> None:
    planner = TripPlanner(poi_repo=poi_repo, guide_index=guide_index)
    plan = planner.build(
        TripRequest(
            city="chengdu",
            start_date="2026-11-01",
            days=3,
            budget=5000,
            preferences="美食",
        )
    )
    repo = TripRepository(tmp_path / "trips")
    path = repo.create(plan)
    assert path.exists()
    assert plan.db_path == str(path)
    tables = repo.schema(plan.trip_id)
    assert "trip_info" in tables
    assert "itinerary_items" in tables
    assert "plan_versions" in tables
    assert "lodging" in tables
    db = TripDatabase(path)
    try:
        versions = db.versions()
    finally:
        db.close()
    assert versions[0]["version"] == 1
