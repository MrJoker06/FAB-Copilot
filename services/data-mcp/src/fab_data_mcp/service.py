from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from fab_contracts import IdentityContext, ReportRequest, ToolResult
from fab_core import DomainError

from .repository import SQLiteManufacturingRepository
from .settings import DataMCPSettings
from .sql_guard import execute_guarded_query

LOGGER = logging.getLogger("fab_insight.data_mcp")


class DataToolService:
    REPORT_TOOLS = {
        "get_fab_overview",
        "get_yield_trend",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_process_capability",
        "get_defect_pareto",
        "get_recent_excursions",
        "get_sensor_summary",
    }

    def __init__(self, settings: DataMCPSettings) -> None:
        self.settings = settings
        self.repository = SQLiteManufacturingRepository(settings)

    def call(self, tool_name: str, arguments: dict[str, Any], identity: IdentityContext) -> ToolResult:
        started = time.perf_counter()
        data: Any
        audit_fields: dict[str, Any]
        try:
            if tool_name == "get_dashboard":
                request = ReportRequest.model_validate(arguments)
                data = {
                    "overview": self.repository.get_fab_overview(request),
                    "yield_trend": self.repository.get_yield_trend(request),
                    "equipment": self.repository.get_equipment_health(request),
                    "defects": self.repository.get_defect_pareto(request.model_copy(update={"limit": 8})),
                    "excursions": self.repository.get_recent_excursions(
                        request.model_copy(update={"limit": 12})
                    ),
                }
                row_count = sum(len(value) if isinstance(value, list) else 1 for value in data.values())
                truncated = False
                audit_fields = {"aggregate": True}
            elif tool_name == "query_manufacturing_data":
                if not identity.has_scope("analytics:adhoc"):
                    raise DomainError(
                        "MCP_SCOPE_REQUIRED",
                        "ad-hoc manufacturing queries require analytics:adhoc scope",
                        status_code=403,
                    )
                sql = str(arguments.get("sql") or "")
                result, tables = execute_guarded_query(sql, self.settings)
                data = result.model_dump(mode="json")
                row_count = result.row_count
                truncated = result.truncated
                audit_fields = {
                    "sql_fingerprint": hashlib.sha256(sql.encode()).hexdigest()[:16],
                    "tables": tables,
                }
            elif tool_name in self.REPORT_TOOLS:
                request = ReportRequest.model_validate(arguments)
                handler = getattr(self.repository, tool_name)
                data = handler(request)
                row_count = len(data) if isinstance(data, list) else 1
                truncated = False
                audit_fields = {}
            else:
                raise DomainError("TOOL_NOT_FOUND", f"unknown data tool: {tool_name}", status_code=404)
            LOGGER.info(
                "tool=%s request_id=%s user_id=%s rows=%s duration_ms=%.2f %s",
                tool_name,
                identity.request_id,
                identity.user_id,
                row_count,
                (time.perf_counter() - started) * 1000,
                audit_fields,
            )
            return ToolResult(
                tool=tool_name,
                data=data,
                row_count=row_count,
                truncated=truncated,
                request_id=identity.request_id,
            )
        except Exception as exc:
            LOGGER.warning(
                "tool=%s request_id=%s user_id=%s status=error error=%s duration_ms=%.2f",
                tool_name,
                identity.request_id,
                identity.user_id,
                type(exc).__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise
