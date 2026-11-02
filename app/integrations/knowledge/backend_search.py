"""Explicit adapter for governed factory and private knowledge searches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...knowledge.search_contracts import (
    FactorySearchBackend,
    validate_factory_candidates,
)
from ...knowledge.search_tool.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchQuery,
    KnowledgeSearchSnapshot,
    KnowledgeSearchTimeoutError,
    PersonalKnowledgeSearchPort,
    PersonalSearchBatch,
    knowledge_owner_id,
    knowledge_scope,
    prepare_search,
)


def _non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_aliases(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise KnowledgeSearchDataError("knowledge-search source is unavailable")
    aliases: dict[str, tuple[str, ...]] = {}
    for name, entries in value.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or isinstance(entries, (str, bytes))
            or not isinstance(entries, Sequence)
        ):
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        copied = tuple(entries)
        if not copied or any(
            not isinstance(item, str) or not item.strip() for item in copied
        ):
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        aliases[name] = copied
    return aliases


def _validate_personal_rows(
    value: object, *, owner_user_id: str, tenant_id: str
) -> tuple[dict[str, object], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KnowledgeSearchDataError("knowledge-search source is unavailable")
    rows: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        copied = dict(row)
        if copied.get("source_type") != "personal":
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        reference_id = copied.get("reference_id")
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        for key in ("owner_user_id", "owner_id", "knowledge_owner_id"):
            if key in copied and copied[key] != owner_user_id:
                raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        for key in ("tenant_id", "tenant"):
            if key in copied and copied[key] != tenant_id:
                raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        rows.append(copied)
    return tuple(rows)


class BackendKnowledgeSearchAdapter:
    """Compose injected governed sources without global backend selection or fallback."""

    def __init__(
        self,
        factory: FactorySearchBackend,
        personal: PersonalKnowledgeSearchPort | None,
        *,
        demo_tenant_id: str,
        default_tenant_id: str,
        source_kind: ToolSourceKind = ToolSourceKind.FAKE,
        personal_source_kind: ToolSourceKind | None = None,
        source_ref: str = "backend:knowledge-search",
        adapter_id: str = "knowledge-backend",
    ) -> None:
        self.demo_tenant_id = _non_empty_string(demo_tenant_id, "demo_tenant_id")
        self.default_tenant_id = _non_empty_string(
            default_tenant_id, "default_tenant_id"
        )
        self.source_ref = _non_empty_string(source_ref, "source_ref")
        self.adapter_id = _non_empty_string(adapter_id, "adapter_id")
        if not isinstance(source_kind, ToolSourceKind):
            raise TypeError("source_kind must be a ToolSourceKind")
        if not all(
            callable(getattr(factory, method, None))
            for method in ("defect_aliases", "search")
        ):
            raise ValueError("factory backend must implement defect_aliases and search")
        if personal is not None and not callable(getattr(personal, "search", None)):
            raise ValueError("personal backend must implement search")
        if personal_source_kind is not None and not isinstance(
            personal_source_kind, ToolSourceKind
        ):
            raise TypeError("personal_source_kind must be a ToolSourceKind")
        self.factory = factory
        self.personal = personal
        self.source_kind = source_kind
        self.personal_source_kind = personal_source_kind or source_kind

    def _factory_source(self, principal: ToolPrincipal) -> ToolSource:
        return ToolSource(
            f"{self.source_ref}/factory",
            self.adapter_id,
            self.source_kind,
            knowledge_scope(principal),
        )

    def _personal_source(self, principal: ToolPrincipal) -> ToolSource:
        return ToolSource(
            f"{self.source_ref}/personal",
            self.adapter_id,
            self.personal_source_kind,
            knowledge_scope(principal),
        )

    def fetch(
        self, query: KnowledgeSearchQuery, principal: ToolPrincipal
    ) -> KnowledgeSearchSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        if "personal" in query.source_types and self.personal is None:
            raise KnowledgeSearchDataError("knowledge-search source is unavailable")
        try:
            aliases = _validate_aliases(self.factory.defect_aliases(principal))
            _, request, personal_query = prepare_search(query, aliases)
            factory_rows = validate_factory_candidates(
                self.factory.search(principal, request)
            )
            if any(
                row["source_type"] not in request.source_types for row in factory_rows
            ):
                raise KnowledgeSearchDataError("knowledge-search source is unavailable")
            owner: str | None = None
            personal_rows: tuple[dict[str, object], ...] = ()
            sources = [self._factory_source(principal)]
            if "personal" in query.source_types:
                owner = knowledge_owner_id(principal, self.default_tenant_id)
                batch = self.personal.search(
                    principal, owner, personal_query, query.candidate_limit
                )
                if not isinstance(batch, PersonalSearchBatch):
                    raise KnowledgeSearchDataError(
                        "knowledge-search source is unavailable"
                    )
                if batch.owner_user_id != owner:
                    raise KnowledgeSearchDataError(
                        "knowledge-search source is unavailable"
                    )
                personal_rows = _validate_personal_rows(
                    batch.rows, owner_user_id=owner, tenant_id=principal.tenant_id
                )
                sources.append(self._personal_source(principal))
            return KnowledgeSearchSnapshot(
                query,
                principal.tenant_id,
                principal.user_id,
                owner,
                deepcopy(aliases),
                tuple(deepcopy(factory_rows)) + deepcopy(personal_rows),
                tuple(sources),
            )
        except (TimeoutError, KnowledgeSearchTimeoutError):
            raise KnowledgeSearchTimeoutError(
                "knowledge-search source timed out"
            ) from None
        except Exception:  # noqa: BLE001 - source details are never public.
            raise KnowledgeSearchDataError(
                "knowledge-search source is unavailable"
            ) from None
