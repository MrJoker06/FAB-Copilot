"""Exact fixture adapter for production reports."""

from __future__ import annotations

from collections.abc import Mapping

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.production_reports.contracts import (
    ProductionReportDataError,
    ProductionReportQuery,
    ProductionReportSnapshot,
    production_report_scope,
)


class FakeProductionReportsAdapter:
    def __init__(
        self,
        demo_tenant_id: str,
        snapshots: Mapping[
            ProductionReportQuery, dict[str, object] | tuple[dict[str, object], ...]
        ],
    ) -> None:
        self.demo_tenant_id = demo_tenant_id
        self.snapshots = {
            query: dict(data)
            if isinstance(data, dict)
            else tuple(dict(row) for row in data)
            for query, data in snapshots.items()
        }
        self.calls: list[ProductionReportQuery] = []

    def fetch(
        self, query: ProductionReportQuery, principal: ToolPrincipal
    ) -> ProductionReportSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise ProductionReportDataError("production-report source is unavailable")
        self.calls.append(query)
        try:
            data = self.snapshots[query]
        except KeyError:
            raise ProductionReportDataError(
                "no production-report fixture for requested scope"
            ) from None
        copy = (
            dict(data) if isinstance(data, dict) else tuple(dict(row) for row in data)
        )
        return ProductionReportSnapshot(
            query,
            copy,
            ToolSource(
                "fake:production-reports",
                "fake-production-reports",
                ToolSourceKind.FAKE,
                production_report_scope(query, principal),
            ),
        )
