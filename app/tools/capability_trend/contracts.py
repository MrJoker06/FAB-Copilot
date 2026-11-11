"""Contracts for the weekly process-capability trend tool."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Protocol

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolScope, ToolSource
from ...agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from app.core.manufacturing_terms import MANUFACTURING_STEPS

TOOL_NAME = "get_capability_trend"
TOOL_VERSION = "1.0.0"
MAX_RANGE_DAYS = 182
_ARGUMENTS = frozenset({"start", "end", "process_step", "equipment_id"})


class CapabilityTrendInputError(ToolInputError):
    """A public capability-trend input validation failure."""


class CapabilityTrendDataError(ToolDataSourceError):
    """A sanitized capability-trend source or source-contract failure."""


class CapabilityTrendTimeoutError(CapabilityTrendDataError, ToolSourceTimeout):
    """A capability-trend source exceeded its execution deadline."""


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CapabilityTrendInputError(f"{name} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class CapabilityTrendInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        for name in _ARGUMENTS:
            _optional_string(getattr(self, name), name)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> CapabilityTrendInput:
        if not isinstance(arguments, Mapping):
            raise CapabilityTrendInputError("arguments must be an object")
        if set(arguments) - _ARGUMENTS:
            raise CapabilityTrendInputError("unknown capability-trend argument")
        if any(arguments[key] is None for key in arguments):
            raise CapabilityTrendInputError("null capability-trend arguments are not allowed")
        return cls(
            **{key: _optional_string(arguments.get(key), key) for key in _ARGUMENTS}
        )

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": "开始日期 YYYY-MM-DD，默认最近90天",
                },
                "end": {
                    "type": "string",
                    "description": "结束日期 YYYY-MM-DD，默认今天",
                },
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "equipment_id": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> CapabilityTrendQuery:
        if isinstance(as_of, datetime) or not isinstance(as_of, date):
            raise CapabilityTrendInputError("as_of must be a date")
        try:
            start = (
                date.fromisoformat(self.start)
                if self.start
                else as_of - timedelta(days=89)
            )
            end = date.fromisoformat(self.end) if self.end else as_of
        except (TypeError, ValueError, OverflowError) as exc:
            raise CapabilityTrendInputError("日期必须使用 YYYY-MM-DD 格式") from exc
        if start > end:
            raise CapabilityTrendInputError("开始日期不能晚于结束日期")
        if (end - start).days > MAX_RANGE_DAYS:
            raise CapabilityTrendInputError(
                f"单次趋势查询范围不能超过 {MAX_RANGE_DAYS} 天"
            )
        process = None
        if self.process_step is not None:
            process = self.process_step.upper()
            if process not in MANUFACTURING_STEPS:
                raise CapabilityTrendInputError(
                    "process_step is not a known manufacturing step"
                )
        equipment = self.equipment_id
        if equipment is not None:
            equipment = equipment.strip()
            if not equipment:
                raise CapabilityTrendInputError("equipment_id must not be blank")
        return CapabilityTrendQuery(start, end, process, equipment)


@dataclass(frozen=True, slots=True)
class CapabilityTrendQuery:
    start: date
    end: date
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.start, datetime)
            or isinstance(self.end, datetime)
            or not isinstance(self.start, date)
            or not isinstance(self.end, date)
        ):
            raise CapabilityTrendInputError("query dates must be dates")
        if self.start > self.end or (self.end - self.start).days > MAX_RANGE_DAYS:
            raise CapabilityTrendInputError("invalid capability-trend date range")
        if self.end == date.max:
            raise CapabilityTrendInputError("end date cannot be represented")
        if self.process_step is not None and self.process_step not in MANUFACTURING_STEPS:
            raise CapabilityTrendInputError("invalid process_step")
        if self.equipment_id is not None and (
            not isinstance(self.equipment_id, str) or not self.equipment_id.strip()
        ):
            raise CapabilityTrendInputError("invalid equipment_id")

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)

    def to_input(self) -> CapabilityTrendInput:
        return CapabilityTrendInput(
            self.start.isoformat(),
            self.end.isoformat(),
            self.process_step,
            self.equipment_id,
        )


@dataclass(frozen=True, slots=True)
class CapabilityTrendSnapshot:
    query: CapabilityTrendQuery
    rows: tuple[dict[str, object], ...]
    source: ToolSource

    def __post_init__(self) -> None:
        if not isinstance(self.query, CapabilityTrendQuery):
            raise CapabilityTrendDataError("invalid snapshot query")
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, dict) for row in self.rows
        ):
            raise CapabilityTrendDataError("invalid snapshot rows")
        if not isinstance(self.source, ToolSource):
            raise CapabilityTrendDataError("invalid snapshot source")


class CapabilityTrendPort(Protocol):
    def fetch(
        self, query: CapabilityTrendQuery, principal: ToolPrincipal
    ) -> CapabilityTrendSnapshot: ...


def capability_trend_scope(
    query: CapabilityTrendQuery, principal: ToolPrincipal
) -> ToolScope:
    if not isinstance(query, CapabilityTrendQuery):
        raise CapabilityTrendDataError("invalid capability-trend query")
    return ToolScope(
        principal.tenant_id,
        query.start,
        query.end,
        (query.equipment_id,) if query.equipment_id else (),
        (query.process_step,) if query.process_step else (),
        grain="equipment_week",
    )


_NULLABLE_NUMBER = {"type": ["number", "null"]}
OUTPUT_FIELDS = (
    "week_start",
    "period_start",
    "period_end",
    "process_step",
    "equipment_id",
    "samples",
    "mean_value",
    "sigma",
    "cpk",
    "metric_name",
    "metric_unit",
    "spec_lsl",
    "spec_usl",
)
OUTPUT_SCHEMA: dict[str, object] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "week_start": {
                "type": "string",
                "format": "date",
                "description": "ISO 周一日期",
            },
            "period_start": {
                "type": "string",
                "format": "date",
                "description": "本周在查询范围内的首日",
            },
            "period_end": {
                "type": "string",
                "format": "date",
                "description": "本周在查询范围内的末日",
            },
            "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
            "equipment_id": {"type": "string", "minLength": 1},
            "samples": {"type": "integer", "minimum": 1},
            "mean_value": {"type": "number"},
            "sigma": {"type": ["number", "null"], "minimum": 0},
            "cpk": _NULLABLE_NUMBER,
            "metric_name": {"type": ["string", "null"]},
            "metric_unit": {"type": ["string", "null"]},
            "spec_lsl": _NULLABLE_NUMBER,
            "spec_usl": _NULLABLE_NUMBER,
        },
        "required": list(OUTPUT_FIELDS),
        "additionalProperties": False,
    },
}


def _number(value: object, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise CapabilityTrendDataError(f"invalid {name} from source")


def _iso_date(value: object, name: str) -> date:
    try:
        if not isinstance(value, str):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise CapabilityTrendDataError(f"invalid {name} from source") from None


def validate_capability_trend_output(value: object) -> object:
    if not isinstance(value, list):
        raise CapabilityTrendDataError("capability-trend output must be a list")
    seen: set[tuple[object, ...]] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != set(OUTPUT_FIELDS):
            raise CapabilityTrendDataError("capability-trend output has invalid fields")
        week = _iso_date(row["week_start"], "week_start")
        first = _iso_date(row["period_start"], "period_start")
        last = _iso_date(row["period_end"], "period_end")
        if (
            week.weekday() != 0
            or not week <= first <= last <= week + timedelta(days=6)
        ):
            raise CapabilityTrendDataError("invalid week period from source")
        process = row["process_step"]
        if not isinstance(process, str) or process not in MANUFACTURING_STEPS:
            raise CapabilityTrendDataError("invalid process_step from source")
        equipment = row["equipment_id"]
        if not isinstance(equipment, str) or not equipment.strip():
            raise CapabilityTrendDataError("invalid equipment_id from source")
        key = (row["week_start"], process, equipment)
        if key in seen:
            raise CapabilityTrendDataError("duplicate week row from source")
        seen.add(key)
        samples = row["samples"]
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise CapabilityTrendDataError("invalid samples from source")
        _number(row["mean_value"], "mean_value")
        for name in ("sigma", "cpk", "spec_lsl", "spec_usl"):
            _number(row[name], name, nullable=True)
        if row["sigma"] is not None and row["sigma"] < 0:
            raise CapabilityTrendDataError("invalid sigma from source")
        for name in ("metric_name", "metric_unit"):
            text = row[name]
            if text is not None and not isinstance(text, str):
                raise CapabilityTrendDataError(f"invalid {name} from source")
    return value


def validate_rows_in_scope(
    query: CapabilityTrendQuery, rows: list[dict[str, object]]
) -> None:
    """Reject rows a source returned outside the requested filters or dates."""
    for row in rows:
        if query.process_step is not None and row.get("process_step") != query.process_step:
            raise CapabilityTrendDataError("source returned row outside requested scope")
        if query.equipment_id is not None and row.get("equipment_id") != query.equipment_id:
            raise CapabilityTrendDataError("source returned row outside requested scope")
        first, last = row.get("period_start"), row.get("period_end")
        if not (
            isinstance(first, str)
            and isinstance(last, str)
            and query.start.isoformat() <= first <= last <= query.end.isoformat()
        ):
            raise CapabilityTrendDataError("source returned row outside requested dates")
