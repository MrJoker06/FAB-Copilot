"""Typed contracts for bounded knowledge and case retrieval."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from app.agent_runtime.tools.contracts import ToolPrincipal, ToolScope, ToolSource
from app.agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from app.core.manufacturing_terms import ANALYSIS_SCOPES
from app.knowledge.search_contracts import FACTORY_SOURCE_TYPES, FactorySearchRequest
from app.knowledge.search_policy import PROCESS_SEARCH_EXPANSIONS, infer_filters_from_aliases

_SOURCE_TYPES = frozenset(("personal", "knowledge", "case"))


class KnowledgeSearchInputError(ToolInputError):
    """Raised before a search source is contacted."""


class KnowledgeSearchDataError(ToolDataSourceError):
    """Sanitized source or source-contract failure."""


class KnowledgeSearchTimeoutError(KnowledgeSearchDataError, ToolSourceTimeout):
    """Typed timeout at the adapter boundary."""


def _text(value: object, name: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise KnowledgeSearchInputError(f"{name} must be a string")
    value = value.strip()
    if not value and required:
        return value
    if not value:
        raise KnowledgeSearchInputError(f"{name} must not be blank")
    return value


def _arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "query",
        "limit",
        "process_step",
        "equipment_id",
        "defect_type",
        "source_types",
    }
    if not isinstance(arguments, Mapping):
        raise KnowledgeSearchInputError("arguments must be an object")
    if set(arguments) - allowed:
        raise KnowledgeSearchInputError("unknown knowledge-search argument")
    if any(value is None for value in arguments.values()):
        raise KnowledgeSearchInputError(
            "null knowledge-search arguments are not allowed"
        )
    if "query" not in arguments:
        raise KnowledgeSearchInputError("query is required")
    values = dict(arguments)
    if "source_types" in values:
        raw = values["source_types"]
        if not isinstance(raw, list):
            raise KnowledgeSearchInputError("source_types must be an array")
        values["source_types"] = tuple(raw)
    return values


@dataclass(frozen=True, slots=True)
class KnowledgeSearchQuery:
    query: str
    limit: int = 5
    process_step: str | None = None
    equipment_id: str | None = None
    defect_type: str | None = None
    source_types: tuple[str, ...] = ("personal", "knowledge", "case")

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise KnowledgeSearchInputError("query must be a string")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 10
        ):
            raise KnowledgeSearchInputError("limit must be between 1 and 10")
        for name in ("process_step", "equipment_id", "defect_type"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise KnowledgeSearchInputError(f"{name} must be a non-empty string")
        if self.process_step is not None and self.process_step not in ANALYSIS_SCOPES:
            raise KnowledgeSearchInputError(
                "process_step is not a known analysis scope"
            )
        if (
            self.equipment_id is not None
            and self.equipment_id != self.equipment_id.upper()
        ):
            raise KnowledgeSearchInputError("equipment_id must be uppercase")
        if (
            not isinstance(self.source_types, tuple)
            or not self.source_types
            or len(self.source_types) > len(_SOURCE_TYPES)
            or any(
                not isinstance(item, str) or item not in _SOURCE_TYPES
                for item in self.source_types
            )
            or len(set(self.source_types)) != len(self.source_types)
        ):
            raise KnowledgeSearchInputError(
                "source_types must be unique supported sources"
            )

    @property
    def candidate_limit(self) -> int:
        return max(30, self.limit * 5)


@dataclass(frozen=True, slots=True)
class KnowledgeSearchInput:
    query: str
    limit: int = 5
    process_step: str | None = None
    equipment_id: str | None = None
    defect_type: str | None = None
    source_types: tuple[str, ...] = ("personal", "knowledge", "case")

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise KnowledgeSearchInputError("query must be a string")
        object.__setattr__(self, "query", self.query.strip())
        if self.process_step is not None:
            step = _text(self.process_step, "process_step")
            object.__setattr__(self, "process_step", step.upper() if step else None)
        if self.equipment_id is not None:
            equipment = _text(self.equipment_id, "equipment_id")
            object.__setattr__(
                self, "equipment_id", equipment.upper() if equipment else None
            )
        if self.defect_type is not None:
            object.__setattr__(
                self, "defect_type", _text(self.defect_type, "defect_type")
            )
        KnowledgeSearchQuery(
            self.query,
            self.limit,
            self.process_step,
            self.equipment_id,
            self.defect_type,
            self.source_types,
        )

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> KnowledgeSearchInput:
        return cls(**_arguments(arguments))

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                "process_step": {"type": "string", "enum": list(ANALYSIS_SCOPES)},
                "equipment_id": {"type": "string"},
                "defect_type": {"type": "string"},
                "source_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(_SOURCE_TYPES)},
                    "minItems": 1,
                    "maxItems": 3,
                    "uniqueItems": True,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def resolve(self) -> KnowledgeSearchQuery:
        return KnowledgeSearchQuery(
            self.query,
            self.limit,
            self.process_step,
            self.equipment_id,
            self.defect_type,
            self.source_types,
        )


@dataclass(frozen=True, slots=True)
class PersonalSearchBatch:
    owner_user_id: str
    rows: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.owner_user_id, str) or not self.owner_user_id.strip():
            raise KnowledgeSearchDataError("invalid personal search batch")
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, dict) for row in self.rows
        ):
            raise KnowledgeSearchDataError("invalid personal search batch")


@dataclass(frozen=True, slots=True)
class KnowledgeSearchSnapshot:
    query: KnowledgeSearchQuery
    tenant_id: str
    user_id: str
    owner_user_id: str | None
    aliases: dict[str, tuple[str, ...]]
    candidates: tuple[dict[str, object], ...]
    sources: tuple[ToolSource, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.query, KnowledgeSearchQuery):
            raise KnowledgeSearchDataError("invalid knowledge-search snapshot")
        for name in ("tenant_id", "user_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise KnowledgeSearchDataError("invalid knowledge-search snapshot")
        if self.owner_user_id is not None and (
            not isinstance(self.owner_user_id, str) or not self.owner_user_id.strip()
        ):
            raise KnowledgeSearchDataError("invalid knowledge-search snapshot")
        if not isinstance(self.aliases, dict) or not isinstance(self.candidates, tuple):
            raise KnowledgeSearchDataError("invalid knowledge-search snapshot")
        if any(not isinstance(row, dict) for row in self.candidates):
            raise KnowledgeSearchDataError("invalid knowledge-search snapshot")
        if not isinstance(self.sources, tuple) or any(
            not isinstance(source, ToolSource) for source in self.sources
        ):
            raise KnowledgeSearchDataError("invalid knowledge-search snapshot")


class KnowledgeSearchPort(Protocol):
    def fetch(
        self, query: KnowledgeSearchQuery, principal: ToolPrincipal
    ) -> KnowledgeSearchSnapshot: ...


class PersonalKnowledgeSearchPort(Protocol):
    def search(
        self, principal: ToolPrincipal, owner_user_id: str, query: str, limit: int
    ) -> PersonalSearchBatch: ...


def knowledge_owner_id(principal: ToolPrincipal, default_tenant_id: str) -> str:
    if not isinstance(default_tenant_id, str) or not default_tenant_id.strip():
        raise ValueError("default_tenant_id must be a non-empty string")
    return (
        principal.user_id
        if principal.tenant_id == default_tenant_id
        else f"{principal.tenant_id}:{principal.user_id}"
    )


def knowledge_scope(principal: ToolPrincipal) -> ToolScope:
    return ToolScope(principal.tenant_id, grain="knowledge_search")


def validate_aliases(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise KnowledgeSearchDataError("knowledge aliases are invalid")
    aliases: dict[str, tuple[str, ...]] = {}
    for name, items in value.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(items, tuple)
            or not items
        ):
            raise KnowledgeSearchDataError("knowledge aliases are invalid")
        if any(not isinstance(item, str) or not item.strip() for item in items):
            raise KnowledgeSearchDataError("knowledge aliases are invalid")
        aliases[name] = items
    return aliases


def prepare_search(
    query: KnowledgeSearchQuery, aliases: Mapping[str, object]
) -> tuple[dict[str, str | None], FactorySearchRequest, str]:
    aliases = validate_aliases(aliases)
    filters = infer_filters_from_aliases(
        query.query, query.process_step, query.equipment_id, query.defect_type, aliases
    )
    retrieval_query = " ".join(
        value for value in (query.query, *filters.values()) if value
    ).strip()
    requested = tuple(
        source for source in query.source_types if source in FACTORY_SOURCE_TYPES
    )
    request = FactorySearchRequest(
        raw_query=retrieval_query,
        inferred_filters=filters,
        candidate_limit=query.candidate_limit,
        source_types=requested or ("knowledge", "case"),
    )
    expansion = PROCESS_SEARCH_EXPANSIONS.get(filters.get("process_step"), "")
    return filters, request, f"{retrieval_query} {expansion}".strip()


def _finite_number(value: object, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise KnowledgeSearchDataError(f"invalid {name} from source")


KNOWLEDGE_SEARCH_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "source_type": {"enum": sorted(_SOURCE_TYPES)},
            "reference_id": {"type": "string", "minLength": 1},
            "retrieval": {
                "type": "object",
                "properties": {
                    "lexical_rank": {"type": "integer", "minimum": 1},
                    "final_score": {"type": "number"},
                    "confidence": {"enum": ["low", "medium", "high"]},
                    "selection_reason": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object", "properties": {name: {"type": ["string", "null"]} for name in ("process_step", "equipment_id", "defect_type")}, "required": ["process_step", "equipment_id", "defect_type"], "additionalProperties": False},
                },
                "required": ["lexical_rank", "final_score", "confidence", "selection_reason", "filters"],
                "additionalProperties": False,
            },
        },
        "required": ["source_type", "reference_id", "retrieval"],
        # Source-specific document fields are retained, not silently discarded.
        "additionalProperties": True,
        "allOf": [
            {"if": {"properties": {"source_type": {"const": "knowledge"}}}, "then": {"properties": {"status": {"const": "Active"}}, "required": ["status"]}},
            {"if": {"properties": {"source_type": {"const": "case"}}}, "then": {"properties": {"case_status": {"const": "Validated"}}, "required": ["case_status"]}},
        ],
    },
}


def validate_knowledge_search_output(value: object) -> object:
    if not isinstance(value, list):
        raise KnowledgeSearchDataError("knowledge-search output must be a list")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise KnowledgeSearchDataError(
            "knowledge-search output is not JSON-safe"
        ) from exc
    for row in value:
        if not isinstance(row, dict):
            raise KnowledgeSearchDataError("knowledge-search output row is invalid")
        source_type = row.get("source_type")
        if not isinstance(source_type, str) or source_type not in _SOURCE_TYPES:
            raise KnowledgeSearchDataError("knowledge-search output source is invalid")
        if source_type == "knowledge" and row.get("status") != "Active":
            raise KnowledgeSearchDataError("knowledge-search output source is invalid")
        if source_type == "case" and row.get("case_status") != "Validated":
            raise KnowledgeSearchDataError("knowledge-search output source is invalid")
        if (
            not isinstance(row.get("reference_id"), str)
            or not row["reference_id"].strip()
        ):
            raise KnowledgeSearchDataError("knowledge-search reference is invalid")
        retrieval = row.get("retrieval")
        if not isinstance(retrieval, dict) or set(retrieval) != {
            "lexical_rank",
            "final_score",
            "confidence",
            "selection_reason",
            "filters",
        }:
            raise KnowledgeSearchDataError(
                "knowledge-search retrieval metadata is invalid"
            )
        if (
            isinstance(retrieval["lexical_rank"], bool)
            or not isinstance(retrieval["lexical_rank"], int)
            or retrieval["lexical_rank"] < 1
        ):
            raise KnowledgeSearchDataError("knowledge-search lexical rank is invalid")
        _finite_number(retrieval["final_score"], "final_score")
        if not isinstance(retrieval["confidence"], str) or retrieval[
            "confidence"
        ] not in {"low", "medium", "high"}:
            raise KnowledgeSearchDataError("knowledge-search confidence is invalid")
        if not isinstance(retrieval["selection_reason"], list) or any(
            not isinstance(item, str) for item in retrieval["selection_reason"]
        ):
            raise KnowledgeSearchDataError(
                "knowledge-search selection reason is invalid"
            )
        if not isinstance(retrieval["filters"], dict) or set(retrieval["filters"]) != {
            "process_step",
            "equipment_id",
            "defect_type",
        }:
            raise KnowledgeSearchDataError("knowledge-search filters are invalid")
        if any(
            value is not None and not isinstance(value, str)
            for value in retrieval["filters"].values()
        ):
            raise KnowledgeSearchDataError("knowledge-search filters are invalid")
    return value


def copied_candidates(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    return deepcopy(list(rows))
