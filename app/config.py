from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PROJECT_DIR.parent.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


_load_env(WORKSPACE_DIR / ".env")
_load_env(PROJECT_DIR / ".env")

ALLOWED_MODELS = ("deepseekv4-flash", "deepseekv4-pro")
MODEL_API_NAMES = {
    "deepseekv4-flash": "deepseek-v4-flash",
    "deepseekv4-pro": "deepseek-v4-pro",
}
_runtime_lock = threading.Lock()
_runtime_api_key: str | None = None
_configured_model = os.getenv("DEEPSEEK_MODEL", "")
_configured_alias = next((alias for alias, api_name in MODEL_API_NAMES.items() if api_name == _configured_model), _configured_model)
_runtime_model = _configured_alias if _configured_alias in ALLOWED_MODELS else ALLOWED_MODELS[0]


@dataclass(frozen=True)
class Settings:
    database_path: Path
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    api_timeout_seconds: float


def get_settings() -> Settings:
    database_value = os.getenv("FAB_DATABASE_PATH", "data/fab_history.db")
    database_path = Path(database_value)
    if not database_path.is_absolute():
        database_path = PROJECT_DIR / database_path
    with _runtime_lock:
        api_key = _runtime_api_key if _runtime_api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        model = MODEL_API_NAMES[_runtime_model]
    return Settings(
        database_path=database_path,
        deepseek_api_key=api_key,
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=model,
        api_timeout_seconds=float(os.getenv("API_TIMEOUT_MS", "60000")) / 1000,
    )


def update_model_config(model: str, api_key: str | None = None) -> dict:
    if model not in ALLOWED_MODELS:
        raise ValueError(f"不支持的模型: {model}")
    cleaned_key = api_key.strip() if api_key is not None else None
    if cleaned_key is not None and len(cleaned_key) < 8:
        raise ValueError("API Key 长度不能少于 8 个字符")
    global _runtime_api_key, _runtime_model
    with _runtime_lock:
        _runtime_model = model
        if cleaned_key:
            _runtime_api_key = cleaned_key
    return public_model_config()


def public_model_config() -> dict:
    with _runtime_lock:
        key = _runtime_api_key if _runtime_api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        source = "runtime" if _runtime_api_key is not None else ("environment" if key else "none")
        model = _runtime_model
    masked = f"••••••••{key[-4:]}" if len(key) >= 4 else ""
    return {
        "model": model,
        "provider_model": MODEL_API_NAMES[model],
        "allowed_models": list(ALLOWED_MODELS),
        "api_key_configured": bool(key),
        "api_key_masked": masked,
        "api_key_source": source,
        "persistence": "process_memory",
    }
