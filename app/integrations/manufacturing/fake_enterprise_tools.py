"""Exact fixture adapter for the enterprise-data tool migration."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.enterprise_tools.contracts import (
    EnterpriseDataError,
    EnterpriseQuery,
    EnterpriseSnapshot,
    enterprise_scope,
)


class FakeEnterpriseToolsAdapter:
    """Return copied fixtures only for an exact, supplied enterprise query."""

    def __init__(
        self,
        demo_tenant_id: str,
        snapshots: Mapping[EnterpriseQuery, dict[str, object]],
    ) -> None:
        self.demo_tenant_id = demo_tenant_id
        self.snapshots = {query: deepcopy(data) for query, data in snapshots.items()}
        self.calls: list[EnterpriseQuery] = []

    def fetch(
        self, query: EnterpriseQuery, principal: ToolPrincipal
    ) -> EnterpriseSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise EnterpriseDataError("enterprise-tools source is unavailable")
        self.calls.append(query)
        try:
            data = self.snapshots[query]
        except KeyError:
            raise EnterpriseDataError(
                "no enterprise-tools fixture for requested scope"
            ) from None
        return EnterpriseSnapshot(
            query,
            deepcopy(data),
            ToolSource(
                f"fake:enterprise-tools/{query.kind}",
                "fake-enterprise-tools",
                ToolSourceKind.FAKE,
                enterprise_scope(query, principal),
            ),
        )
