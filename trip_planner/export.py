from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .models import TripPlan


def to_markdown(plan: TripPlan) -> str:
    request = plan.request
    lines = [
        f"# 行程管家 · {request.city} {request.days} 天",
        "",
        f"- 出发：{request.origin}",
        f"- 日期：{request.start_date} 起 {request.days} 天",
        f"- 预算：{request.budget:.0f} 元",
        f"- 预估：{plan.total_cost:.0f} 元",
        f"- 节奏：{request.pace}",
        "",
        f"> {plan.summary}",
        "",
        "## 预算",
        "",
        "| 项目 | 金额 |",
        "|---|---:|",
    ]
    for item in plan.budget_items:
        lines.append(f"| {item.label} | {item.amount:.0f} 元 |")
    lines.extend(["", "## 每日行程", ""])
    for day in plan.days:
        lines.append(f"### Day {day.day} · {day.date} · {day.theme}")
        for item in day.items:
            lines.append(
                f"- **{item.start}-{item.end}** {item.poi_name}"
                f"（交通 {item.travel_minutes} 分钟，门票 {item.ticket:.0f} 元）"
            )
            if item.note:
                lines.append(f"  - {item.note}")
        lines.append("")
    if plan.issues:
        lines.extend(["## 校验提示", ""])
        for issue in plan.issues:
            lines.append(f"- `{issue.severity}` {issue.message}")
    if plan.citations:
        lines.extend(["", "## 攻略引用", ""])
        for citation in plan.citations:
            lines.append(
                f"- 《{citation['doc_name']}》 · {citation['heading']}：{citation['snippet']}"
            )
    return "\n".join(lines)


def to_ics(plan: TripPlan) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Trip Planner Agent//CN",
        "CALSCALE:GREGORIAN",
    ]
    for day in plan.days:
        for item in day.items:
            start = datetime.fromisoformat(f"{day.date}T{item.start}:00")
            end = datetime.fromisoformat(f"{day.date}T{item.end}:00")
            if end <= start:
                end = start + timedelta(hours=1)
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{plan.trip_id}-{day.day}-{item.seq}@trip-planner",
                    f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}",
                    f"DTSTART;TZID=Asia/Shanghai:{start.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND;TZID=Asia/Shanghai:{end.strftime('%Y%m%dT%H%M%S')}",
                    f"SUMMARY:{item.poi_name}",
                    f"DESCRIPTION:{item.note}",
                    "END:VEVENT",
                ]
            )
    lines.append("END:VCALENDAR")
    return "\n".join(lines)


def write_exports(plan: TripPlan, directory: str | Path) -> dict[str, str]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{plan.trip_id}.md"
    ics = out / f"{plan.trip_id}.ics"
    md.write_text(to_markdown(plan), encoding="utf-8")
    ics.write_text(to_ics(plan), encoding="utf-8")
    return {"markdown": str(md), "ics": str(ics)}
