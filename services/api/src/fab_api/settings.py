from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FAB_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_dir: Path = Field(default_factory=lambda: Path.cwd())
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    mcp_url: str = "http://127.0.0.1:8770/mcp"
    mcp_health_url: str = "http://127.0.0.1:8770/health/ready"
    mcp_service_token: str = "dev-mcp-service-token"
    mcp_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    dev_user_id: str = "local-user"
    dev_api_token: str = ""
    admin_api_token: str = ""
    web_dist: Path = Path("web/dist")
    application_database_dir: Path = Path("data/departments")
    audit_log_dir: Path = Path("logs")
    model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FAB_API_MODEL_API_KEY", "DEEPSEEK_API_KEY"),
    )
    model_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("FAB_API_MODEL_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    model_name: str = Field(
        default="deepseek-v4-flash",
        validation_alias=AliasChoices("FAB_API_MODEL_NAME", "DEEPSEEK_MODEL"),
    )
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=180)
    model_max_tool_rounds: int = Field(default=6, ge=1, le=10)

    @field_validator("model_name")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        return {
            "deepseekv4-flash": "deepseek-v4-flash",
            "deepseekv4-pro": "deepseek-v4-pro",
        }.get(value, value)

    def resolved_web_dist(self) -> Path:
        return self.web_dist if self.web_dist.is_absolute() else (self.project_dir / self.web_dist).resolve()

    def resolved_application_database_dir(self) -> Path:
        path = self.application_database_dir
        return path if path.is_absolute() else (self.project_dir / path).resolve()

    def resolved_audit_log_dir(self) -> Path:
        path = self.audit_log_dir
        return path if path.is_absolute() else (self.project_dir / path).resolve()
