"""Exact in-memory fixtures for the native knowledge-search tool."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSourceKind
from ...knowledge.search_tool.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchQuery,
    KnowledgeSearchSnapshot,
    knowledge_scope,
)


class FakeKnowledgeSearchAdapter:
    """Return a copied fixture for exactly one authorized search query."""

    def __init__(
        self,
        demo_tenant_id: str,
        demo_user_id: str,
        snapshots: Mapping[KnowledgeSearchQuery, KnowledgeSearchSnapshot],
    ) -> None:
        for name, value in (
            ("demo_tenant_id", demo_tenant_id),
            ("demo_user_id", demo_user_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(snapshots, Mapping):
            raise TypeError("snapshots must be a mapping")
        copied: dict[KnowledgeSearchQuery, KnowledgeSearchSnapshot] = {}
        for query, snapshot in snapshots.items():
            if not isinstance(query, KnowledgeSearchQuery) or not isinstance(
                snapshot, KnowledgeSearchSnapshot
            ):
                raise TypeError("snapshots must map queries to knowledge snapshots")
            if snapshot.query != query or any(
                source.source_kind is not ToolSourceKind.FAKE
                for source in snapshot.sources
            ):
                raise ValueError(
                    "fake knowledge fixtures must have fake source metadata"
                )
            copied[query] = deepcopy(snapshot)
        self.demo_tenant_id = demo_tenant_id
        self.demo_user_id = demo_user_id
        self.snapshots = copied
        self.calls: list[KnowledgeSearchQuery] = []

    def fetch(
        self, query: KnowledgeSearchQuery, principal: ToolPrincipal
    ) -> KnowledgeSearchSnapshot:
        if (
            principal.tenant_id != self.demo_tenant_id
            or principal.user_id != self.demo_user_id
        ):
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        self.calls.append(query)
        try:
            snapshot = self.snapshots[query]
        except KeyError:
            raise KnowledgeSearchDataError(
                "no knowledge-search fixture for requested scope"
            ) from None
        if snapshot.sources and any(
            source.scope != knowledge_scope(principal) for source in snapshot.sources
        ):
            raise KnowledgeSearchDataError("knowledge-search fixture scope is invalid")
        return deepcopy(snapshot)
