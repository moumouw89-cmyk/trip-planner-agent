from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from .config import AMAP_API_KEY, AMAP_CITY_CODES, BAIDU_AK
from .poi import City

_AMAP_LOCK = threading.Lock()
_AMAP_LAST = 0.0


def amap_throttle(interval: float = 0.35) -> None:
    """Keep sequential Amap calls below the free-key QPS limit."""
    global _AMAP_LAST
    with _AMAP_LOCK:
        wait = interval - (time.monotonic() - _AMAP_LAST)
        if wait > 0:
            time.sleep(wait)
        _AMAP_LAST = time.monotonic()


@dataclass
class RouteInfo:
    minutes: int
    distance_km: float
    mode: str = "taxi"
    provider: str = "mock"


@dataclass
class WeatherInfo:
    city: str
    date: str
    text: str
    temperature: str
    provider: str = "mock"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


class MockRouteProvider:
    name = "mock"

    def route(self, origin: tuple[float, float], dest: tuple[float, float]) -> RouteInfo:
        distance = haversine_km(origin[0], origin[1], dest[0], dest[1])
        # City traffic and parking buffer; this is intentionally conservative.
        minutes = max(8, int(distance * 1.35 / 24 * 60 + 10))
        return RouteInfo(minutes=minutes, distance_km=round(distance, 2), provider=self.name)


class AmapRouteProvider:
    name = "amap"

    def __init__(self, api_key: str = AMAP_API_KEY, fallback: MockRouteProvider | None = None):
        self.api_key = api_key
        self.fallback = fallback or MockRouteProvider()
        self._cache: dict[tuple[tuple[float, float], tuple[float, float]], RouteInfo] = {}

    def route(self, origin: tuple[float, float], dest: tuple[float, float]) -> RouteInfo:
        if not self.api_key:
            return self.fallback.route(origin, dest)
        cache_key = (origin, dest)
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            amap_throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/direction/driving",
                params={
                    "origin": f"{origin[1]:.6f},{origin[0]:.6f}",
                    "destination": f"{dest[1]:.6f},{dest[0]:.6f}",
                    "extensions": "base",
                    "key": self.api_key,
                },
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            path = data["route"]["paths"][0]
            minutes = max(5, int(float(path["duration"]) / 60))
            info = RouteInfo(
                minutes=minutes,
                distance_km=round(float(path.get("distance", 0)) / 1000, 2),
                provider=self.name,
            )
            self._cache[cache_key] = info
            return info
        except Exception:
            return self.fallback.route(origin, dest)


class MockWeatherProvider:
    name = "mock"

    def weather(self, city: City, day: str) -> WeatherInfo:
        month = datetime.fromisoformat(day).month
        if city.id in {"chengdu", "hangzhou"}:
            text = "多云" if month in {3, 4, 5, 9, 10, 11} else "阴"
        elif city.id in {"xiamen", "shenzhen"}:
            text = "晴间多云"
        else:
            text = "晴"
        return WeatherInfo(city=city.name, date=day, text=text, temperature="18-26℃", provider=self.name)


class AmapWeatherProvider:
    name = "amap"

    def __init__(self, api_key: str = AMAP_API_KEY, fallback: MockWeatherProvider | None = None):
        self.api_key = api_key
        self.fallback = fallback or MockWeatherProvider()

    def weather(self, city: City, day: str) -> WeatherInfo:
        code = AMAP_CITY_CODES.get(city.id)
        if not self.api_key or not code:
            return self.fallback.weather(city, day)
        try:
            amap_throttle()
            response = httpx.get(
                "https://restapi.amap.com/v3/weather/weatherInfo",
                params={"city": code, "extensions": "base", "key": self.api_key},
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            live = data["lives"][0]
            return WeatherInfo(
                city=city.name,
                date=day,
                text=live.get("weather", ""),
                temperature=f"{live.get('temperature_float', '')}℃",
                provider=self.name,
            )
        except Exception:
            return self.fallback.weather(city, day)


class BaiduRouteProvider:
    name = "baidu"

    def __init__(self, ak: str = BAIDU_AK, fallback: MockRouteProvider | None = None):
        self.ak = ak
        self.fallback = fallback or MockRouteProvider()

    def route(self, origin: tuple[float, float], dest: tuple[float, float]) -> RouteInfo:
        if not self.ak:
            return self.fallback.route(origin, dest)
        try:
            response = httpx.get(
                "https://api.map.baidu.com/direction/v2/driving",
                params={
                    "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
                    "destination": f"{dest[0]:.6f},{dest[1]:.6f}",
                    "ak": self.ak,
                },
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            route = data["result"]["routes"][0]
            return RouteInfo(
                minutes=max(5, int(route["duration"] / 60)),
                distance_km=round(float(route["distance"]) / 1000, 2),
                provider=self.name,
            )
        except Exception:
            return self.fallback.route(origin, dest)


class BaiduWeatherProvider:
    name = "baidu"

    def __init__(self, ak: str = BAIDU_AK, fallback: MockWeatherProvider | None = None):
        self.ak = ak
        self.fallback = fallback or MockWeatherProvider()

    def weather(self, city: City, day: str) -> WeatherInfo:
        code = AMAP_CITY_CODES.get(city.id)
        if not self.ak or not code:
            return self.fallback.weather(city, day)
        try:
            response = httpx.get(
                "https://api.map.baidu.com/weather/v1/",
                params={"district_id": code, "data_type": "all", "ak": self.ak},
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            now = data["result"]["forecast"][0] if data["result"].get("forecast") else data["result"].get("now", {})
            return WeatherInfo(
                city=city.name,
                date=day,
                text=now.get("text", ""),
                temperature=f"{now.get('temp', '')}℃",
                provider=self.name,
            )
        except Exception:
            return self.fallback.weather(city, day)


def get_route_provider(name: str = "mock", amap_key: str = AMAP_API_KEY, baidu_ak: str = BAIDU_AK):
    if name == "amap":
        return AmapRouteProvider(amap_key)
    if name == "baidu":
        return BaiduRouteProvider(baidu_ak)
    return MockRouteProvider()


def get_weather_provider(name: str = "mock", amap_key: str = AMAP_API_KEY, baidu_ak: str = BAIDU_AK):
    if name == "amap":
        return AmapWeatherProvider(amap_key)
    if name == "baidu":
        return BaiduWeatherProvider(baidu_ak)
    return MockWeatherProvider()
