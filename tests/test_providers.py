from __future__ import annotations

from trip_planner.providers import MockRouteProvider, MockWeatherProvider


def test_mock_route_positive() -> None:
    info = MockRouteProvider().route((30.57, 104.06), (30.73, 104.14))
    assert info.minutes > 0
    assert info.distance_km > 0
    assert info.provider == "mock"


def test_mock_weather(poi_repo) -> None:
    city = poi_repo.get_city("chengdu")
    info = MockWeatherProvider().weather(city, "2026-11-01")
    assert info.city == "成都"
    assert info.temperature
