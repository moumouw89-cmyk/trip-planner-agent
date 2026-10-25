"""Run a small constraint-satisfaction eval for the deterministic planner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trip_planner.agent import TripAgent  # noqa: E402
from trip_planner.judge import ItineraryJudge  # noqa: E402
from trip_planner.planner import TripPlanner  # noqa: E402
from trip_planner.tripdb import TripRepository  # noqa: E402


def main() -> None:
    requests = json.loads((ROOT / "evals" / "requests.json").read_text(encoding="utf-8"))
    planner = TripPlanner()
    agent = TripAgent(planner, TripRepository(ROOT / "data" / "eval_trips"))
    judge = ItineraryJudge()
    rows = []
    for item in requests:
        plan = agent.plan_from_text(item["text"])
        high = [issue for issue in plan.issues if issue.severity == "high"]
        rows.append(
            {
                "request": item["text"],
                "trip_id": plan.trip_id,
                "days": len(plan.days),
                "total_cost": plan.total_cost,
                "budget": plan.request.budget,
                "high_issues": [issue.message for issue in high],
                "valid": not high,
                "judge": judge.judge(plan).to_dict(),
            }
        )
    report = {
        "total": len(rows),
        "valid": sum(1 for row in rows if row["valid"]),
        "pass_rate": round(sum(1 for row in rows if row["valid"]) / len(rows), 4),
        "avg_judge": round(sum(row["judge"]["average"] for row in rows) / len(rows), 2),
        "rows": rows,
    }
    out = ROOT / "reports" / "eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
