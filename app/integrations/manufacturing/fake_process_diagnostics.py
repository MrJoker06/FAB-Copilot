"""Explicit fixture-backed adapter for process diagnostics."""

from __future__ import annotations

from collections.abc import Mapping

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.process_diagnostics.contracts import (
    DiagnosticsDataError,
    DiagnosticsQuery,
    DiagnosticsSnapshot,
    diagnostics_scope,
)


class FakeProcessDiagnosticsAdapter:
    """Return only an explicitly supplied snapshot for an exact query."""

    def __init__(
        self,
        demo_tenant_id: str,
        snapshots: Mapping[DiagnosticsQuery, tuple[dict[str, object], ...]],
    ) -> None:
        self.demo_tenant_id = demo_tenant_id
        self.snapshots = {
            query: tuple(dict(row) for row in rows) for query, rows in snapshots.items()
        }
        self.calls: list[DiagnosticsQuery] = []

    def fetch(
        self, query: DiagnosticsQuery, principal: ToolPrincipal
    ) -> DiagnosticsSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise DiagnosticsDataError("process-diagnostics source is unavailable")
        self.calls.append(query)
        try:
            rows = self.snapshots[query]
        except KeyError:
            raise DiagnosticsDataError(
                "no process-diagnostics fixture for requested scope"
            ) from None
        return DiagnosticsSnapshot(
            query,
            tuple(dict(row) for row in rows),
            ToolSource(
                "fake:process-diagnostics",
                "fake-process-diagnostics",
                ToolSourceKind.FAKE,
                diagnostics_scope(query, principal),
            ),
        )
