from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date, datetime, timedelta

from .config import PACE_LABELS
from .llm import LLMError, OpenAICompatibleLLM
from .models import POI, TripPlan, TripRequest
from .planner import TripPlanner
from .poi import POIRepository
from .tripdb import TripRepository


class TripAgent:
    """Plan-and-execute agent: LLM parses/narrates, code plans/validates/saves."""

    def __init__(
        self,
        planner: TripPlanner,
        trip_repo: TripRepository,
        llm: OpenAICompatibleLLM | None = None,
        hotel_provider=None,
    ):
        self.planner = planner
        self.trip_repo = trip_repo
        self.llm = llm
        self.poi_repo = planner.poi_repo
        self.hotel_provider = hotel_provider or planner.hotel_provider

    def plan_from_text(self, text: str, save: bool = True) -> TripPlan:
        trace: list[dict] = []
        parsed = self._parse_with_llm(text)
        if parsed:
            trace.append({"step": "parse", "tool": "llm", "detail": "LLM 解析需求", "ok": True})
        else:
            parsed = self.parse_text(text)
            trace.append({"step": "parse", "tool": "rule", "detail": "规则解析需求", "ok": True})
        request = self._to_request(parsed, text)
        return self._plan(request, trace, save=save)

    def plan(self, request: TripRequest, save: bool = True) -> TripPlan:
        trace = [{"step": "request", "tool": "form", "detail": "使用表单需求", "ok": True}]
        return self._plan(request, trace, save=save)

    def _plan(self, request: TripRequest, trace: list[dict], save: bool = True) -> TripPlan:
        plan = self.planner.build(request)
        trace.append(
            {
                "step": "build",
                "tool": "TripPlanner",
                "detail": f"生成 {len(plan.days)} 天初版，预估 {plan.total_cost:.0f} 元",
                "ok": True,
            }
        )
        before = len([i for i in plan.issues if i.severity == "high"])
        plan = self.planner.repair(plan)
        after = len([i for i in plan.issues if i.severity == "high"])
        trace.append(
            {
                "step": "validate",
                "tool": "Validator",
                "detail": f"高优先级问题 {before} → {after}",
                "ok": after == 0,
            }
        )
        if save:
            self.trip_repo.create(plan)
            trace.append(
                {
                    "step": "save",
                    "tool": "SQLite",
                    "detail": f"已创建 {plan.db_path}",
                    "ok": True,
                }
            )
        else:
            trace.append(
                {
                    "step": "save",
                    "tool": "SQLite",
                    "detail": "未保存，等待用户选择",
                    "ok": True,
                }
            )
        if self.llm is not None and self.llm.configured:
            try:
                plan.summary = self.llm.narrate(
                    plan.summary,
                    json.dumps([day.to_dict() for day in plan.days], ensure_ascii=False),
                ) or plan.summary
                trace.append(
                    {"step": "narrate", "tool": "llm", "detail": "LLM 生成行程说明", "ok": True}
                )
            except LLMError as exc:
                trace.append(
                    {
                        "step": "narrate",
                        "tool": "llm",
                        "detail": f"LLM 失败，使用模板说明：{exc}",
                        "ok": False,
                    }
                )
        plan.trace = trace + plan.trace
        return plan

    def recommendations(self, plan: TripPlan) -> list[POI]:
        city = self.poi_repo.get_city(plan.request.city)
        used_ids = {
            item.poi_id
            for day in plan.days
            for item in day.items
            if item.kind == "poi"
        }
        names = {item.poi_name for day in plan.days for item in day.items}
        if len([poi for poi in city.pois if poi.id not in used_ids and poi.category != "food"]) < 3:
            self.poi_repo.add_extra_pois(city, "景点", 10)
        result = [
            poi
            for poi in city.pois
            if poi.id not in used_ids and poi.name not in names
        ]
        # Add real restaurant candidates for the "美食" recommendation bucket.
        if self.planner.meal_provider is not None:
            for restaurant in self.planner.meal_provider.search(city, 10):
                if restaurant.name in names:
                    continue
                result.append(
                    POI(
                        id=restaurant.id,
                        name=restaurant.name,
                        category="food",
                        lat=restaurant.lat,
                        lon=restaurant.lon,
                        visit_minutes=60,
                        ticket=0,
                        open="09:00",
                        close="22:00",
                        tags=["高德餐厅"],
                        area="",
                        score=restaurant.rating,
                        description=(
                            f"高德餐厅 · {restaurant.address}"
                            + (
                                f" · 人均约 ¥{restaurant.cost:.0f}"
                                if restaurant.cost > 0
                                else ""
                            )
                        ),
                        photo_url=restaurant.photo_url,
                    )
                )
        result.sort(key=lambda poi: poi.score, reverse=True)
        return result[:10]

    def add_places(
        self,
        plan: TripPlan,
        names: list[str],
        extra_pois: list[POI] | None = None,
        save: bool = True,
    ) -> TripPlan:
        city = self.poi_repo.get_city(plan.request.city)
        known = {poi.id for poi in city.pois}
        for poi in extra_pois or []:
            if poi.id not in known:
                city.pois.append(poi)
                known.add(poi.id)
        must_visit = list(dict.fromkeys(plan.request.must_visit + names))
        request = replace(plan.request, must_visit=must_visit)
        new_plan = self.planner.build(
            request,
            hotel_options=plan.hotel_options,
            selected_hotel=plan.selected_hotel,
        )
        new_plan.trip_id = plan.trip_id
        new_plan.created_at = plan.created_at
        new_plan = self.planner.repair(new_plan)
        if save and plan.db_path:
            self.trip_repo.create(new_plan, reason=f"add:{','.join(names)}")
        new_plan.trace = [
            {
                "step": "add",
                "tool": "POI",
                "detail": "加入：" + "、".join(names),
                "ok": True,
            },
            {
                "step": "save",
                "tool": "SQLite",
                "detail": f"新版本 v{new_plan.version}" if save and plan.db_path else "未保存",
                "ok": True,
            },
        ] + plan.trace
        return new_plan

    def replan(self, plan: TripPlan, hotel, save: bool = True) -> TripPlan:
        """Apply a selected hotel and persist it as a new plan version."""
        request = plan.request
        new_plan = self.planner.build(
            request,
            hotel_options=plan.hotel_options,
            selected_hotel=hotel,
        )
        new_plan.trip_id = plan.trip_id
        new_plan.created_at = plan.created_at
        new_plan = self.planner.repair(new_plan)
        if save:
            self.trip_repo.create(new_plan, reason=f"hotel:{hotel.name}")
        new_plan.trace = [
            {"step": "hotel", "tool": "HotelProvider", "detail": f"选择 {hotel.name}", "ok": True},
            {
                "step": "save",
                "tool": "SQLite",
                "detail": f"新版本 v{new_plan.version}" if save else "未保存",
                "ok": True,
            },
        ] + plan.trace
        return new_plan

    def _parse_with_llm(self, text: str) -> dict | None:
        if self.llm is None or not self.llm.configured:
            return None
        try:
            return self.llm.parse_request(
                text,
                [city.name for city in self.poi_repo.list_cities()],
                date.today().isoformat(),
            )
        except Exception:
            return None

    def _to_request(self, data: dict, raw_text: str) -> TripRequest:
        place = str(data.get("place") or "").strip()
        if not place:
            for alias in self.poi_repo.PLACE_ALIASES:
                if alias in raw_text:
                    place = alias
                    break
        city = self.poi_repo.resolve_city_from_place(place) if place else None
        if city is None:
            try:
                city = self.poi_repo.get_city(str(data.get("city", "成都")))
            except ValueError as exc:
                supported = "、".join(c.name for c in self.poi_repo.list_cities())
                raise ValueError(f"{exc} 当前支持：{supported}") from exc
        start = str(data.get("start_date") or (date.today() + timedelta(days=7)).isoformat())
        try:
            date.fromisoformat(start)
        except ValueError:
            start = (date.today() + timedelta(days=7)).isoformat()
        days = int(data.get("days") or 3)
        budget = float(data.get("budget") or 5000)
        pace = data.get("pace") if data.get("pace") in PACE_LABELS else "balanced"
        named_poi = self.poi_repo.add_place(city, place) if place else None
        must = data.get("must_visit") or []
        if not isinstance(must, list):
            must = []
        if named_poi is not None and named_poi.name not in must:
            must.append(named_poi.name)
        return TripRequest(
            city=city.id,
            start_date=start,
            days=max(1, min(days, 6)),
            budget=budget,
            origin=str(data.get("origin") or "深圳"),
            preferences=str(data.get("preferences") or raw_text),
            pace=pace,
            must_visit=[str(item) for item in must],
            raw_text=raw_text,
        )

    def parse_text(self, text: str) -> dict:
        city = next(
            (c for c in self.poi_repo.list_cities() if c.name in text),
            self.poi_repo.list_cities()[0],
        )
        today = date.today()
        start = today + timedelta(days=7)
        days = 3

        iso_dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if iso_dates:
            start = date.fromisoformat(iso_dates[0])
            if len(iso_dates) >= 2:
                days = (date.fromisoformat(iso_dates[1]) - start).days + 1
        else:
            range_match = re.search(
                r"(\d{1,2})月(\d{1,2})[日号]?\s*[-~到至]\s*(\d{1,2})[日号]?",
                text,
            )
            single_match = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", text)
            if range_match:
                month, day1, day2 = (int(x) for x in range_match.groups())
                start = date(today.year, month, day1)
                days = max(1, day2 - day1 + 1)
            elif single_match:
                month, day1 = (int(x) for x in single_match.groups())
                start = date(today.year, month, day1)

        day_match = re.search(r"(\d+)\s*天", text)
        if day_match:
            days = int(day_match.group(1))

        budget_match = re.search(r"预算\s*(\d+)", text) or re.search(r"(\d+)\s*元", text)
        budget = float(budget_match.group(1)) if budget_match else 5000

        origin_match = re.search(r"从(.{1,8}?)出发", text)
        origin = origin_match.group(1) if origin_match else "深圳"
        pace = "balanced"
        if re.search(r"轻松|慢|不赶|放松|不想太赶|别太赶|不要太赶", text):
            pace = "relaxed"
        elif re.search(r"紧凑|特种兵|多去", text):
            pace = "packed"

        must = []
        must_match = re.search(r"(?:必去|想去|一定要去)[：:]\s*([^\n。；;]+)", text)
        if must_match:
            must = [x.strip() for x in re.split(r"[、,，]", must_match.group(1)) if x.strip()]

        return {
            "city": city.id,
            "start_date": start.isoformat(),
            "days": days,
            "budget": budget,
            "origin": origin,
            "preferences": text,
            "pace": pace,
            "must_visit": must,
        }
