from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
TRIPS_DIR = DATA_DIR / "trips"
GUIDES_DIR = ROOT / "guides"
GUIDES_DB = DATA_DIR / "guides.db"
CITIES_PATH = DATA_DIR / "cities.json"
REPORTS_DIR = ROOT / "reports"

PACE_MAX_ACTIVITIES = {"relaxed": 2, "balanced": 3, "packed": 4}
PACE_LABELS = {"relaxed": "轻松", "balanced": "适中", "packed": "紧凑"}

AI_PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    },
    "qwen": {
        "label": "通义千问（DashScope）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
    },
    "kimi": {
        "label": "Kimi（Moonshot）",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "kimi-latest"],
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-air", "glm-4-plus"],
    },
    "siliconflow": {
        "label": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": [
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct",
        ],
    },
    "custom": {
        "label": "自定义（兼容 OpenAI）",
        "base_url": "",
        "models": [],
    },
}
MAP_LABELS = {"amap": "高德", "baidu": "百度", "mock": "模拟（无密钥）"}
HOTEL_LABELS = {
    "auto": "本地精选 + 高德实时",
    "local": "本地演示",
    "amap": "仅高德实时",
}

AMAP_API_KEY = os.getenv("AMAP_API_KEY", "").strip()
BAIDU_AK = os.getenv("BAIDU_AK", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", OPENAI_MODEL)

# Amap weather city adcodes (demo subset).
AMAP_CITY_CODES = {
    "chengdu": "510100",
    "xian": "610100",
    "hangzhou": "330100",
    "xiamen": "350200",
    "shenzhen": "440300",
    "kunming": "530100",
}
