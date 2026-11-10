"""Exact fixture adapter for the fixed named manufacturing queries."""

from __future__ import annotations

from collections.abc import Mapping

from app.agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from app.tools.named_queries.contracts import (
    NamedQuery,
    NamedQueryDataError,
    NamedQuerySnapshot,
    named_query_scope,
)


class FakeNamedQueryAdapter:
    """Return copied fixtures only for an exact query and the demo tenant."""

    def __init__(
        self,
        demo_tenant_id: str,
        fixtures: Mapping[NamedQuery, tuple[dict[str, object], ...]],
    ) -> None:
        self.demo_tenant_id = demo_tenant_id
        self.fixtures = {
            query: tuple(dict(row) for row in rows) for query, rows in fixtures.items()
        }
        self.calls: list[NamedQuery] = []

    def fetch(self, query: NamedQuery, principal: ToolPrincipal) -> NamedQuerySnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise NamedQueryDataError("named-query source is unavailable")
        self.calls.append(query)
        try:
            rows = self.fixtures[query]
        except KeyError:
            raise NamedQueryDataError(
                "no named-query fixture for requested scope"
            ) from None
        return NamedQuerySnapshot(
            query,
            tuple(dict(row) for row in rows),
            ToolSource(
                f"fake:named-query/{query.kind}",
                "fake-named-query",
                ToolSourceKind.FAKE,
                named_query_scope(query, principal),
            ),
        )
