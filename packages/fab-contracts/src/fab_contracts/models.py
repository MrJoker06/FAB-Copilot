from __future__ import annotations

from datetime import date
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IdentityContext(ContractModel):
    user_id: str = Field(min_length=1, max_length=128)
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    site_ids: tuple[str, ...] = ()
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class DateRange(ContractModel):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def validate_range(self) -> DateRange:
        if self.start and self.end:
            if self.start > self.end:
                raise ValueError("start must not be later than end")
            if (self.end - self.start).days > 730:
                raise ValueError("date range must not exceed 730 days")
        return self


class ReportRequest(DateRange):
    process_step: str | None = Field(default=None, max_length=32)
    equipment_id: str | None = Field(default=None, max_length=64)
    product: str | None = Field(default=None, max_length=64)
    signal_name: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=100, ge=1, le=100)

    @field_validator("process_step")
    @classmethod
    def normalize_process_step(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class AdHocQueryRequest(ContractModel):
    sql: str = Field(min_length=6, max_length=20_000)


class QueryResult(ContractModel):
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int = Field(ge=0, le=100)
    truncated: bool = False
    duration_ms: float = Field(ge=0)


class ToolResult(ContractModel):
    tool: str
    data: Any
    row_count: int | None = Field(default=None, ge=0)
    truncated: bool = False
    request_id: str


class ApiEnvelope(ContractModel, Generic[T]):
    data: T
    request_id: str


class ProblemDetail(ContractModel):
    type: str = "about:blank"
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str | None = None
    error_code: str
    request_id: str
    retryable: bool = False
    category: Literal["client", "dependency", "server"] = "client"
