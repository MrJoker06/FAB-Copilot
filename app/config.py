from __future__ import annotations

import os
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
    return Settings(
        database_path=database_path,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_timeout_seconds=float(os.getenv("API_TIMEOUT_MS", "60000")) / 1000,
    )
