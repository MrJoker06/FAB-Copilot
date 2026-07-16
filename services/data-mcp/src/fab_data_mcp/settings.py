from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataMCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAB_MCP_", env_file=".env", extra="ignore")

    project_dir: Path = Field(default_factory=lambda: Path.cwd())
    database_dir: Path = Path("data/departments")
    manufacturing_database_path: Path | None = None
    equipment_database_path: Path | None = None
    quality_database_path: Path | None = None
    service_token: str = "dev-mcp-service-token"
    host: str = "127.0.0.1"
    port: int = Field(default=8770, ge=1, le=65535)
    query_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    max_query_rows: int = Field(default=100, ge=1, le=1000)

    def resolved_database_paths(self) -> dict[str, Path]:
        directory = self._resolve(self.database_dir)
        values = {
            "main": self.manufacturing_database_path or directory / "manufacturing_operations.db",
            "equipment": self.equipment_database_path or directory / "equipment_engineering.db",
            "quality": self.quality_database_path or directory / "yield_quality.db",
        }
        return {name: self._resolve(path) for name, path in values.items()}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else (self.project_dir / path).resolve()
