from __future__ import annotations

import json
import os
import re
import time

import httpx

from .config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL


class LLMError(RuntimeError):
    pass


class OpenAICompatibleLLM:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = (api_key or OPENAI_API_KEY or "").strip()
        self.base_url = (base_url or OPENAI_BASE_URL).rstrip("/")
        self.model = model or OPENAI_MODEL
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, json_mode: bool = False) -> str:
        if not self.api_key:
            raise LLMError("未配置 API Key。")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        }
        if "reasoner" in self.model:
            # DeepSeek R1 rejects sampling parameters such as temperature.
            payload.pop("temperature", None)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        last_error = ""
        for attempt in range(3):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"].get("content") or ""
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )
                return content
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}"
                if exc.response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise LLMError(f"LLM 请求失败：{exc}") from exc
            except httpx.TimeoutException as exc:
                last_error = "timeout"
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise LLMError("LLM 请求超时。") from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"LLM 请求失败：{exc}") from exc
            except (KeyError, IndexError, ValueError) as exc:
                raise LLMError("LLM 响应格式异常。") from exc
        raise LLMError(f"LLM 请求失败：{last_error or '未知错误'}")

    def parse_request(self, text: str, city_names: list[str], today: str) -> dict | None:
        prompt = f"""
把用户的旅行需求解析成 JSON，只输出 JSON，不要 Markdown。
今天是 {today}。城市可以是任意中国城市；下面是内置示例，用户提到其他城市时也照常返回：{city_names}。
字段：
- city: 城市中文名或 id
- place: 用户提到的具体景点/山/古镇/寺庙/地标；没有就空字符串。不要把它猜成北京
- start_date: YYYY-MM-DD
- days: 整数
- budget: 数字（人民币）
- origin: 出发城市
- preferences: 偏好描述
- pace: relaxed | balanced | packed
- must_visit: 字符串数组

用户需求：{text}
""".strip()
        raw = self.complete(
            "你是一个旅行需求解析器，只输出合法 JSON，不要编造用户没说的日期。",
            prompt,
            json_mode=True,
        )
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def narrate(self, plan_summary: str, days_json: str) -> str:
        prompt = f"""
你是行程管家。用中文写一段 120 字以内的行程说明，先给整体节奏，再点出 2-3 个亮点。
不要编造未提供的价格或营业时间，不要使用“绝对”“保证”等词。
行程摘要：{plan_summary}
每日安排：{days_json}
""".strip()
        return self.complete(
            "你只根据给定行程写说明，不增加未提供的景点和价格。",
            prompt,
        )
