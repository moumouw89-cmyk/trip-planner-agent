from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .llm import LLMError, OpenAICompatibleLLM
from .models import TripPlan


@dataclass
class JudgeResult:
    scores: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    provider: str = "heuristic"

    @property
    def average(self) -> float:
        return sum(self.scores.values()) / len(self.scores) if self.scores else 0.0

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "average": round(self.average, 2),
            "reasons": self.reasons,
            "provider": self.provider,
        }


class ItineraryJudge:
    """LLM judge for offline evaluation; runtime decisions use the validator."""

    def __init__(self, llm: OpenAICompatibleLLM | None = None):
        self.llm = llm

    def judge(self, plan: TripPlan) -> JudgeResult:
        if self.llm is not None and self.llm.configured:
            try:
                prompt = f"""
你是旅行行程评审。按 1-5 分评价以下行程，只输出 JSON：
{{"feasibility":1-5,"pacing":1-5,"preference_fit":1-5,"budget":1-5,"explanation":1-5,"reasons":["..."]}}
不要因为“看起来高级”给高分；只依据给定行程和校验问题。
行程摘要：{plan.summary}
校验问题：{[i.to_dict() for i in plan.issues]}
每日安排：{json.dumps([d.to_dict() for d in plan.days], ensure_ascii=False)}
""".strip()
                raw = self.llm.complete(
                    "你是严格但公正的旅行行程评审，只输出 JSON。",
                    prompt,
                    json_mode=True,
                )
                match = re.search(r"\{.*\}", raw, flags=re.S)
                data = json.loads(match.group(0)) if match else {}
                keys = ["feasibility", "pacing", "preference_fit", "budget", "explanation"]
                scores = {key: float(data.get(key, 3)) for key in keys}
                return JudgeResult(
                    scores=scores,
                    reasons=[str(x) for x in data.get("reasons", [])][:5],
                    provider="llm",
                )
            except (LLMError, ValueError, TypeError, json.JSONDecodeError):
                pass
        return self._heuristic(plan)

    def _heuristic(self, plan: TripPlan) -> JudgeResult:
        high = sum(1 for issue in plan.issues if issue.severity == "high")
        medium = sum(1 for issue in plan.issues if issue.severity == "medium")
        feasibility = max(1.0, 5.0 - high * 1.5 - medium * 0.5)
        pacing = max(1.0, 5.0 - max(0, len(plan.days) - 1) * 0.1)
        budget_ratio = plan.total_cost / plan.request.budget if plan.request.budget else 1
        budget = 5.0 if budget_ratio <= 0.9 else 3.5 if budget_ratio <= 1 else 2.0
        preference = 4.0 if plan.request.preferences else 3.0
        explanation = 4.0 if plan.summary else 2.0
        return JudgeResult(
            scores={
                "feasibility": round(feasibility, 2),
                "pacing": round(pacing, 2),
                "preference_fit": preference,
                "budget": budget,
                "explanation": explanation,
            },
            reasons=["规则评分：基于校验问题、预算比例和偏好关键词。"],
            provider="heuristic",
        )
