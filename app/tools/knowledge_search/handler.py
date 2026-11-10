"""Pure native handler for bounded knowledge retrieval."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
)
from app.knowledge.ranking import _metadata_rerank
from app.knowledge.search_contracts import validate_factory_candidates
from app.knowledge.search_query import search_terms
from app.tools.knowledge_search.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchInput,
    KnowledgeSearchPort,
    KnowledgeSearchSnapshot,
    KnowledgeSearchTimeoutError,
    copied_candidates,
    knowledge_owner_id,
    knowledge_scope,
    prepare_search,
    validate_aliases,
    validate_knowledge_search_output,
)


@dataclass(frozen=True, slots=True)
class KnowledgeSearchDependencies:
    port: KnowledgeSearchPort
    default_tenant_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.default_tenant_id, str)
            or not self.default_tenant_id.strip()
        ):
            raise ValueError("default_tenant_id must be a non-empty string")


def _source_error() -> KnowledgeSearchDataError:
    return KnowledgeSearchDataError("knowledge-search source returned invalid data")


def _candidate(
    value: dict[str, object], expected_owner: str | None, tenant_id: str, user_id: str
) -> None:
    source_type = value.get("source_type")
    if source_type not in {"personal", "knowledge", "case"}:
        raise _source_error()
    reference_id = value.get("reference_id")
    if not isinstance(reference_id, str) or not reference_id.strip():
        raise _source_error()
    for key in (
        "tenant_id",
        "tenant",
        "owner_user_id",
        "owner_id",
        "knowledge_owner_id",
        "user_id",
    ):
        if (
            key in value
            and value[key] is not None
            and (not isinstance(value[key], str) or not value[key].strip())
        ):
            raise _source_error()
    if any(value[key] != tenant_id for key in ("tenant_id", "tenant") if key in value):
        raise _source_error()
    if "user_id" in value and value["user_id"] != user_id:
        raise _source_error()
    if source_type == "personal":
        if expected_owner is None:
            raise _source_error()
        for key in ("process_steps", "equipment_ids", "tags"):
            item = value.get(key, [])
            if not isinstance(item, list) or any(
                not isinstance(entry, str) for entry in item
            ):
                raise _source_error()
        if not isinstance(value.get("title", ""), str):
            raise _source_error()
        if any(
            value[key] != expected_owner
            for key in ("owner_user_id", "owner_id", "knowledge_owner_id")
            if key in value
        ):
            raise _source_error()
    elif source_type == "knowledge":
        if any(
            value.get(key) is not None
            for key in ("owner_user_id", "owner_id", "knowledge_owner_id")
        ):
            raise _source_error()
        if value.get("status") != "Active":
            raise _source_error()
        for key in ("process_steps", "tags", "title", "section"):
            if key in value and not isinstance(value[key], str):
                raise _source_error()
        authority = value.get("authority", 0)
        if (
            isinstance(authority, bool)
            or not isinstance(authority, int)
            or not 0 <= authority <= 5
        ):
            raise _source_error()
    else:
        if any(
            value.get(key) is not None
            for key in ("owner_user_id", "owner_id", "knowledge_owner_id")
        ):
            raise _source_error()
        if value.get("case_status") != "Validated":
            raise _source_error()
        for key in (
            "process_step",
            "equipment_id",
            "equipment_family",
            "defect_type",
            "occurred_date",
        ):
            if (
                key in value
                and value[key] is not None
                and not isinstance(value[key], str)
            ):
                raise _source_error()
        confidence = value.get("root_cause_confidence", 0)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise _source_error()


def _snapshot(
    input_value: KnowledgeSearchInput,
    context: ToolExecutionContext[KnowledgeSearchDependencies],
) -> tuple[list[dict[str, object]], tuple, dict[str, str | None]]:
    query = input_value.resolve()
    if not search_terms(query.query):
        return [], (), {"process_step": None, "equipment_id": None, "defect_type": None}
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except KnowledgeSearchTimeoutError:
        raise
    except KnowledgeSearchDataError:
        raise
    except Exception as exc:
        raise KnowledgeSearchDataError(
            "knowledge-search source is unavailable"
        ) from exc
    expected_owner = (
        knowledge_owner_id(context.principal, context.dependencies.default_tenant_id)
        if "personal" in query.source_types
        else None
    )
    try:
        if (
            not isinstance(snapshot, KnowledgeSearchSnapshot)
            or snapshot.query != query
            or snapshot.tenant_id != context.principal.tenant_id
            or snapshot.user_id != context.principal.user_id
            or snapshot.owner_user_id != expected_owner
            or (snapshot.candidates and not snapshot.sources)
            or any(
                source.scope != knowledge_scope(context.principal)
                for source in snapshot.sources
            )
        ):
            raise _source_error()
        aliases = validate_aliases(snapshot.aliases)
        filters, _, _ = prepare_search(query, aliases)
        rows = copied_candidates(snapshot.candidates)
        json.dumps(rows, allow_nan=False)
        validate_factory_candidates(
            [row for row in rows if row.get("source_type") in {"knowledge", "case"}]
        )
        for row in rows:
            _candidate(row, expected_owner, snapshot.tenant_id, snapshot.user_id)
        return rows, snapshot.sources, filters
    except KnowledgeSearchDataError:
        raise
    except Exception as exc:
        raise _source_error() from exc


def knowledge_search_handler(
    input_value: KnowledgeSearchInput,
    context: ToolExecutionContext[KnowledgeSearchDependencies],
) -> ToolResult[object]:
    rows, sources, filters = _snapshot(input_value, context)
    try:
        data = _metadata_rerank(
            deepcopy(rows), filters, input_value.limit, list(input_value.source_types)
        )
        validate_knowledge_search_output(data)
    except KnowledgeSearchDataError:
        raise
    except Exception as exc:
        raise _source_error() from exc
    return ToolResult(
        context.call_id,
        "search_knowledge",
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=data,
        sources=sources,
        row_count=len(data),
    )
