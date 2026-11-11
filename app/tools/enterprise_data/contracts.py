"""Typed, bounded contracts for enterprise manufacturing data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Literal, Protocol

from app.agent_runtime.tools.contracts import (
    ToolPrincipal,
    ToolScope,
    ToolSource,
)
from app.agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from app.core.manufacturing_terms import MANUFACTURING_STEPS

_ENTITIES = frozenset(("lots", "process-runs", "sensor-events"))
_STATUSES = frozenset(("Completed", "Running", "Hold"))
_ALLOWED = {
    "lots": frozenset(("start", "end", "product", "status")),
    "process-runs": frozenset(("start", "end", "process_step", "equipment_id")),
    "sensor-events": frozenset(
        ("start", "end", "process_step", "equipment_id", "signal_name")
    ),
}


class EnterpriseInputError(ToolInputError):
    pass


class EnterpriseDataError(ToolDataSourceError):
    pass


class EnterpriseTimeoutError(EnterpriseDataError, ToolSourceTimeout):
    pass


def _date(value: object, name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise EnterpriseInputError(f"{name} must be a date")
    return value


@dataclass(frozen=True, slots=True)
class EnterpriseWindow:
    as_of: date
    retention_days: int = 730
    summary_default_days: int = 90

    def __post_init__(self) -> None:
        _date(self.as_of, "as_of")
        for name in ("retention_days", "summary_default_days"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EnterpriseInputError(f"{name} must be a positive integer")
        try:
            self.as_of - timedelta(days=self.retention_days - 1)
            self.as_of - timedelta(days=self.summary_default_days - 1)
        except OverflowError as exc:
            raise EnterpriseInputError("date window cannot be represented") from exc

    @property
    def retention_start(self) -> date:
        return self.as_of - timedelta(days=self.retention_days - 1)


def _arguments(arguments: Mapping[str, object], allowed: set[str]) -> dict[str, object]:
    if not isinstance(arguments, Mapping):
        raise EnterpriseInputError("arguments must be an object")
    if set(arguments) - allowed:
        raise EnterpriseInputError("unknown enterprise-data argument")
    if any(value is None for value in arguments.values()):
        raise EnterpriseInputError("null enterprise-data arguments are not allowed")
    return dict(arguments)


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EnterpriseInputError(f"{name} must be a string")
    value = value.strip()
    if not value:
        raise EnterpriseInputError(f"{name} must not be blank")
    return value


def _optional_date_text(value: object, name: str) -> str | None:
    value = _optional_text(value, name)
    if value is not None:
        if len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise EnterpriseInputError(f"{name} must use YYYY-MM-DD")
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError(value)
        except ValueError as exc:
            raise EnterpriseInputError(f"{name} must use YYYY-MM-DD") from exc
    return value


def _interval(
    start: str | None, end: str | None, window: EnterpriseWindow, default_days: int
) -> tuple[date, date]:
    first = (
        date.fromisoformat(start)
        if start
        else window.as_of - timedelta(days=default_days - 1)
    )
    last = date.fromisoformat(end) if end else window.as_of
    if first > last:
        raise EnterpriseInputError("start must not be after end")
    first, last = max(first, window.retention_start), min(last, window.as_of)
    if first > last:
        raise EnterpriseInputError("requested dates do not overlap retention")
    return first, last


@dataclass(frozen=True, slots=True)
class EnterpriseQuery:
    kind: Literal["manifest", "summary", "sample"]
    filters: tuple[tuple[str, str], ...] = ()
    entity: str | None = None
    limit: int | None = None
    effective_start: date | None = None
    effective_end: date | None = None
    as_of: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {
            "manifest",
            "summary",
            "sample",
        }:
            raise EnterpriseInputError("invalid enterprise query kind")
        if not isinstance(self.filters, tuple) or any(
            not isinstance(p, tuple)
            or len(p) != 2
            or not all(isinstance(x, str) and x for x in p)
            for p in self.filters
        ):
            raise EnterpriseInputError("invalid enterprise query filters")
        if len({key for key, _ in self.filters}) != len(self.filters):
            raise EnterpriseInputError("duplicate enterprise query filter")
        object.__setattr__(self, "filters", tuple(sorted(self.filters)))
        if self.as_of is not None:
            _date(self.as_of, "as_of")
        if self.kind == "manifest":
            if (
                self.filters
                or self.entity is not None
                or self.limit is not None
                or self.effective_start is not None
                or self.effective_end is not None
            ):
                raise EnterpriseInputError("manifest query cannot have filters")
            return
        if self.kind == "sample" and (
            not isinstance(self.entity, str) or self.entity not in _ENTITIES
        ):
            raise EnterpriseInputError("invalid sample entity")
        if self.kind == "summary" and self.entity is not None:
            raise EnterpriseInputError("summary query has no entity")
        if self.kind == "sample":
            if (
                isinstance(self.limit, bool)
                or not isinstance(self.limit, int)
                or not 1 <= self.limit <= 50
            ):
                raise EnterpriseInputError("sample limit must be between 1 and 50")
        elif self.limit is not None:
            raise EnterpriseInputError("summary query has no limit")
        if self.effective_start is None or self.effective_end is None:
            raise EnterpriseInputError("query requires effective dates")
        if self.as_of is None:
            raise EnterpriseInputError("dated query requires as_of")
        _date(self.effective_start, "effective_start")
        _date(self.effective_end, "effective_end")
        if self.effective_start > self.effective_end or self.effective_end > self.as_of:
            raise EnterpriseInputError("invalid effective dates")
        allowed = (
            {"start", "end", "process_step", "equipment_id"}
            if self.kind == "summary"
            else _ALLOWED[self.entity]
        )  # type: ignore[index]
        if {key for key, _ in self.filters} - allowed:
            raise EnterpriseInputError("query has unsupported filters")
        for key, value in self.filters:
            if key in {"start", "end"}:
                _optional_date_text(value, key)
            elif key == "process_step" and (value not in MANUFACTURING_STEPS):
                raise EnterpriseInputError("invalid process_step")
            elif key == "status" and value not in _STATUSES:
                raise EnterpriseInputError("invalid status")

    def filter_dict(self) -> dict[str, str]:
        return dict(self.filters)


@dataclass(frozen=True, slots=True)
class EnterpriseManifestInput:
    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> EnterpriseManifestInput:
        _arguments(arguments, set())
        return cls()

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def resolve(self, window: EnterpriseWindow) -> EnterpriseQuery:
        return EnterpriseQuery("manifest", as_of=window.as_of)


@dataclass(frozen=True, slots=True)
class EnterpriseSummaryInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _optional_date_text(self.start, "start"))
        object.__setattr__(self, "end", _optional_date_text(self.end, "end"))
        step = _optional_text(self.process_step, "process_step")
        if step is not None and (
            step != step.upper() or step not in MANUFACTURING_STEPS
        ):
            raise EnterpriseInputError("process_step is not a known manufacturing step")
        object.__setattr__(self, "process_step", step)
        object.__setattr__(
            self, "equipment_id", _optional_text(self.equipment_id, "equipment_id")
        )

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> EnterpriseSummaryInput:
        return cls(
            **_arguments(arguments, {"start", "end", "process_step", "equipment_id"})
        )

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": "YYYY-MM-DD; default recent 90 days",
                },
                "end": {"type": "string", "description": "YYYY-MM-DD; default as_of"},
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "equipment_id": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def resolve(self, window: EnterpriseWindow) -> EnterpriseQuery:
        start, end = _interval(
            self.start, self.end, window, window.summary_default_days
        )
        filters = tuple(
            (k, v)
            for k, v in (
                ("start", self.start),
                ("end", self.end),
                ("process_step", self.process_step),
                ("equipment_id", self.equipment_id),
            )
            if v is not None
        )
        return EnterpriseQuery(
            "summary",
            filters,
            effective_start=start,
            effective_end=end,
            as_of=window.as_of,
        )


@dataclass(frozen=True, slots=True)
class EnterpriseSampleInput:
    entity: str
    limit: int = 20
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None
    product: str | None = None
    status: str | None = None
    signal_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entity, str) or self.entity not in _ENTITIES:
            raise EnterpriseInputError("invalid sample entity")
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 50
        ):
            raise EnterpriseInputError("sample limit must be between 1 and 50")
        for name in ("start", "end"):
            object.__setattr__(
                self, name, _optional_date_text(getattr(self, name), name)
            )
        step = _optional_text(self.process_step, "process_step")
        if step is not None and (
            step != step.upper() or step not in MANUFACTURING_STEPS
        ):
            raise EnterpriseInputError("process_step is not a known manufacturing step")
        object.__setattr__(self, "process_step", step)
        for name in ("equipment_id", "product", "status", "signal_name"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if self.status is not None and self.status not in _STATUSES:
            raise EnterpriseInputError("invalid status")
        values = (
            self.__dict__
            if hasattr(self, "__dict__")
            else {
                name: getattr(self, name)
                for name in (
                    "start",
                    "end",
                    "process_step",
                    "equipment_id",
                    "product",
                    "status",
                    "signal_name",
                )
            }
        )
        if any(
            values[name] is not None and name not in _ALLOWED[self.entity]
            for name in values
        ):
            raise EnterpriseInputError("filter is not supported by this entity")

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> EnterpriseSampleInput:
        values = _arguments(
            arguments,
            {
                "entity",
                "limit",
                "start",
                "end",
                "process_step",
                "equipment_id",
                "product",
                "status",
                "signal_name",
            },
        )
        if "entity" not in values:
            raise EnterpriseInputError("entity is required")
        return cls(**values)

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "enum": sorted(_ENTITIES)},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "start": {
                    "type": "string",
                    "description": "YYYY-MM-DD; default recent 730 days",
                },
                "end": {
                    "type": "string",
                    "description": "YYYY-MM-DD; default as_of",
                },
                "process_step": {
                    "type": "string",
                    "enum": list(MANUFACTURING_STEPS),
                },
                "equipment_id": {"type": "string"},
                "product": {"type": "string"},
                "status": {"type": "string", "enum": sorted(_STATUSES)},
                "signal_name": {"type": "string"},
            },
            "required": ["entity"],
            "additionalProperties": False,
        }

    def resolve(self, window: EnterpriseWindow) -> EnterpriseQuery:
        start, end = _interval(self.start, self.end, window, window.retention_days)
        filters = tuple(
            (k, getattr(self, k))
            for k in _ALLOWED[self.entity]
            if getattr(self, k) is not None
        )
        return EnterpriseQuery(
            "sample", filters, self.entity, self.limit, start, end, window.as_of
        )


@dataclass(frozen=True, slots=True)
class EnterpriseSnapshot:
    query: EnterpriseQuery
    data: dict[str, object]
    source: ToolSource

    def __post_init__(self) -> None:
        if (
            not isinstance(self.query, EnterpriseQuery)
            or not isinstance(self.data, dict)
            or not isinstance(self.source, ToolSource)
        ):
            raise EnterpriseDataError("invalid enterprise snapshot")


class EnterpriseDataPort(Protocol):
    def fetch(
        self, query: EnterpriseQuery, principal: ToolPrincipal
    ) -> EnterpriseSnapshot: ...


def enterprise_scope(query: EnterpriseQuery, principal: ToolPrincipal) -> ToolScope:
    filters = query.filter_dict()
    return ToolScope(
        principal.tenant_id,
        query.effective_start,
        query.effective_end,
        (filters["equipment_id"],) if "equipment_id" in filters else (),
        (filters["process_step"],) if "process_step" in filters else (),
        grain={
            "manifest": "enterprise_manifest",
            "summary": "enterprise_aggregate",
            "sample": "enterprise_sample",
        }[query.kind],
    )


def _count(v: object, name: str) -> None:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise EnterpriseDataError(f"invalid {name} from source")


def _number(v: object, name: str) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v):
        raise EnterpriseDataError(f"invalid {name} from source")


def _exact_keys(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise EnterpriseDataError(f"invalid {label} from source")
    return value


def _text(value: object, name: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise EnterpriseDataError(f"invalid {name} from source")


def _flag(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1}:
        raise EnterpriseDataError(f"invalid {name} from source")


def _iso_datetime(value: object, name: str) -> date:
    _text(value, name)
    if not isinstance(value, str) or "T" not in value:
        raise EnterpriseDataError(f"invalid {name} from source")
    try:
        return datetime.fromisoformat(value).date()  # type: ignore[arg-type]
    except ValueError as exc:
        raise EnterpriseDataError(f"invalid {name} from source") from exc


def _iso_date(value: object, name: str) -> date:
    if (
        not isinstance(value, str)
        or len(value) != 10
        or value[4] != "-"
        or value[7] != "-"
    ):
        raise EnterpriseDataError(f"invalid {name} from source")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EnterpriseDataError(f"invalid {name} from source") from exc


_OUTPUT_COMMON = {
    "provider": {"type": "string", "minLength": 1},
    "simulated": {"type": "boolean"},
    "tenant_id": {"type": "string", "minLength": 1},
}
_OUTPUT_PROPERTIES = {
    "manifest": {
        **_OUTPUT_COMMON,
        "virtual_scale": {"type": "object", "properties": {name: {"type": "integer", "minimum": 0} for name in sorted(_ENTITIES)}, "required": sorted(_ENTITIES), "additionalProperties": False},
        "entities": {"type": "object", "properties": {name: {"type": "object", "properties": {"path": {"type": "string"}, "primary_key": {"type": "string"}}, "required": ["path", "primary_key"], "additionalProperties": False} for name in sorted(_ENTITIES)}, "required": sorted(_ENTITIES), "additionalProperties": False},
        "analytics": {"type": "object", "properties": {"summary_path": {"type": "string"}, "semantics": {"type": "string"}, "supports": {"type": "array", "items": {"type": "string"}}}, "required": ["summary_path", "semantics", "supports"], "additionalProperties": False},
        "pagination": {"type": "object", "properties": {"strategy": {"type": "string"}, "default_limit": {"type": "integer", "minimum": 1}, "max_limit": {"type": "integer", "minimum": 1}}, "required": ["strategy", "default_limit", "max_limit"], "additionalProperties": False},
        "retention_days": {"type": "integer", "minimum": 0},
        "partition_recommendation": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "data_classification": {"type": "string", "minLength": 1},
    },
    "summary": {
        **_OUTPUT_COMMON,
        "query": {"type": "object", "properties": {"filters": {"type": "object"}, "effective_start": {"type": "string"}, "effective_end": {"type": "string"}, "query_id": {"type": "string"}}, "required": ["filters", "effective_start", "effective_end", "query_id"], "additionalProperties": False},
        "aggregation": {"type": "object", "properties": {"semantics": {"type": "string"}, "exact": {"type": "boolean"}, "description": {"type": "string"}}, "required": ["semantics", "exact", "description"], "additionalProperties": False},
        "totals": {"type": "object", "properties": {name: {"type": "integer", "minimum": 0} for name in ("lots", "completed_lots", "wafers", "process_runs", "sensor_events")}, "required": ["lots", "completed_lots", "wafers", "process_runs", "sensor_events"], "additionalProperties": False},
        "kpis": {"type": "object", "properties": {**{name: {"type": "number", "minimum": 0, "maximum": 100} for name in ("yield_pct", "process_pass_rate_pct", "hold_rate_pct", "excursion_rate_pct", "sensor_missing_pct", "sensor_outlier_pct")}, "avg_cycle_hours": {"type": "number"}, "excursion_runs": {"type": "integer", "minimum": 0}}, "required": ["yield_pct", "process_pass_rate_pct", "avg_cycle_hours", "hold_rate_pct", "excursion_rate_pct", "excursion_runs", "sensor_missing_pct", "sensor_outlier_pct"], "additionalProperties": False},
        "equipment": {"type": "array", "items": {"type": "object", "properties": {"equipment_id": {"type": "string"}, "projected_runs": {"type": "integer", "minimum": 0}, **{name: {"type": "number", "minimum": 0, "maximum": 100} for name in ("pass_rate_pct", "excursion_rate_pct", "health_score")}, "risk": {"enum": ["high", "watch", "stable"]}}, "required": ["equipment_id", "projected_runs", "pass_rate_pct", "excursion_rate_pct", "health_score", "risk"], "additionalProperties": False}},
        "lineage": {"type": "object", "properties": {**{name: {"type": "string"} for name in ("source", "classification", "as_of", "freshness")}, "generated_from": {"type": "array", "items": {"type": "string"}}}, "required": ["source", "classification", "generated_from", "as_of", "freshness"], "additionalProperties": False},
    },
    "sample": {
        **_OUTPUT_COMMON,
        "entity": {"enum": sorted(_ENTITIES)},
        "filters": {"type": "object", "additionalProperties": {"type": "string"}},
        # Entity-specific record semantics remain enforced by the existing validator.
        "records": {"type": "array", "items": {"type": "object"}},
        "page": {"type": "object", "properties": {**{name: {"type": "integer", "minimum": 0} for name in ("count", "position", "estimated_total")}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "next_cursor": {"type": ["string", "null"], "minLength": 1}}, "required": ["count", "limit", "position", "estimated_total", "next_cursor"], "additionalProperties": False},
    },
}
ENTERPRISE_OUTPUT_SCHEMAS = {
    kind: {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    for kind, properties in _OUTPUT_PROPERTIES.items()
}


def validate_enterprise_manifest_output(value: object) -> object:
    data = _exact_keys(
        value,
        {
            "provider",
            "simulated",
            "tenant_id",
            "virtual_scale",
            "entities",
            "analytics",
            "pagination",
            "retention_days",
            "partition_recommendation",
            "data_classification",
        },
        "manifest",
    )
    if (
        not isinstance(data["provider"], str)
        or not data["provider"].strip()
        or not isinstance(data["simulated"], bool)
        or not isinstance(data["tenant_id"], str)
        or not data["tenant_id"].strip()
        or not isinstance(data["virtual_scale"], dict)
        or set(data["virtual_scale"]) != _ENTITIES
    ):
        raise EnterpriseDataError("invalid manifest from source")
    for n in data["virtual_scale"].values():
        _count(n, "virtual scale")
    entities = data["entities"]
    if not isinstance(entities, dict) or set(entities) != _ENTITIES:
        raise EnterpriseDataError("invalid manifest entities")
    for entity, primary_key in (
        ("lots", "lot_id"),
        ("process-runs", "run_id"),
        ("sensor-events", "reading_id"),
    ):
        row = _exact_keys(entities[entity], {"path", "primary_key"}, "manifest entity")
        _text(row["path"], "entity path")
        if row["primary_key"] != primary_key:
            raise EnterpriseDataError("invalid manifest entity")
    analytics = _exact_keys(
        data["analytics"],
        {"summary_path", "semantics", "supports"},
        "manifest analytics",
    )
    _text(analytics["summary_path"], "summary path")
    if (
        not isinstance(analytics["semantics"], str)
        or not analytics["semantics"].strip()
        or analytics["supports"] != ["date_range", "process_step", "equipment_id"]
    ):
        raise EnterpriseDataError("invalid manifest analytics")
    if (
        data["simulated"] is True
        and analytics["semantics"] != "deterministic_projection"
    ):
        raise EnterpriseDataError("invalid manifest analytics")
    pagination = _exact_keys(
        data["pagination"],
        {"strategy", "default_limit", "max_limit"},
        "manifest pagination",
    )
    if (
        not isinstance(pagination["strategy"], str)
        or not pagination["strategy"].strip()
        or isinstance(pagination["default_limit"], bool)
        or not isinstance(pagination["default_limit"], int)
        or pagination["default_limit"] < 1
        or isinstance(pagination["max_limit"], bool)
        or not isinstance(pagination["max_limit"], int)
        or pagination["max_limit"] < pagination["default_limit"]
    ):
        raise EnterpriseDataError("invalid manifest pagination")
    _count(data["retention_days"], "retention_days")
    if (
        not isinstance(data["partition_recommendation"], list)
        or not data["partition_recommendation"]
        or any(
            not isinstance(item, str) or not item
            for item in data["partition_recommendation"]
        )
    ):
        raise EnterpriseDataError("invalid manifest partition")
    _text(data["data_classification"], "data_classification")
    return value


def validate_enterprise_summary_output(value: object) -> object:
    data = _exact_keys(
        value,
        {
            "provider",
            "simulated",
            "tenant_id",
            "query",
            "aggregation",
            "totals",
            "kpis",
            "equipment",
            "lineage",
        },
        "summary",
    )
    for key in ("provider", "tenant_id"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise EnterpriseDataError("invalid summary from source")
    if not isinstance(data["simulated"], bool):
        raise EnterpriseDataError("invalid summary simulation")
    query = _exact_keys(
        data["query"],
        {"filters", "effective_start", "effective_end", "query_id"},
        "summary query",
    )
    if not isinstance(query["filters"], dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in query["filters"].items()
    ):
        raise EnterpriseDataError("invalid summary filters")
    if set(query["filters"]) - {"start", "end", "process_step", "equipment_id"}:
        raise EnterpriseDataError("invalid summary filters")
    _iso_date(query["effective_start"], "effective_start")
    _iso_date(query["effective_end"], "effective_end")
    _text(query["query_id"], "query_id")
    totals = _exact_keys(
        data["totals"],
        {"lots", "completed_lots", "wafers", "process_runs", "sensor_events"},
        "summary totals",
    )
    for k, v in totals.items():
        _count(v, k)
    if totals["completed_lots"] > totals["lots"]:
        raise EnterpriseDataError("invalid completed_lots")
    aggregation = _exact_keys(
        data["aggregation"],
        {"semantics", "exact", "description"},
        "summary aggregation",
    )
    _text(aggregation["semantics"], "aggregation semantics")
    _text(aggregation["description"], "aggregation description")
    if not isinstance(aggregation["exact"], bool):
        raise EnterpriseDataError("invalid aggregation exact")
    kpis = _exact_keys(
        data["kpis"],
        {
            "yield_pct",
            "process_pass_rate_pct",
            "avg_cycle_hours",
            "hold_rate_pct",
            "excursion_rate_pct",
            "excursion_runs",
            "sensor_missing_pct",
            "sensor_outlier_pct",
        },
        "summary kpis",
    )
    for k, v in kpis.items():
        if k == "excursion_runs":
            _count(v, k)
        else:
            _number(v, k)
    for k in (
        "yield_pct",
        "process_pass_rate_pct",
        "hold_rate_pct",
        "excursion_rate_pct",
        "sensor_missing_pct",
        "sensor_outlier_pct",
    ):
        if k not in kpis or not 0 <= kpis[k] <= 100:
            raise EnterpriseDataError("invalid summary percentage")
    if not isinstance(data["equipment"], list):
        raise EnterpriseDataError("invalid equipment")
    for row in data["equipment"]:
        row = _exact_keys(
            row,
            {
                "equipment_id",
                "projected_runs",
                "pass_rate_pct",
                "excursion_rate_pct",
                "health_score",
                "risk",
            },
            "equipment",
        )
        _text(row["equipment_id"], "equipment_id")
        _count(row["projected_runs"], "projected_runs")
        for k in ("pass_rate_pct", "excursion_rate_pct", "health_score"):
            _number(row.get(k), k)
        if (
            not 0 <= row["pass_rate_pct"] <= 100
            or not 0 <= row["excursion_rate_pct"] <= 100
            or not 0 <= row["health_score"] <= 100
            or not isinstance(row["risk"], str)
            or row["risk"] not in {"high", "watch", "stable"}
        ):
            raise EnterpriseDataError("invalid equipment")
    lineage = _exact_keys(
        data["lineage"],
        {"source", "classification", "generated_from", "as_of", "freshness"},
        "summary lineage",
    )
    for key in ("source", "classification", "as_of", "freshness"):
        _text(lineage[key], key)
    _iso_datetime(lineage["as_of"], "as_of")
    if not isinstance(lineage["generated_from"], list) or any(
        not isinstance(item, str) or not item for item in lineage["generated_from"]
    ):
        raise EnterpriseDataError("invalid summary lineage")
    return value


def validate_enterprise_sample_output(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {
        "provider",
        "simulated",
        "tenant_id",
        "entity",
        "filters",
        "records",
        "page",
    }:
        raise EnterpriseDataError("invalid sample from source")
    if (
        not isinstance(value["provider"], str)
        or not value["provider"].strip()
        or not isinstance(value["simulated"], bool)
        or not isinstance(value["tenant_id"], str)
        or not value["tenant_id"].strip()
        or not isinstance(value["entity"], str)
        or value["entity"] not in _ENTITIES
        or not isinstance(value["filters"], dict)
        or not isinstance(value["records"], list)
    ):
        raise EnterpriseDataError("invalid sample from source")
    if not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value["filters"].items()
    ):
        raise EnterpriseDataError("invalid sample filters")
    if set(value["filters"]) - _ALLOWED[value["entity"]]:
        raise EnterpriseDataError("invalid sample filters")
    page = value["page"]
    if not isinstance(page, dict) or set(page) != {
        "count",
        "limit",
        "position",
        "estimated_total",
        "next_cursor",
    }:
        raise EnterpriseDataError("invalid sample page")
    for k in ("count", "limit", "position", "estimated_total"):
        _count(page[k], k)
    if (
        page["count"] != len(value["records"])
        or page["position"] != 0
        or page["count"] > page["limit"]
        or page["estimated_total"] < page["count"]
        or not 1 <= page["limit"] <= 50
        or (
            page["next_cursor"] is not None
            and (
                not isinstance(page["next_cursor"], str)
                or not page["next_cursor"].strip()
            )
        )
    ):
        raise EnterpriseDataError("invalid sample page")
    fields = {
        "lots": {
            "tenant_id",
            "lot_id",
            "product",
            "technology_nm",
            "route",
            "priority",
            "start_time",
            "status",
            "wafer_count",
            "good_wafers",
            "yield_rate",
            "cycle_time_hours",
            "synthetic",
        },
        "process-runs": {
            "tenant_id",
            "run_id",
            "lot_id",
            "operation_seq",
            "process_step",
            "equipment_id",
            "chamber",
            "recipe",
            "run_time",
            "measurement_name",
            "measurement_value",
            "measurement_unit",
            "pass_flag",
            "synthetic",
        },
        "sensor-events": {
            "tenant_id",
            "reading_id",
            "lot_id",
            "process_step",
            "equipment_id",
            "chamber",
            "sample_time",
            "signal_name",
            "signal_value",
            "signal_unit",
            "is_missing",
            "is_outlier",
            "synthetic",
        },
    }[value["entity"]]
    for row in value["records"]:
        row = _exact_keys(row, fields, "sample record")
        if row["tenant_id"] != value["tenant_id"] or not isinstance(
            row["synthetic"], bool
        ):
            raise EnterpriseDataError("invalid sample record")
        text_fields = fields - {
            "tenant_id",
            "technology_nm",
            "operation_seq",
            "wafer_count",
            "good_wafers",
            "yield_rate",
            "cycle_time_hours",
            "measurement_value",
            "pass_flag",
            "signal_value",
            "is_missing",
            "is_outlier",
            "synthetic",
            "start_time",
            "run_time",
            "sample_time",
        }
        for key in text_fields:
            _text(row[key], key)
        if value["entity"] == "lots":
            _count(row["technology_nm"], "technology_nm")
            _count(row["wafer_count"], "wafer_count")
            _count(row["good_wafers"], "good_wafers")
            _number(row["yield_rate"], "yield_rate")
            _number(row["cycle_time_hours"], "cycle_time_hours")
            _iso_datetime(row["start_time"], "start_time")
            if (
                row["technology_nm"] < 1
                or row["good_wafers"] > row["wafer_count"]
                or not 0 <= row["yield_rate"] <= 1
                or row["cycle_time_hours"] < 0
                or not isinstance(row["status"], str)
                or row["status"] not in _STATUSES
            ):
                raise EnterpriseDataError("invalid lot record")
        elif value["entity"] == "process-runs":
            _count(row["operation_seq"], "operation_seq")
            _number(row["measurement_value"], "measurement_value")
            _flag(row["pass_flag"], "pass_flag")
            _iso_datetime(row["run_time"], "run_time")
            if (
                row["operation_seq"] < 1
                or not isinstance(row["process_step"], str)
                or row["process_step"] not in MANUFACTURING_STEPS
            ):
                raise EnterpriseDataError("invalid process record")
        else:
            _number(row["signal_value"], "signal_value")
            _flag(row["is_missing"], "is_missing")
            _flag(row["is_outlier"], "is_outlier")
            _iso_datetime(row["sample_time"], "sample_time")
            if (
                not isinstance(row["process_step"], str)
                or row["process_step"] not in MANUFACTURING_STEPS
            ):
                raise EnterpriseDataError("invalid sensor record")
        for key, val in value["filters"].items():
            if key not in {"start", "end"} and row.get(key) != val:
                raise EnterpriseDataError("sample row outside requested filters")
    return value
