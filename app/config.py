from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PROJECT_DIR.parent.parent
APP_VERSION = "20260801-6"


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


_load_env(Path(os.getenv("FAB_WORKSPACE_ENV_FILE", WORKSPACE_DIR / ".env")))
_load_env(Path(os.getenv("FAB_PROJECT_ENV_FILE", PROJECT_DIR / ".env")))

ALLOWED_MODELS = ("deepseekv4-flash", "deepseekv4-pro")
MODEL_API_NAMES = {
    "deepseekv4-flash": "deepseek-v4-flash",
    "deepseekv4-pro": "deepseek-v4-pro",
}
_configured_model = os.getenv("DEEPSEEK_MODEL", "")
_configured_alias = next((alias for alias, api_name in MODEL_API_NAMES.items() if api_name == _configured_model), _configured_model)
_default_model = _configured_alias if _configured_alias in ALLOWED_MODELS else ALLOWED_MODELS[0]


@dataclass(frozen=True)
class Settings:
    database_path: Path
    manufacturing_database_path: Path
    equipment_database_path: Path
    quality_database_path: Path
    knowledge_database_path: Path
    agent_database_path: Path
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    api_timeout_seconds: float
    model_max_retries: int
    model_retry_base_seconds: float
    personal_knowledge_storage_path: Path
    personal_knowledge_user_id: str
    personal_knowledge_api_token: str
    personal_knowledge_max_upload_bytes: int
    enterprise_mode: bool
    enterprise_data_provider: str
    enterprise_default_tenant_id: str
    enterprise_default_user_id: str
    enterprise_require_identity: bool
    enterprise_mock_seed: int
    enterprise_mock_virtual_lots: int
    enterprise_mock_cursor_secret: str
    admin_api_token: str


def get_settings() -> Settings:
    database_value = os.getenv("FAB_DATABASE_PATH", "data/fab_history.db")
    database_path = Path(database_value)
    if not database_path.is_absolute():
        database_path = PROJECT_DIR / database_path
    database_dir_value = os.getenv("FAB_DATABASE_DIR", "data/departments")
    database_dir = Path(database_dir_value)
    if not database_dir.is_absolute():
        database_dir = PROJECT_DIR / database_dir

    def department_path(variable: str, filename: str) -> Path:
        value = os.getenv(variable)
        path = Path(value) if value else database_dir / filename
        return path if path.is_absolute() else PROJECT_DIR / path
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    model = MODEL_API_NAMES[_default_model]
    personal_storage = Path(os.getenv("FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH", "data/personal_knowledge"))
    if not personal_storage.is_absolute():
        personal_storage = PROJECT_DIR / personal_storage
    return Settings(
        database_path=database_path,
        manufacturing_database_path=department_path("FAB_MANUFACTURING_DATABASE_PATH", "manufacturing_operations.db"),
        equipment_database_path=department_path("FAB_EQUIPMENT_DATABASE_PATH", "equipment_engineering.db"),
        quality_database_path=department_path("FAB_QUALITY_DATABASE_PATH", "yield_quality.db"),
        knowledge_database_path=department_path("FAB_KNOWLEDGE_DATABASE_PATH", "process_knowledge.db"),
        agent_database_path=department_path("FAB_AGENT_DATABASE_PATH", "ai_operations.db"),
        deepseek_api_key=api_key,
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=model,
        api_timeout_seconds=float(os.getenv("API_TIMEOUT_MS", "60000")) / 1000,
        model_max_retries=max(0, min(int(os.getenv("MODEL_MAX_RETRIES", "2")), 4)),
        model_retry_base_seconds=max(0.05, min(float(os.getenv("MODEL_RETRY_BASE_MS", "500")) / 1000, 5.0)),
        personal_knowledge_storage_path=personal_storage,
        personal_knowledge_user_id=os.getenv("FAB_PERSONAL_KNOWLEDGE_USER_ID", "local-user").strip() or "local-user",
        personal_knowledge_api_token=os.getenv("FAB_PERSONAL_KNOWLEDGE_API_TOKEN", "").strip(),
        personal_knowledge_max_upload_bytes=max(
            1024,
            min(int(os.getenv("FAB_PERSONAL_KNOWLEDGE_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))), 500 * 1024 * 1024),
        ),
        enterprise_mode=os.getenv("FAB_ENTERPRISE_MODE", "true").strip().lower() in {"1", "true", "yes", "on"},
        enterprise_data_provider=os.getenv("FAB_DATA_PROVIDER", "synthetic").strip().lower() or "synthetic",
        enterprise_default_tenant_id=os.getenv("FAB_DEFAULT_TENANT_ID", "demo-fab").strip() or "demo-fab",
        enterprise_default_user_id=os.getenv(
            "FAB_DEFAULT_USER_ID",
            os.getenv("FAB_PERSONAL_KNOWLEDGE_USER_ID", "local-user"),
        ).strip() or "local-user",
        enterprise_require_identity=os.getenv("FAB_REQUIRE_IDENTITY", "false").strip().lower() in {"1", "true", "yes", "on"},
        enterprise_mock_seed=int(os.getenv("FAB_MOCK_SEED", "20260717")),
        enterprise_mock_virtual_lots=max(100_000, int(os.getenv("FAB_MOCK_VIRTUAL_LOTS", "25000000"))),
        enterprise_mock_cursor_secret=os.getenv("FAB_MOCK_CURSOR_SECRET", "fab-insight-local-demo-secret").strip()
        or "fab-insight-local-demo-secret",
        admin_api_token=os.getenv("FAB_ADMIN_API_TOKEN", "").strip(),
    )
