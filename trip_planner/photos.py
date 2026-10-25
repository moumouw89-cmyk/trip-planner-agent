from __future__ import annotations

from typing import Any

import httpx

from .models import POI
from .poi import City
from .providers import amap_throttle


class AmapPhotoProvider:
    """Fetch real POI photos by name from Amap Place Search."""

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def enrich_city(self, city: City, pois: list[POI]) -> None:
        if not self.api_key:
            return
        for poi in pois:
            if poi.photo_url:
                continue
            data = self._lookup(city, poi.name)
            if not data:
                continue
            photos = data.get("photos") or []
            if photos and photos[0].get("url"):
                poi.photo_url = photos[0]["url"]
            biz = data.get("biz_ext") or {}
            rating = biz.get("rating")
            if rating:
                try:
                    poi.score = float(rating)
                except (TypeError, ValueError):
                    pass

    def _lookup(self, city: City, name: str) -> dict[str, Any] | None:
        key = (city.id, name)
        if key in self._cache:
            return self._cache[key]
        try:
            amap_throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/place/text",
                params={
                    "keywords": name,
                    "city": city.name,
                    "citylimit": "true",
                    "offset": 1,
                    "page": 1,
                    "extensions": "all",
                    "key": self.api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            pois = data.get("pois") or []
            result = pois[0] if pois else None
        except Exception:
            result = None
        self._cache[key] = result or {}
        return result
