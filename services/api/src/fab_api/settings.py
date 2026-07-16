from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAB_API_", env_file=".env", extra="ignore")

    project_dir: Path = Field(default_factory=lambda: Path.cwd())
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    mcp_url: str = "http://127.0.0.1:8770/mcp"
    mcp_health_url: str = "http://127.0.0.1:8770/health/ready"
    mcp_service_token: str = "dev-mcp-service-token"
    mcp_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    dev_user_id: str = "local-user"
    dev_api_token: str = ""
    web_dist: Path = Path("web/dist")
    application_database_dir: Path = Path("data/departments")
    audit_log_dir: Path = Path("logs")

    def resolved_web_dist(self) -> Path:
        return self.web_dist if self.web_dist.is_absolute() else (self.project_dir / self.web_dist).resolve()

    def resolved_application_database_dir(self) -> Path:
        path = self.application_database_dir
        return path if path.is_absolute() else (self.project_dir / path).resolve()

    def resolved_audit_log_dir(self) -> Path:
        path = self.audit_log_dir
        return path if path.is_absolute() else (self.project_dir / path).resolve()
