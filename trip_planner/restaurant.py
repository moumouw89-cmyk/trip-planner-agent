from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import AMAP_API_KEY
from .poi import City, _throttle


@dataclass
class Restaurant:
    id: str
    name: str
    address: str
    rating: float
    cost: float
    lat: float
    lon: float
    photo_url: str = ""


class AmapRestaurantProvider:
    """Real Amap restaurant POIs, used for lunch/dinner recommendations."""

    def __init__(self, api_key: str = AMAP_API_KEY):
        self.api_key = (api_key or "").strip()
        self._cache: dict[str, list[Restaurant]] = {}

    def search(self, city: City, limit: int = 10) -> list[Restaurant]:
        if not self.api_key:
            return []
        if city.id in self._cache:
            return self._cache[city.id]
        try:
            data = None
            for attempt in range(3):
                try:
                    _throttle()
                    response = httpx.get(
                        "https://restapi.amap.com/v3/place/text",
                        params={
                            "keywords": "餐厅",
                            "city": city.name,
                            "citylimit": "true",
                            "types": "050000",
                            "offset": max(limit, 10),
                            "page": 1,
                            "extensions": "all",
                            "key": self.api_key,
                        },
                        timeout=15,
                    )
                    response.raise_for_status()
                    data = response.json()
                    break
                except Exception:
                    if attempt < 2:
                        import time

                        time.sleep(1.0)
            if data is None:
                return []
            restaurants = []
            for poi in data.get("pois") or []:
                location = poi.get("location") or ""
                if "," not in location:
                    continue
                lng, lat = (float(x) for x in location.split(","))
                biz = poi.get("biz_ext") or {}
                photos = poi.get("photos") or []
                restaurants.append(
                    Restaurant(
                        id="meal_" + str(poi.get("id") or len(restaurants)),
                        name=poi.get("name") or "餐厅",
                        address=poi.get("address") or "",
                        rating=float(biz.get("rating") or 0),
                        cost=_price(biz.get("cost")),
                        lat=lat,
                        lon=lng,
                        photo_url=photos[0].get("url", "") if photos else "",
                    )
                )
            restaurants.sort(key=lambda r: (r.rating, bool(r.photo_url)), reverse=True)
            self._cache[city.id] = restaurants[:limit]
            return self._cache[city.id]
        except Exception:
            return []


def _price(value) -> float:
    import re

    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else 0.0
