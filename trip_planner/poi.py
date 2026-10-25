from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import AMAP_API_KEY, CITIES_PATH, DATA_DIR
from .models import POI

_THROTTLE_LOCK = threading.Lock()
_THROTTLE_LAST = 0.0


def _throttle(interval: float = 0.35) -> None:
    global _THROTTLE_LAST
    with _THROTTLE_LOCK:
        wait = interval - (time.monotonic() - _THROTTLE_LAST)
        if wait > 0:
            time.sleep(wait)
        _THROTTLE_LAST = time.monotonic()


@dataclass
class City:
    id: str
    name: str
    center: tuple[float, float]
    hotel_rate: float
    airport_transfer: float
    tags: list[str] = field(default_factory=list)
    pois: list[POI] = field(default_factory=list)


class POIRepository:
    def __init__(
        self,
        path: str | Path = CITIES_PATH,
        amap_key: str = AMAP_API_KEY,
    ):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.amap_key = (amap_key or "").strip()
        self._dynamic_cache: dict[str, City] = {}
        self._extra_loaded: set[str] = set()
        self.cache_path = DATA_DIR / "dynamic_cities.json"
        self.cities: dict[str, City] = {}
        for item in raw:
            city = City(
                id=item["id"],
                name=item["name"],
                center=tuple(item["center"]),
                hotel_rate=float(item["hotel_rate"]),
                airport_transfer=float(item["airport_transfer"]),
                tags=item.get("tags", []),
                pois=[POI(**poi) for poi in item["pois"]],
            )
            self.cities[city.id] = city
        self._load_cache()

    def list_cities(self) -> list[City]:
        seen = set(self.cities)
        result = list(self.cities.values())
        for city in self._dynamic_cache.values():
            if city.id not in seen:
                seen.add(city.id)
                result.append(city)
        return result

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            for item in raw.get("cities", []):
                city = City(
                    id=item["id"],
                    name=item["name"],
                    center=tuple(item["center"]),
                    hotel_rate=float(item["hotel_rate"]),
                    airport_transfer=float(item["airport_transfer"]),
                    tags=item.get("tags", []),
                    pois=[POI(**poi) for poi in item.get("pois", [])],
                )
                self._dynamic_cache[city.name.lower()] = city
                self._dynamic_cache[city.id] = city
        except Exception:
            # A corrupt cache must never block planning.
            return

    def _save_cache(self) -> None:
        cities = {}
        for city in self._dynamic_cache.values():
            cities[city.id] = city
        payload = {
            "version": 1,
            "cities": [
                {
                    "id": city.id,
                    "name": city.name,
                    "center": list(city.center),
                    "hotel_rate": city.hotel_rate,
                    "airport_transfer": city.airport_transfer,
                    "tags": city.tags,
                    "pois": [poi.__dict__ for poi in city.pois],
                }
                for city in cities.values()
            ],
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cache_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.cache_path)

    def get_city(self, key: str) -> City:
        value = (key or "").strip().lower()
        if value in self.cities:
            return self.cities[value]
        for city in self.cities.values():
            if value == city.name.lower() or value in city.name:
                return city
        if value in self._dynamic_cache:
            return self._dynamic_cache[value]
        if self.amap_key:
            city = self._fetch_dynamic(key)
            if city is not None:
                self._dynamic_cache[value] = city
                self._dynamic_cache[city.id] = city
                self._save_cache()
                return city
        raise ValueError(f"暂时无法获取城市：{key}（高德实时建城失败）")

    # Ambiguous scenic names must resolve to their actual prefecture city.
    PLACE_ALIASES = {
        "老君山": "洛阳",
        "栾川": "洛阳",
        "龙门石窟": "洛阳",
        "白马寺": "洛阳",
    }

    def resolve_city_from_place(self, place: str) -> City | None:
        text = (place or "").strip()
        if not text:
            return None
        for alias, city_name in self.PLACE_ALIASES.items():
            if alias in text:
                try:
                    return self.get_city(city_name)
                except ValueError:
                    pass
        try:
            _throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/place/text",
                params={
                    "keywords": text,
                    "citylimit": "false",
                    "offset": 5,
                    "page": 1,
                    "extensions": "all",
                    "key": self.amap_key,
                },
                timeout=15,
            )
            response.raise_for_status()
            for poi in response.json().get("pois") or []:
                city_name = (poi.get("cityname") or "").strip()
                if city_name:
                    try:
                        return self.get_city(city_name)
                    except ValueError:
                        continue
        except Exception:
            pass
        return None

    def add_place(self, city: City, name: str) -> POI | None:
        """Resolve and append a named landmark (e.g. 老君山) to the city."""
        text = (name or "").strip()
        if not text or not self.amap_key:
            return None
        for poi in city.pois:
            if text in poi.name or poi.name in text:
                return poi
        try:
            _throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/place/text",
                params={
                    "keywords": text,
                    "city": city.name,
                    "citylimit": "true",
                    "offset": 3,
                    "page": 1,
                    "extensions": "all",
                    "key": self.amap_key,
                },
                timeout=15,
            )
            response.raise_for_status()
            for raw in response.json().get("pois") or []:
                poi = self._parse_dynamic_poi(raw, city.name)
                if poi is not None:
                    city.pois.insert(0, poi)
                    return poi
        except Exception:
            pass
        return None

    def add_extra_pois(self, city: City, keyword: str = "景点", limit: int = 10) -> list[POI]:
        """Add more real Amap candidates to a built-in city on demand."""
        if not self.amap_key or city.id in self._extra_loaded:
            return []
        self._extra_loaded.add(city.id)
        known = {poi.name for poi in city.pois}
        added: list[POI] = []
        try:
            _throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/place/text",
                params={
                    "keywords": keyword,
                    "city": city.name,
                    "citylimit": "true",
                    "offset": max(limit, 10),
                    "page": 1,
                    "extensions": "all",
                    "key": self.amap_key,
                },
                timeout=12,
            )
            response.raise_for_status()
            for raw in response.json().get("pois") or []:
                poi = self._parse_dynamic_poi(raw, city.name)
                if poi is not None and poi.name not in known:
                    city.pois.append(poi)
                    known.add(poi.name)
                    added.append(poi)
        except Exception:
            pass
        return added[:limit]

    def _fetch_dynamic(self, city_name: str) -> City | None:
        """Build a real Amap city on demand (not a curated demo city)."""
        name = city_name.strip()
        if not name:
            return None
        center = self._geocode(name)
        if center is None:
            return None
        found: dict[str, POI] = {}
        for keyword in ["景点", "博物馆", "公园", "美食", "购物中心", "地标"]:
            data = None
            for attempt in range(3):
                try:
                    _throttle()
                    response = httpx.get(
                        "https://restapi.amap.com/v3/place/text",
                        params={
                            "keywords": keyword,
                            "city": name,
                            "citylimit": "true",
                            "offset": 8,
                            "page": 1,
                            "extensions": "all",
                            "key": self.amap_key,
                        },
                        timeout=15,
                    )
                    response.raise_for_status()
                    data = response.json()
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(0.8)
            if data is None:
                continue
            for raw in data.get("pois") or []:
                poi = self._parse_dynamic_poi(raw, name)
                if poi is not None and poi.name not in found:
                    found[poi.name] = poi
        pois = list(found.values())
        if len(pois) < 3:
            return None
        city_id = "dynamic_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
        return City(
            id=city_id,
            name=name.removesuffix("市"),
            center=center,
            hotel_rate=350,
            airport_transfer=80,
            tags=["高德实时数据"],
            pois=pois[:20],
        )

    def _geocode(self, name: str) -> tuple[float, float] | None:
        for attempt in range(3):
            try:
                _throttle()
                response = httpx.get(
                    "https://restapi.amap.com/v3/geocode/geo",
                    params={"address": name, "key": self.amap_key},
                    timeout=15,
                )
                response.raise_for_status()
                geocodes = response.json().get("geocodes") or []
                if not geocodes:
                    return None
                lng, lat = (float(x) for x in geocodes[0]["location"].split(","))
                return lat, lng
            except Exception:
                if attempt < 2:
                    time.sleep(1.0)
        return None

    def _parse_dynamic_poi(self, raw: dict, city_name: str) -> POI | None:
        name = (raw.get("name") or "").strip()
        location = raw.get("location") or ""
        if not name or "," not in location:
            return None
        lng, lat = (float(x) for x in location.split(","))
        type_text = raw.get("type") or ""
        category = _category(name, type_text)
        biz = raw.get("biz_ext") or {}
        rating = float(biz.get("rating") or 0)
        cost = _number(biz.get("cost"))
        open_text = str(biz.get("open_time") or "")
        open_match = re.search(r"(\d{1,2}:\d{2})\s*[-~至]\s*(\d{1,2}:\d{2})", open_text)
        open_time = open_match.group(1) if open_match else "09:00"
        close_time = open_match.group(2) if open_match else "18:00"
        photos = raw.get("photos") or []
        photo_url = photos[0].get("url", "") if photos else ""
        visit_minutes = {
            "museum": 120,
            "nature": 120,
            "culture": 90,
            "food": 90,
            "shopping": 90,
            "nightlife": 90,
            "landmark": 75,
        }.get(category, 90)
        note = f"高德实时 POI；预计游玩 {visit_minutes} 分钟（估算），门票/营业时间以官方为准。"
        return POI(
            id="amap_" + str(raw.get("id") or hashlib.md5(name.encode()).hexdigest())[:18],
            name=name,
            category=category,
            lat=lat,
            lon=lng,
            visit_minutes=visit_minutes,
            ticket=cost,
            open=open_time,
            close=close_time,
            closed_days=[],
            tags=[tag for tag in [type_text.split(";")[-1], "高德"] if tag],
            area=raw.get("adname") or city_name,
            score=rating,
            description=note,
            photo_url=photo_url,
        )

    def search(
        self,
        city_key: str,
        query: str = "",
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[POI]:
        city = self.get_city(city_key)
        tags = tags or []
        tokens = _tokens(query)
        scored = []
        for poi in city.pois:
            text = " ".join([poi.name, poi.category, poi.area, *poi.tags, poi.description])
            score = poi.score
            score += sum(1 for token in tokens if token and token in text)
            score += sum(1.5 for tag in tags if tag in poi.tags or tag in city.tags)
            scored.append((score, poi))
        scored.sort(key=lambda item: (-item[0], -item[1].score))
        return [poi for _, poi in scored[:limit]]

    def find(self, city_key: str, poi_id: str) -> POI:
        for poi in self.get_city(city_key).pois:
            if poi.id == poi_id:
                return poi
        raise KeyError(poi_id)


def _category(name: str, type_text: str) -> str:
    text = f"{name} {type_text}"
    if any(word in text for word in ("博物馆", "展览馆", "纪念馆")):
        return "museum"
    if any(word in text for word in ("公园", "山", "湖", "湿地", "景区", "风景")):
        return "nature"
    if any(word in text for word in ("美食", "小吃", "餐饮", "夜市")):
        return "food"
    if any(word in text for word in ("购物", "商场", "商业街")):
        return "shopping"
    if any(word in text for word in ("夜", "酒吧")):
        return "nightlife"
    if any(word in text for word in ("古镇", "寺", "庙", "文化", "古城")):
        return "culture"
    return "landmark"


def _number(value) -> float:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else 0.0


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.split(r"[\s,，、;；/|]+", (text or "").lower())
        if token
    ]


def preferred_tags(text: str, city: City) -> list[str]:
    value = (text or "").lower()
    tags = []
    for tag in city.tags:
        if tag.lower() in value:
            tags.append(tag)
    for poi in city.pois:
        for tag in poi.tags:
            if tag.lower() in value and tag not in tags:
                tags.append(tag)
    return tags
