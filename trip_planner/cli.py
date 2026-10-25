from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta

from .agent import TripAgent
from .config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from .llm import OpenAICompatibleLLM
from .models import TripRequest
from .planner import TripPlanner
from .tripdb import TripRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="行程管家 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="生成一个行程")
    plan_parser.add_argument("--text", default="", help="自然语言需求")
    plan_parser.add_argument("--city", default="成都")
    plan_parser.add_argument("--start", default=(date.today() + timedelta(days=7)).isoformat())
    plan_parser.add_argument("--days", type=int, default=3)
    plan_parser.add_argument("--budget", type=float, default=5000)
    plan_parser.add_argument("--origin", default="深圳")
    plan_parser.add_argument("--preferences", default="")
    plan_parser.add_argument("--pace", choices=["relaxed", "balanced", "packed"], default="balanced")
    plan_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "plan":
        planner = TripPlanner()
        llm = (
            OpenAICompatibleLLM(
                api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL,
                model=OPENAI_MODEL,
            )
            if OPENAI_API_KEY
            else None
        )
        agent = TripAgent(planner, TripRepository(), llm=llm)
        if args.text:
            plan = agent.plan_from_text(args.text)
        else:
            plan = agent.plan(
                TripRequest(
                    city=args.city,
                    start_date=args.start,
                    days=args.days,
                    budget=args.budget,
                    origin=args.origin,
                    preferences=args.preferences,
                    pace=args.pace,
                )
            )
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(plan.summary)
            print(f"\nDB: {plan.db_path}")
            print(f"预算: {plan.total_cost:.0f} / {plan.request.budget:.0f} 元")
            for day in plan.days:
                print(f"\nDay {day.day} {day.date} · {day.theme}")
                for item in day.items:
                    print(
                        f"  {item.start}-{item.end} {item.poi_name} "
                        f"(交通 {item.travel_minutes}min, ¥{item.ticket:.0f})"
                    )
            if plan.issues:
                print("\n校验问题:")
                for issue in plan.issues:
                    print(f"  [{issue.severity}] {issue.message}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
