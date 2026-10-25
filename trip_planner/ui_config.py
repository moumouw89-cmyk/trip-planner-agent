from __future__ import annotations

from pathlib import Path

from .config import AI_PRESETS, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, ROOT


def default_llm_config() -> dict:
    base_url = (OPENAI_BASE_URL or "").rstrip("/")
    provider = "custom"
    for key, preset in AI_PRESETS.items():
        if key != "custom" and (preset["base_url"].rstrip("/") == base_url):
            provider = key
            break
    preset = AI_PRESETS[provider]
    model = OPENAI_MODEL or (preset["models"][0] if preset["models"] else "")
    return {
        "provider": provider,
        "label": preset["label"],
        "base_url": OPENAI_BASE_URL,
        "model": model,
        "api_key": OPENAI_API_KEY,
    }


def get_llm_config(st) -> dict:
    return st.session_state.get("llm_config") or default_llm_config()


def persist_llm_config(config: dict, path: str | Path | None = None) -> None:
    """Persist the selected OpenAI-compatible endpoint to the ignored .env."""
    env_path = Path(path or (ROOT / ".env"))
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    values = {
        "OPENAI_API_KEY": config.get("api_key", ""),
        "OPENAI_BASE_URL": config.get("base_url", ""),
        "OPENAI_MODEL": config.get("model", ""),
    }
    for name, value in values.items():
        found = False
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{name}="):
                lines[index] = f"{name}={value}"
                found = True
        if not found:
            lines.append(f"{name}={value}")
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
