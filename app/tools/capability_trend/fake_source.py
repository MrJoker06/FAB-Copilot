"""Fixture-backed source for weekly capability trends."""

from __future__ import annotations

from collections.abc import Mapping

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from .contracts import (
    CapabilityTrendDataError,
    CapabilityTrendQuery,
    CapabilityTrendSnapshot,
    capability_trend_scope,
)


class FakeCapabilityTrendSource:
    """Return only an explicitly supplied snapshot for an exact query."""

    def __init__(
        self,
        demo_tenant_id: str,
        snapshots: Mapping[CapabilityTrendQuery, tuple[dict[str, object], ...]],
    ) -> None:
        self.demo_tenant_id = demo_tenant_id
        self.snapshots = {
            query: tuple(dict(row) for row in rows) for query, rows in snapshots.items()
        }
        self.calls: list[CapabilityTrendQuery] = []

    def fetch(
        self, query: CapabilityTrendQuery, principal: ToolPrincipal
    ) -> CapabilityTrendSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise CapabilityTrendDataError("capability-trend source is unavailable")
        self.calls.append(query)
        try:
            rows = self.snapshots[query]
        except KeyError:
            raise CapabilityTrendDataError(
                "no capability-trend fixture for requested scope"
            ) from None
        return CapabilityTrendSnapshot(
            query,
            tuple(dict(row) for row in rows),
            ToolSource(
                "fake:capability-trend",
                "fake-capability-trend",
                ToolSourceKind.FAKE,
                capability_trend_scope(query, principal),
            ),
        )
