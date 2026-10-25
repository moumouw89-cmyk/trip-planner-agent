from __future__ import annotations

from trip_planner.agent import TripAgent
from trip_planner.hotel import HotelRepository
from trip_planner.models import TripRequest
from trip_planner.planner import TripPlanner
from trip_planner.tripdb import TripDatabase, TripRepository


def test_replan_with_hotel_creates_v2(poi_repo, guide_index, tmp_path) -> None:
    hotel_repo = HotelRepository()
    planner = TripPlanner(
        poi_repo=poi_repo, guide_index=guide_index, hotel_provider=hotel_repo
    )
    agent = TripAgent(
        planner, TripRepository(tmp_path / "trips"), hotel_provider=hotel_repo
    )
    request = TripRequest(
        city="chengdu",
        start_date="2026-11-01",
        days=3,
        budget=5000,
        preferences="安静",
    )
    plan = agent.plan(request)
    assert plan.hotel_options
    selected = plan.hotel_options[1]
    new_plan = agent.replan(plan, selected)
    assert new_plan.selected_hotel.id == selected.id
    db = TripDatabase(new_plan.db_path)
    try:
        versions = db.versions()
        info = db.conn.execute(
            "SELECT hotel_name, hotel_price FROM trip_info WHERE trip_id = ?",
            (new_plan.trip_id,),
        ).fetchone()
    finally:
        db.close()
    assert len(versions) >= 2
    assert info[0] == selected.name
    assert float(info[1]) == selected.price
