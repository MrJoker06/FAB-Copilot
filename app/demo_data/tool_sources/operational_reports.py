"""Exact fixture adapter for fixed operational manufacturing reports."""

from __future__ import annotations

from collections.abc import Mapping

from app.agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from app.tools.operational_reports.contracts import (
    OperationalReportDataError,
    OperationalReportQuery,
    OperationalReportSnapshot,
    operational_report_scope,
)


class FakeOperationalReportsAdapter:
    """Return copied fixtures only for an exact operational report query."""

    def __init__(
        self,
        demo_tenant_id: str,
        snapshots: Mapping[OperationalReportQuery, tuple[dict[str, object], ...]],
    ) -> None:
        self.demo_tenant_id = demo_tenant_id
        self.snapshots = {
            query: tuple(dict(row) for row in rows) for query, rows in snapshots.items()
        }
        self.calls: list[OperationalReportQuery] = []

    def fetch(
        self, query: OperationalReportQuery, principal: ToolPrincipal
    ) -> OperationalReportSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise OperationalReportDataError("operational-report source is unavailable")
        self.calls.append(query)
        try:
            rows = self.snapshots[query]
        except KeyError:
            raise OperationalReportDataError(
                "no operational-report fixture for requested scope"
            ) from None
        return OperationalReportSnapshot(
            query,
            tuple(dict(row) for row in rows),
            ToolSource(
                "fake:operational-reports",
                "fake-operational-reports",
                ToolSourceKind.FAKE,
                operational_report_scope(query, principal),
            ),
        )
