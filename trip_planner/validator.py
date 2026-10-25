from __future__ import annotations

from datetime import date

from .config import PACE_MAX_ACTIVITIES
from .models import TripPlan, ValidationIssue
from .poi import City, POIRepository
from .providers import MockRouteProvider


def _minutes(value: str) -> int:
    hour, minute = (int(x) for x in value.split(":"))
    return hour * 60 + minute


def _clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def rebuild_times(plan: TripPlan, city: City, route_provider=None) -> None:
    provider = route_provider or MockRouteProvider()
    base = (
        (plan.selected_hotel.lat, plan.selected_hotel.lon)
        if plan.selected_hotel
        else city.center
    )
    for day in plan.days:
        current = base
        clock = 9 * 60
        for item in day.items:
            if item.kind != "poi":
                clock = max(clock, _minutes(item.end))
                continue
            route = provider.route(current, (item.lat, item.lon))
            arrival = max(9 * 60, clock + route.minutes)
            end = arrival + max(30, _minutes(item.end) - _minutes(item.start))
            item.start = _clock(arrival)
            item.end = _clock(end)
            item.travel_minutes = route.minutes
            clock = end
            current = (item.lat, item.lon)
        day.daily_minutes = clock - 9 * 60
        day.daily_cost = round(sum(item.ticket for item in day.items) + 150 + 80, 2)


def validate_plan(
    plan: TripPlan,
    poi_repo: POIRepository,
    route_provider,
    city: City,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(plan.days) != plan.request.days:
        issues.append(
            ValidationIssue(
                "day_count",
                "high",
                f"计划天数 {len(plan.days)} 与请求 {plan.request.days} 不一致。",
            )
        )
    if plan.total_cost > plan.request.budget + 1e-6:
        issues.append(
            ValidationIssue(
                "over_budget",
                "high",
                f"预估 {plan.total_cost:.0f} 元，超过预算 {plan.request.budget:.0f} 元。",
            )
        )

    max_activities = PACE_MAX_ACTIVITIES.get(plan.request.pace, 3)
    seen: dict[str, int] = {}
    all_names = []
    for day in plan.days:
        poi_count = sum(1 for item in day.items if item.kind == "poi")
        if poi_count > max_activities:
            issues.append(
                ValidationIssue(
                    "too_many_activities",
                    "high",
                    f"第 {day.day} 天安排了 {poi_count} 个景点，超过 {max_activities} 个。",
                    day.day,
                )
            )
        if not day.items:
            issues.append(
                ValidationIssue("empty_day", "low", f"第 {day.day} 天还没有安排活动。", day.day)
            )
        for item in day.items:
            if item.kind != "poi":
                continue
            all_names.append(item.poi_name)
            if item.poi_id in seen:
                issues.append(
                    ValidationIssue(
                        "duplicate_poi",
                        "high",
                        f"{item.poi_name} 重复出现在第 {seen[item.poi_id]} 天和第 {day.day} 天。",
                        day.day,
                    )
                )
            seen[item.poi_id] = day.day
            try:
                poi = poi_repo.find(city.id, item.poi_id)
            except KeyError:
                issues.append(
                    ValidationIssue(
                        "unknown_poi",
                        "high",
                        f"找不到 POI：{item.poi_id}",
                        day.day,
                    )
                )
                continue
            weekday = date.fromisoformat(day.date).strftime("%A")
            if weekday in poi.closed_days:
                issues.append(
                    ValidationIssue(
                        "closed_day",
                        "high",
                        f"{poi.name} 在 {weekday} 闭馆。",
                        day.day,
                    )
                )
            if _minutes(item.end) > 20 * 60:
                issues.append(
                    ValidationIssue(
                        "late_end",
                        "medium",
                        f"第 {day.day} 天结束时间 {item.end} 偏晚。",
                        day.day,
                    )
                )
            if item.travel_minutes > 75:
                issues.append(
                    ValidationIssue(
                        "long_transfer",
                        "medium",
                        f"去 {item.poi_name} 的路程约 {item.travel_minutes} 分钟，偏长。",
                        day.day,
                    )
                )

    for required in plan.request.must_visit:
        if not any(required in name or required == name for name in all_names):
            issues.append(
                ValidationIssue(
                    "missing_must_visit",
                    "high",
                    f"必去点「{required}」还没有安排进行程。",
                )
            )
    return issues
