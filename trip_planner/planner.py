from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from .config import PACE_MAX_ACTIVITIES
from .hotel import HotelRepository, get_hotel_provider
from .models import BudgetItem, DayPlan, Hotel, ItineraryItem, POI, TripPlan, TripRequest
from .poi import City, POIRepository, preferred_tags
from .providers import MockRouteProvider, RouteInfo
from .rag import GuideIndex
from .tripdb import new_trip_id


def _minutes(value: str) -> int:
    hour, minute = (int(x) for x in value.split(":"))
    return hour * 60 + minute


def _clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _weekday(value: str) -> str:
    return date.fromisoformat(value).strftime("%A")


class TripPlanner:
    def __init__(
        self,
        poi_repo: POIRepository | None = None,
        guide_index: GuideIndex | None = None,
        route_provider=None,
        hotel_provider=None,
        photo_provider=None,
        meal_provider=None,
    ):
        self.poi_repo = poi_repo or POIRepository()
        self.guide_index = guide_index or GuideIndex()
        self.route_provider = route_provider or MockRouteProvider()
        self.hotel_provider = hotel_provider or get_hotel_provider("local")
        self.photo_provider = photo_provider
        self.meal_provider = meal_provider

    def build(
        self,
        request: TripRequest,
        hotel_options: list[Hotel] | None = None,
        selected_hotel: Hotel | None = None,
    ) -> TripPlan:
        if request.days < 1:
            raise ValueError("旅行天数至少为 1 天。")
        city = self.poi_repo.get_city(request.city)
        if self.photo_provider is not None:
            self.photo_provider.enrich_city(city, city.pois)
        preferred = preferred_tags(request.preferences, city)
        must_visit = self._must_visit(city, request.must_visit)
        candidates = self._ordered_candidates(city, preferred, must_visit)
        max_activities = PACE_MAX_ACTIVITIES.get(request.pace, 3)
        used: set[str] = set()
        days: list[DayPlan] = []
        start = date.fromisoformat(request.start_date)
        nights = max(1, request.days - 1)
        if hotel_options is None:
            hotel_options = self.hotel_provider.search(
                city, request.budget / nights, request.preferences, limit=3
            )
        if selected_hotel is None:
            selected_hotel = (
                self.hotel_provider.get(request.hotel_id)
                if hasattr(self.hotel_provider, "get") and request.hotel_id
                else None
            )
        if selected_hotel is None and hotel_options:
            selected_hotel = hotel_options[0]

        base_location = (
            (selected_hotel.lat, selected_hotel.lon)
            if selected_hotel
            else city.center
        )
        for offset in range(request.days):
            day_date = (start + timedelta(days=offset)).isoformat()
            weekday = _weekday(day_date)
            day_items: list[ItineraryItem] = []
            current = base_location
            clock = 9 * 60
            remaining_days = request.days - offset
            remaining_pois = max(0, len(candidates) - len(used))
            day_target = max(
                1, min(max_activities, math.ceil(remaining_pois / remaining_days))
            )
            for _ in range(day_target):
                poi = self._pick_next(
                    city, candidates, used, weekday, preferred, must_visit, current
                )
                if poi is None:
                    break
                route = self.route_provider.route(current, (poi.lat, poi.lon))
                arrival = max(9 * 60, clock + route.minutes)
                end = arrival + poi.visit_minutes
                # Keep the day human-sized; paid items are dropped later if over budget.
                if end > 19 * 60:
                    break
                item = ItineraryItem(
                    day=offset + 1,
                    seq=len(day_items) + 1,
                    poi_id=poi.id,
                    poi_name=poi.name,
                    category=poi.category,
                    start=_clock(arrival),
                    end=_clock(end),
                    travel_minutes=route.minutes,
                    ticket=poi.ticket,
                    note=poi.description,
                    photo_url=poi.photo_url,
                    lat=poi.lat,
                    lon=poi.lon,
                )
                day_items.append(item)
                used.add(poi.id)
                current = (poi.lat, poi.lon)
                clock = end

            theme = self._theme(day_items)
            days.append(
                DayPlan(
                    day=offset + 1,
                    date=day_date,
                    theme=theme,
                    items=day_items,
                    daily_cost=sum(item.ticket for item in day_items) + 150 + 80,
                    daily_minutes=clock - 9 * 60,
                )
            )

        plan = TripPlan(
            trip_id=new_trip_id(city.id, request.start_date),
            request=request,
            days=days,
            budget_items=[],
            total_cost=0,
            hotel_options=hotel_options,
            selected_hotel=selected_hotel,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.recalculate_budget(plan, city)
        plan.citations = [
            hit.to_dict()
            for hit in self.guide_index.search(
                city.id, f"{request.preferences} {city.name}", limit=8
            )
        ]
        for day in plan.days:
            if day.items and plan.citations:
                day.items[0].guide_citation = (
                    f"{plan.citations[0]['doc_name']} · {plan.citations[0]['heading']}"
                )
        meals = (
            self.meal_provider.search(city, 10)
            if self.meal_provider is not None
            else []
        )
        self._fill_full_day(plan, city, meals)
        plan.summary = self._summary(plan, city)
        self._attach_issues(plan, city)
        return plan

    def repair(self, plan: TripPlan, max_rounds: int = 4) -> TripPlan:
        """Deterministic repair loop: only touch what the validator flags."""
        from .validator import rebuild_times, validate_plan

        city = self.poi_repo.get_city(plan.request.city)
        for _ in range(max_rounds):
            issues = validate_plan(plan, self.poi_repo, self.route_provider, city)
            high = [issue for issue in issues if issue.severity == "high"]
            if not high:
                break
            changed = False
            for issue in high:
                if issue.code == "over_budget":
                    candidate = None
                    for day in reversed(plan.days):
                        for item in day.items:
                            if item.ticket > 0 and (
                                candidate is None or item.ticket > candidate.ticket
                            ):
                                candidate = item
                    if candidate is not None:
                        for day in plan.days:
                            day.items = [item for item in day.items if item is not candidate]
                        changed = True
                        break
                if issue.code == "too_many_activities" and issue.day:
                    day = plan.days[issue.day - 1]
                    if day.items:
                        day.items.pop()
                        changed = True
                        break
                if issue.code in {"duplicate_poi", "closed_day"} and issue.day:
                    day = plan.days[issue.day - 1]
                    if day.items:
                        day.items.pop()
                        changed = True
                        break
                if issue.code == "missing_must_visit":
                    # Add the missing POI to the first day that has capacity.
                    for poi in city.pois:
                        if issue.message.find(poi.name) >= 0 or poi.name in issue.message:
                            target = next(
                                (
                                    d
                                    for d in plan.days
                                    if sum(1 for item in d.items if item.kind == "poi")
                                    < PACE_MAX_ACTIVITIES.get(plan.request.pace, 3)
                                ),
                                None,
                            )
                            if target is not None:
                                target.items.append(
                                    ItineraryItem(
                                        day=target.day,
                                        seq=len(target.items) + 1,
                                        poi_id=poi.id,
                                        poi_name=poi.name,
                                        category=poi.category,
                                        start="09:00",
                                        end="10:00",
                                        travel_minutes=0,
                                        ticket=poi.ticket,
                                        note=poi.description,
                                        lat=poi.lat,
                                        lon=poi.lon,
                                    )
                                )
                                changed = True
                            break
                    if changed:
                        break
            if not changed:
                break
            self.recalculate_budget(plan, city)
            rebuild_times(plan, city, self.route_provider)

        plan.issues = validate_plan(plan, self.poi_repo, self.route_provider, city)
        plan.summary = self._summary(plan, city)
        return plan

    def _must_visit(self, city: City, values: list[str]) -> list[POI]:
        result = []
        for value in values:
            for poi in city.pois:
                if value == poi.id or value in poi.name:
                    result.append(poi)
                    break
        return result

    def _ordered_candidates(
        self, city: City, preferred: list[str], must_visit: list[POI]
    ) -> list[POI]:
        must_ids = {poi.id for poi in must_visit}
        def key(poi: POI):
            tag_hits = sum(1 for tag in preferred if tag in poi.tags or tag in city.tags)
            return (poi.id in must_ids, tag_hits, poi.score)
        return sorted(city.pois, key=key, reverse=True)

    def _pick_next(
        self,
        city: City,
        candidates: list[POI],
        used: set[str],
        weekday: str,
        preferred: list[str],
        must_visit: list[POI],
        current: tuple[float, float],
    ) -> POI | None:
        must_ids = {poi.id for poi in must_visit}
        available = [
            poi for poi in candidates
            if poi.id not in used and weekday not in poi.closed_days
        ]
        if not available:
            return None
        must_available = [poi for poi in available if poi.id in must_ids]
        pool = must_available or available
        # Prefer a high-scoring seed, then the nearest next stop.
        pool = sorted(pool, key=lambda poi: (-poi.score, poi.ticket))[:8]
        return min(
            pool,
            key=lambda poi: self.route_provider.route(
                current, (poi.lat, poi.lon)
            ).minutes,
        )

    def _fill_full_day(self, plan: TripPlan, city: City, meals=None) -> None:
        """Add real restaurant recommendations, rest and evening slots."""
        meals = meals or []
        base = (
            (plan.selected_hotel.lat, plan.selected_hotel.lon)
            if plan.selected_hotel
            else city.center
        )
        for day in plan.days:
            if not day.items:
                continue
            last_end = max(_minutes(item.end) for item in day.items)
            lunch_start = max(12 * 60, last_end + 30)
            lunch_end = lunch_start + 60
            rest_start = max(15 * 60, lunch_end + 60)
            rest_end = rest_start + 75
            dinner_start = max(18 * 60, rest_end + 30)
            dinner_end = dinner_start + 60
            evening_start = dinner_end + 30
            evening_end = evening_start + 60
            lunch = meals[(day.day - 1) * 2] if len(meals) > (day.day - 1) * 2 else None
            dinner = (
                meals[(day.day - 1) * 2 + 1]
                if len(meals) > (day.day - 1) * 2 + 1
                else None
            )
            fixed = [
                (
                    lunch.id if lunch else "fixed_lunch",
                    lunch.name if lunch else "午餐 · 就近自由选择",
                    "food",
                    lunch_start,
                    lunch_end,
                    (
                        (
                            f"高德餐厅 · {lunch.rating:.1f} 分 · {lunch.address}"
                            + (f" · 人均约 ¥{lunch.cost:.0f}" if lunch.cost > 0 else "")
                        )
                        if lunch and lunch.rating > 0
                        else "不含指定商家，餐饮预算已计入。"
                    ),
                    lunch.photo_url if lunch else "",
                    (lunch.lat, lunch.lon) if lunch else base,
                    "meal",
                ),
                ("fixed_rest", "下午茶 / 休息", "rest", rest_start, rest_end,
                 "自由安排，避免全天赶路。", "", base, "rest"),
                (
                    dinner.id if dinner else "fixed_dinner",
                    dinner.name if dinner else "晚餐 · 就近自由选择",
                    "food",
                    dinner_start,
                    dinner_end,
                    (
                        (
                            f"高德餐厅 · {dinner.rating:.1f} 分 · {dinner.address}"
                            + (f" · 人均约 ¥{dinner.cost:.0f}" if dinner.cost > 0 else "")
                        )
                        if dinner and dinner.rating > 0
                        else "不含指定商家，餐饮预算已计入。"
                    ),
                    dinner.photo_url if dinner else "",
                    (dinner.lat, dinner.lon) if dinner else base,
                    "meal",
                ),
                ("fixed_evening", "夜间散步 / 自由活动", "nightlife", evening_start, evening_end,
                 "可选，按当天体力安排。", "", base, "evening"),
            ]
            for poi_id, name, category, start, end, note, photo, location, kind in fixed:
                if end > 21 * 60 + 30:
                    continue
                day.items.append(
                    ItineraryItem(
                        day=day.day,
                        seq=len(day.items) + 1,
                        poi_id=poi_id,
                        poi_name=name,
                        category=category,
                        start=_clock(start),
                        end=_clock(end),
                        travel_minutes=0,
                        ticket=0,
                        note=note,
                        kind=kind,
                        photo_url=photo,
                        lat=location[0],
                        lon=location[1],
                    )
                )
            day.daily_minutes = max(_minutes(item.end) for item in day.items) - 9 * 60
            day.daily_cost = round(sum(item.ticket for item in day.items) + 150 + 80, 2)

    def _theme(self, items: list[ItineraryItem]) -> str:
        tags = []
        for item in items:
            for tag in item.category.split(","):
                if tag and tag not in tags:
                    tags.append(tag)
        return " · ".join(tags) if tags else "自由活动"

    def recalculate_budget(self, plan: TripPlan, city: City) -> None:
        tickets = sum(
            item.ticket for day in plan.days for item in day.items
        )
        nights = max(0, plan.request.days - 1)
        nightly_rate = (
            plan.selected_hotel.price
            if plan.selected_hotel and plan.selected_hotel.price > 0
            else city.hotel_rate
        )
        hotel = nights * nightly_rate
        meals = plan.request.days * 150
        transport = plan.request.days * 80 + city.airport_transfer
        subtotal = hotel + meals + transport + tickets
        buffer = round(subtotal * 0.10, 2)
        hotel_label = f"住宿 {nights} 晚"
        if plan.selected_hotel and plan.selected_hotel.price <= 0:
            hotel_label += "（城市均价估算）"
        plan.budget_items = [
            BudgetItem("hotel", hotel_label, round(hotel, 2)),
            BudgetItem("meal", f"餐饮 {plan.request.days} 天", round(meals, 2)),
            BudgetItem("transport", "市内交通 + 机场往返", round(transport, 2)),
            BudgetItem("ticket", "门票", round(tickets, 2)),
            BudgetItem("buffer", "机动 10%", buffer),
        ]
        plan.total_cost = round(sum(item.amount for item in plan.budget_items), 2)
        for day in plan.days:
            day.daily_cost = round(
                sum(item.ticket for item in day.items) + 150 + 80, 2
            )

    def _summary(self, plan: TripPlan, city: City) -> str:
        names = "、".join(
            item.poi_name for day in plan.days for item in day.items[:2]
        )
        if plan.selected_hotel:
            if plan.selected_hotel.price > 0:
                hotel = f"推荐住宿：{plan.selected_hotel.name}（参考 ¥{plan.selected_hotel.price:.0f}/晚）。"
            else:
                hotel = f"推荐住宿：{plan.selected_hotel.name}（参考价待查，预算按城市均价估算）。"
        else:
            hotel = ""
        return (
            f"{city.name} {plan.request.days} 天，预算 {plan.request.budget:.0f} 元，"
            f"当前预估 {plan.total_cost:.0f} 元。{hotel}核心安排：{names or '待补充'}。"
        )

    def _attach_issues(self, plan: TripPlan, city: City) -> None:
        # Lazy import avoids a circular import at module load.
        from .validator import validate_plan

        plan.issues = validate_plan(
            plan, self.poi_repo, self.route_provider, city
        )
