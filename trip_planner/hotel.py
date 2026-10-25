from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from .config import AMAP_API_KEY, ROOT
from .models import Hotel
from .poi import City
from .providers import amap_throttle, haversine_km


class HotelRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (ROOT / "data" / "hotels.json"))
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.hotels = [Hotel(**item) for item in raw]

    def get(self, hotel_id: str) -> Hotel | None:
        return next((hotel for hotel in self.hotels if hotel.id == hotel_id), None)

    def search(
        self,
        city: City,
        nightly_budget: float,
        preferences: str = "",
        limit: int = 3,
    ) -> list[Hotel]:
        text = (preferences or "").lower()
        candidates = [hotel for hotel in self.hotels if hotel.city == city.id]
        def score(hotel: Hotel) -> float:
            tag_hits = sum(1 for tag in hotel.tags if tag.lower() in text)
            over = max(0.0, hotel.price - nightly_budget)
            return hotel.rating * 12 + tag_hits * 8 - over / max(nightly_budget, 1) * 30
        candidates.sort(key=score, reverse=True)
        return candidates[:limit]


class AmapHotelProvider:
    """Amap POI search is a reference source, not a booking/inventory API."""

    name = "amap"

    def __init__(self, api_key: str = AMAP_API_KEY, local: HotelRepository | None = None):
        self.api_key = api_key
        self.local = local or HotelRepository()

    def search(
        self,
        city: City,
        nightly_budget: float,
        preferences: str = "",
        limit: int = 3,
    ) -> list[Hotel]:
        if not self.api_key:
            return self.local.search(city, nightly_budget, preferences, limit)
        try:
            amap_throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/place/text",
                params={
                    "keywords": "酒店",
                    "city": city.name,
                    "citylimit": "true",
                    "types": "100101|100102|100103",
                    "offset": max(limit * 5, 15),
                    "page": 1,
                    "extensions": "all",
                    "key": self.api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            hotels = []
            for poi in data.get("pois", []):
                biz = poi.get("biz_ext") or {}
                cost = biz.get("cost")
                price = _price(cost)
                rating = float(biz.get("rating") or 0)
                lng, lat = (float(x) for x in poi.get("location", "0,0").split(","))
                photos = poi.get("photos") or []
                photo_url = photos[0].get("url", "") if photos else ""
                type_name = (poi.get("type") or "").split(";")[-1]
                hotels.append(
                    Hotel(
                        id=f"amap_{poi.get('id', len(hotels))}",
                        city=city.id,
                        name=poi.get("name", "高德酒店"),
                        price=price,
                        rating=rating,
                        area=poi.get("adname", ""),
                        lat=lat,
                        lon=lng,
                        tags=[tag for tag in ["高德", type_name] if tag],
                        address=poi.get("address", ""),
                        source="amap",
                        photo_url=photo_url,
                    )
                )
            def hotel_score(hotel: Hotel) -> float:
                distance = haversine_km(
                    city.center[0], city.center[1], hotel.lat, hotel.lon
                )
                hotel_distance = distance
                return hotel.rating * 10 - min(hotel_distance, 30) * 1.2

            hotels.sort(key=hotel_score, reverse=True)
            nearby = [
                hotel
                for hotel in hotels
                if haversine_km(city.center[0], city.center[1], hotel.lat, hotel.lon) <= 15
            ]
            return (nearby or hotels)[:limit]
        except Exception:
            pass
        return self.local.search(city, nightly_budget, preferences, limit)


class CompositeHotelProvider:
    """Local curated hotels first; optionally merge Amap references."""

    def __init__(self, local: HotelRepository, amap: AmapHotelProvider, use_amap: bool = True):
        self.local = local
        self.amap = amap
        self.use_amap = use_amap and bool(amap.api_key)

    def search(
        self,
        city: City,
        nightly_budget: float,
        preferences: str = "",
        limit: int = 3,
    ) -> list[Hotel]:
        local = self.local.search(city, nightly_budget, preferences, limit)
        if not self.use_amap:
            return local
        remote = self.amap.search(city, nightly_budget, preferences, limit)
        # With a valid Amap key, prefer real hotel POIs. Local hotels are a
        # deliberate demo fallback, not mixed into real results.
        return remote if remote else local


def _price(value) -> float:
    if value is None:
        return 0.0
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else 0.0


def get_hotel_provider(source: str = "auto", amap_key: str = AMAP_API_KEY):
    local = HotelRepository()
    if source == "local":
        return local
    if source == "amap":
        return AmapHotelProvider(amap_key, local)
    return CompositeHotelProvider(local, AmapHotelProvider(amap_key, local), use_amap=True)
