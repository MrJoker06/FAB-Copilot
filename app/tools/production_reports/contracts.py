"""Contracts for fixed production reports; they never accept arbitrary SQL."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Literal, Protocol

from app.agent_runtime.tools.contracts import ToolPrincipal, ToolScope, ToolSource
from app.agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from app.core.manufacturing_terms import MANUFACTURING_STEPS


class ProductionReportInputError(ToolInputError):
    """Public validation error raised before an adapter is contacted."""


class ProductionReportDataError(ToolDataSourceError):
    """Sanitized source or source-contract error."""


class ProductionReportTimeoutError(ProductionReportDataError, ToolSourceTimeout):
    """The fixed report query exceeded its local deadline."""


def _values(
    arguments: Mapping[str, object], allowed: set[str]
) -> dict[str, str | None]:
    if not isinstance(arguments, Mapping):
        raise ProductionReportInputError("arguments must be an object")
    if set(arguments) - allowed:
        raise ProductionReportInputError("unknown production-report argument")
    result: dict[str, str | None] = {}
    for key in allowed:
        value = arguments.get(key)
        if key in arguments and value is None:
            raise ProductionReportInputError(
                "null production-report arguments are not allowed"
            )
        if value is not None and not isinstance(value, str):
            raise ProductionReportInputError(f"{key} must be a string")
        result[key] = value
    return result


def _dates(start: str | None, end: str | None, as_of: date) -> tuple[date, date]:
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise ProductionReportInputError("as_of must be a date")
    try:
        first = date.fromisoformat(start) if start else as_of - timedelta(days=89)
        last = date.fromisoformat(end) if end else as_of
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProductionReportInputError("日期必须使用 YYYY-MM-DD 格式") from exc
    if first > last:
        raise ProductionReportInputError("开始日期不能晚于结束日期")
    if (last - first).days > 730:
        raise ProductionReportInputError("单次查询范围不能超过 730 天")
    if last == date.max:
        raise ProductionReportInputError("end date cannot be represented")
    return first, last


def _process(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.upper()
    if result not in MANUFACTURING_STEPS:
        raise ProductionReportInputError(
            "process_step is not a known manufacturing step"
        )
    return result


def _text(value: str | None, name: str, *, uppercase: bool = False) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ProductionReportInputError(f"{name} must not be blank")
    return value.upper() if uppercase else value


_DATES = {
    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，默认最近90天"},
    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
}


def _date_properties() -> dict[str, object]:
    return {key: dict(value) for key, value in _DATES.items()}


def _typed_optional(value: object, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise ProductionReportInputError(f"{name} must be a string")


@dataclass(frozen=True, slots=True)
class FabOverviewInput:
    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        _typed_optional(self.start, "start")
        _typed_optional(self.end, "end")

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> FabOverviewInput:
        return cls(**_values(arguments, {"start", "end"}))

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": _date_properties(),
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> ProductionReportQuery:
        start, end = _dates(self.start, self.end, as_of)
        return ProductionReportQuery("overview", start, end)


@dataclass(frozen=True, slots=True)
class YieldTrendInput:
    start: str | None = None
    end: str | None = None
    product: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end", "product"):
            _typed_optional(getattr(self, name), name)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> YieldTrendInput:
        return cls(**_values(arguments, {"start", "end", "product"}))

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {**_date_properties(), "product": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> ProductionReportQuery:
        start, end = _dates(self.start, self.end, as_of)
        return ProductionReportQuery(
            "yield", start, end, product=_text(self.product, "product")
        )


@dataclass(frozen=True, slots=True)
class ProcessPassRateInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step", "equipment_id"):
            _typed_optional(getattr(self, name), name)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ProcessPassRateInput:
        return cls(
            **_values(arguments, {"start", "end", "process_step", "equipment_id"})
        )

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                **_date_properties(),
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "equipment_id": {"type": "string"},
            },
            "required": ["process_step"],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> ProductionReportQuery:
        start, end = _dates(self.start, self.end, as_of)
        if self.process_step is None:
            raise ProductionReportInputError("process_step is required")
        return ProductionReportQuery(
            "pass_rate",
            start,
            end,
            _process(self.process_step),
            _text(self.equipment_id, "equipment_id", uppercase=True),
        )


@dataclass(frozen=True, slots=True)
class ProductionReportQuery:
    kind: Literal["overview", "yield", "pass_rate"]
    start: date
    end: date
    process_step: str | None = None
    equipment_id: str | None = None
    product: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"overview", "yield", "pass_rate"}:
            raise ProductionReportInputError("invalid production-report query kind")
        if (
            isinstance(self.start, datetime)
            or isinstance(self.end, datetime)
            or not isinstance(self.start, date)
            or not isinstance(self.end, date)
            or self.start > self.end
            or (self.end - self.start).days > 730
            or self.end == date.max
        ):
            raise ProductionReportInputError("invalid production-report date range")
        if (
            self.process_step is not None
            and self.process_step not in MANUFACTURING_STEPS
        ):
            raise ProductionReportInputError("invalid process_step")
        for name in ("equipment_id", "product"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ProductionReportInputError(f"invalid {name}")
        if (
            self.equipment_id is not None
            and self.equipment_id != self.equipment_id.upper()
        ):
            raise ProductionReportInputError("invalid equipment_id")
        if self.kind == "overview" and any(
            (self.process_step, self.equipment_id, self.product)
        ):
            raise ProductionReportInputError("overview query has unsupported filters")
        if self.kind == "yield" and any((self.process_step, self.equipment_id)):
            raise ProductionReportInputError("yield query has unsupported filters")
        if self.kind == "pass_rate" and (
            self.process_step is None or self.product is not None
        ):
            raise ProductionReportInputError(
                "pass-rate query requires process_step only"
            )

    @property
    def end_exclusive(self) -> date:
        try:
            return self.end + timedelta(days=1)
        except OverflowError as exc:
            raise ProductionReportInputError("end date cannot be represented") from exc


@dataclass(frozen=True, slots=True)
class ProductionReportSnapshot:
    query: ProductionReportQuery
    data: dict[str, object] | tuple[dict[str, object], ...]
    source: ToolSource

    def __post_init__(self) -> None:
        if not isinstance(self.query, ProductionReportQuery) or not isinstance(
            self.source, ToolSource
        ):
            raise ProductionReportDataError("invalid snapshot")
        if self.query.kind == "overview":
            if not isinstance(self.data, dict):
                raise ProductionReportDataError("overview snapshot must be an object")
        elif not isinstance(self.data, tuple) or any(
            not isinstance(row, dict) for row in self.data
        ):
            raise ProductionReportDataError("report snapshot rows are invalid")


class ProductionReportsPort(Protocol):
    def fetch(
        self, query: ProductionReportQuery, principal: ToolPrincipal
    ) -> ProductionReportSnapshot: ...


def production_report_scope(
    query: ProductionReportQuery, principal: ToolPrincipal
) -> ToolScope:
    return ToolScope(
        principal.tenant_id,
        query.start,
        query.end,
        (query.equipment_id,) if query.equipment_id else (),
        (query.process_step,) if query.process_step else (),
        grain={
            "overview": "fab_overview",
            "yield": "weekly_yield",
            "pass_rate": "process_pass_rate",
        }[query.kind],
    )


def _number(value: object, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ProductionReportDataError(f"invalid {name} from source")


def _count(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProductionReportDataError(f"invalid {name} from source")


FAB_OVERVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "lots": {"type": "integer", "minimum": 0},
        "excursions": {"type": "integer", "minimum": 0},
        "held_lots": {"type": ["integer", "null"], "minimum": 0},
        "wafers": {"type": ["integer", "null"], "minimum": 0},
        "good_wafers": {"type": ["integer", "null"], "minimum": 0},
        "yield_pct": {"type": ["number", "null"]},
        "avg_cycle_hours": {"type": ["number", "null"]},
        "avg_hold_hours": {"type": ["number", "null"]},
        "start": {"type": "string", "format": "date"},
        "end": {"type": "string", "format": "date"},
    },
    "required": ["lots", "excursions", "held_lots", "wafers", "good_wafers", "yield_pct", "avg_cycle_hours", "avg_hold_hours", "start", "end"],
    "additionalProperties": False,
}
YIELD_TREND_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "period": {"type": "string"},
            "week_start": {"type": "string", "format": "date"},
            "lots": {"type": "integer", "minimum": 1},
            "yield_pct": {"type": ["number", "null"]},
            "cycle_hours": {"type": ["number", "null"]},
        },
        "required": ["period", "week_start", "lots", "yield_pct", "cycle_hours"],
        "additionalProperties": False,
    },
}
PROCESS_PASS_RATE_OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "process_step": {"enum": list(MANUFACTURING_STEPS)},
            "equipment_id": {"type": ["string", "null"]},
            "runs": {"type": "integer", "minimum": 0},
            "passed_runs": {"type": "integer", "minimum": 0},
            "pass_pct": {"type": ["number", "null"]},
        },
        "required": ["process_step", "equipment_id", "runs", "passed_runs", "pass_pct"],
        "additionalProperties": False,
    },
}


def validate_fab_overview_output(value: object) -> object:
    required = {
        "lots",
        "wafers",
        "good_wafers",
        "yield_pct",
        "avg_cycle_hours",
        "avg_hold_hours",
        "held_lots",
        "excursions",
        "start",
        "end",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ProductionReportDataError("fab-overview output has invalid fields")
    for name in ("lots", "excursions"):
        _count(value[name], name)
    if value["held_lots"] is not None:
        _count(value["held_lots"], "held_lots")
    for name in (
        "wafers",
        "good_wafers",
        "yield_pct",
        "avg_cycle_hours",
        "avg_hold_hours",
    ):
        _number(value[name], name, nullable=True)
    for name in ("wafers", "good_wafers"):
        if value[name] is not None:
            _count(value[name], name)
    if value["held_lots"] is not None and value["held_lots"] > value["lots"]:
        raise ProductionReportDataError("invalid held_lots from source")
    if not isinstance(value["start"], str) or not isinstance(value["end"], str):
        raise ProductionReportDataError("invalid overview dates from source")
    try:
        if date.fromisoformat(value["start"]) > date.fromisoformat(value["end"]):
            raise ProductionReportDataError("invalid overview dates from source")
    except ValueError as exc:
        raise ProductionReportDataError("invalid overview dates from source") from exc
    return value


def validate_yield_trend_output(value: object) -> object:
    fields = {"period", "week_start", "lots", "yield_pct", "cycle_hours"}
    if not isinstance(value, list):
        raise ProductionReportDataError("yield-trend output must be a list")
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or not isinstance(row["period"], str)
            or not isinstance(row["week_start"], str)
        ):
            raise ProductionReportDataError("yield-trend output has invalid fields")
        try:
            week_start = date.fromisoformat(row["week_start"])
        except ValueError as exc:
            raise ProductionReportDataError("invalid yield-trend week_start") from exc
        if row["period"] != week_start.strftime("%Y-%W"):
            raise ProductionReportDataError("invalid yield-trend period")
        _count(row["lots"], "lots")
        if row["lots"] == 0:
            raise ProductionReportDataError("invalid yield-trend lots")
        _number(row["yield_pct"], "yield_pct", nullable=True)
        _number(row["cycle_hours"], "cycle_hours", nullable=True)
    return value


def validate_process_pass_rate_output(value: object) -> object:
    fields = {"process_step", "equipment_id", "runs", "passed_runs", "pass_pct"}
    if not isinstance(value, list):
        raise ProductionReportDataError("process-pass-rate output must be a list")
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or row["process_step"] not in MANUFACTURING_STEPS
            or (
                row["equipment_id"] is not None
                and not isinstance(row["equipment_id"], str)
            )
        ):
            raise ProductionReportDataError(
                "process-pass-rate output has invalid fields"
            )
        _count(row["runs"], "runs")
        _count(row["passed_runs"], "passed_runs")
        if row["passed_runs"] > row["runs"]:
            raise ProductionReportDataError("invalid passed_runs from source")
        _number(row["pass_pct"], "pass_pct", nullable=True)
    return value
