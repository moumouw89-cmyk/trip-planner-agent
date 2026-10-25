"""MCP server exposing the same travel tools to external agents.

Run:
    python -m trip_planner.mcp_server
"""

from __future__ import annotations

from datetime import date

from mcp.server.fastmcp import FastMCP

from .hotel import get_hotel_provider
from .poi import POIRepository
from .providers import get_route_provider, get_weather_provider
from .rag import GuideIndex


mcp = FastMCP("trip-planner")
_poi_repo = POIRepository()
_guide_index = GuideIndex()
_route = get_route_provider()
_weather = get_weather_provider()
_hotels = get_hotel_provider("auto")


@mcp.tool()
def search_pois(city: str, query: str = "", limit: int = 10) -> list[dict]:
    """Search demo POIs in a city by free text or tags."""
    return [poi.to_dict() for poi in _poi_repo.search(city, query, limit=limit)]


@mcp.tool()
def search_guides(city: str, query: str, limit: int = 5) -> list[dict]:
    """Search local travel guides and return citation snippets."""
    return [hit.to_dict() for hit in _guide_index.search(city, query, limit=limit)]


@mcp.tool()
def search_hotels(
    city: str, nightly_budget: float = 500, preferences: str = "", limit: int = 3
) -> list[dict]:
    """Recommend hotels from the local curated list (and Amap when configured)."""
    city_obj = _poi_repo.get_city(city)
    return [
        hotel.to_dict()
        for hotel in _hotels.search(city_obj, nightly_budget, preferences, limit)
    ]


@mcp.tool()
def estimate_route(
    origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
) -> dict:
    """Estimate travel time between two coordinates (Amap if configured, mock otherwise)."""
    info = _route.route((origin_lat, origin_lon), (dest_lat, dest_lon))
    return {
        "minutes": info.minutes,
        "distance_km": info.distance_km,
        "provider": info.provider,
    }


@mcp.tool()
def get_weather(city: str, day: str = "") -> dict:
    """Get a weather estimate for a city and date (Amap if configured)."""
    city_obj = _poi_repo.get_city(city)
    day = day or date.today().isoformat()
    info = _weather.weather(city_obj, day)
    return {
        "city": info.city,
        "date": info.date,
        "text": info.text,
        "temperature": info.temperature,
        "provider": info.provider,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
