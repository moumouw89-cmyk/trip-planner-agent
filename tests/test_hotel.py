from __future__ import annotations

from trip_planner.hotel import HotelRepository


def test_local_hotel_search_returns_ranked_options(poi_repo) -> None:
    repo = HotelRepository()
    city = poi_repo.get_city("chengdu")
    hotels = repo.search(city, nightly_budget=400, preferences="安静", limit=3)
    assert hotels
    assert all(hotel.city == "chengdu" for hotel in hotels)
    assert all(hotel.price > 0 for hotel in hotels)


def test_planner_uses_selected_hotel_in_budget(poi_repo, guide_index) -> None:
    from trip_planner.models import TripRequest
    from trip_planner.planner import TripPlanner

    hotel_repo = HotelRepository()
    city = poi_repo.get_city("chengdu")
    options = hotel_repo.search(city, 400, "安静", 3)
    selected = options[-1]
    planner = TripPlanner(poi_repo=poi_repo, guide_index=guide_index, hotel_provider=hotel_repo)
    plan = planner.build(
        TripRequest(
            city="chengdu",
            start_date="2026-11-01",
            days=3,
            budget=5000,
            preferences="安静",
        ),
        hotel_options=options,
        selected_hotel=selected,
    )
    assert plan.selected_hotel == selected
    assert plan.hotel_options
    assert any(item.label.startswith("住宿") for item in plan.budget_items)
