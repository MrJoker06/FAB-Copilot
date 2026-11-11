"""Consumer-owned contracts for fixed operational manufacturing reports."""

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


class OperationalReportInputError(ToolInputError):
    """Public validation failure before the report source is contacted."""


class OperationalReportDataError(ToolDataSourceError):
    """Sanitized source or source-contract failure."""


class OperationalReportTimeoutError(OperationalReportDataError, ToolSourceTimeout):
    """A fixed operational report exceeded its local source deadline."""


_DATE_PROPERTIES = {
    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，默认最近90天"},
    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
}


def _dates_schema() -> dict[str, object]:
    return {name: dict(value) for name, value in _DATE_PROPERTIES.items()}


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OperationalReportInputError(f"{name} must be a string")
    return value


def _input_values(
    arguments: Mapping[str, object], allowed: set[str]
) -> dict[str, object | None]:
    if not isinstance(arguments, Mapping):
        raise OperationalReportInputError("arguments must be an object")
    if set(arguments) - allowed:
        raise OperationalReportInputError("unknown operational-report argument")
    values: dict[str, object | None] = {}
    for name in allowed:
        value = arguments.get(name)
        if name in arguments and value is None:
            raise OperationalReportInputError(
                "null operational-report arguments are not allowed"
            )
        values[name] = value
    return values


def _dates(start: str | None, end: str | None, as_of: date) -> tuple[date, date]:
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise OperationalReportInputError("as_of must be a date")
    try:
        first = date.fromisoformat(start) if start else as_of - timedelta(days=89)
        last = date.fromisoformat(end) if end else as_of
    except (TypeError, ValueError, OverflowError) as exc:
        raise OperationalReportInputError("日期必须使用 YYYY-MM-DD 格式") from exc
    if first > last:
        raise OperationalReportInputError("开始日期不能晚于结束日期")
    if (last - first).days > 730:
        raise OperationalReportInputError("单次查询范围不能超过 730 天")
    if last == date.max:
        raise OperationalReportInputError("end date cannot be represented")
    return first, last


def _process(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise OperationalReportInputError("process_step must not be blank")
    result = value.upper()
    if result not in MANUFACTURING_STEPS:
        raise OperationalReportInputError(
            "process_step is not a known manufacturing step"
        )
    return result


def _equipment(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise OperationalReportInputError("equipment_id must not be blank")
    return value.upper()


def _limit(value: object, name: str, upper: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
        raise OperationalReportInputError(
            f"{name} must be an integer from 1 to {upper}"
        )
    return value


@dataclass(frozen=True, slots=True)
class EquipmentProductivityInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step", "equipment_id"):
            _optional_text(getattr(self, name), name)

    @classmethod
    def from_arguments(
        cls, arguments: Mapping[str, object]
    ) -> EquipmentProductivityInput:
        values = _input_values(
            arguments, {"start", "end", "process_step", "equipment_id"}
        )
        return cls(**{name: _optional_text(values[name], name) for name in values})

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                **_dates_schema(),
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "equipment_id": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> OperationalReportQuery:
        start, end = _dates(self.start, self.end, as_of)
        process = _process(self.process_step)
        equipment = _equipment(self.equipment_id)
        return OperationalReportQuery(
            "productivity",
            start,
            end,
            None if equipment else process,
            equipment,
        )


@dataclass(frozen=True, slots=True)
class DefectParetoInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    limit: int = 10

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step"):
            _optional_text(getattr(self, name), name)
        if self.limit is None:
            raise OperationalReportInputError("limit must be an integer from 1 to 25")
        _limit(self.limit, "limit", 25, 10)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> DefectParetoInput:
        values = _input_values(arguments, {"start", "end", "process_step", "limit"})
        return cls(
            _optional_text(values["start"], "start"),
            _optional_text(values["end"], "end"),
            _optional_text(values["process_step"], "process_step"),
            _limit(values["limit"], "limit", 25, 10),
        )

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                **_dates_schema(),
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> OperationalReportQuery:
        start, end = _dates(self.start, self.end, as_of)
        return OperationalReportQuery(
            "defects", start, end, _process(self.process_step), limit=self.limit
        )


@dataclass(frozen=True, slots=True)
class RecentExcursionsInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step", "equipment_id"):
            _optional_text(getattr(self, name), name)
        if self.limit is None:
            raise OperationalReportInputError("limit must be an integer from 1 to 100")
        _limit(self.limit, "limit", 100, 20)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> RecentExcursionsInput:
        values = _input_values(
            arguments, {"start", "end", "process_step", "equipment_id", "limit"}
        )
        return cls(
            _optional_text(values["start"], "start"),
            _optional_text(values["end"], "end"),
            _optional_text(values["process_step"], "process_step"),
            _optional_text(values["equipment_id"], "equipment_id"),
            _limit(values["limit"], "limit", 100, 20),
        )

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                **_dates_schema(),
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "equipment_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> OperationalReportQuery:
        start, end = _dates(self.start, self.end, as_of)
        return OperationalReportQuery(
            "excursions",
            start,
            end,
            _process(self.process_step),
            _equipment(self.equipment_id),
            self.limit,
        )


@dataclass(frozen=True, slots=True)
class OperationalReportQuery:
    kind: Literal["productivity", "defects", "excursions"]
    start: date
    end: date
    process_step: str | None = None
    equipment_id: str | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"productivity", "defects", "excursions"}:
            raise OperationalReportInputError("invalid operational-report query kind")
        if (
            isinstance(self.start, datetime)
            or isinstance(self.end, datetime)
            or not isinstance(self.start, date)
            or not isinstance(self.end, date)
            or self.start > self.end
            or (self.end - self.start).days > 730
            or self.end == date.max
        ):
            raise OperationalReportInputError("invalid operational-report date range")
        if (
            self.process_step is not None
            and self.process_step not in MANUFACTURING_STEPS
        ):
            raise OperationalReportInputError("invalid process_step")
        if self.equipment_id is not None and (
            not isinstance(self.equipment_id, str)
            or not self.equipment_id.strip()
            or self.equipment_id != self.equipment_id.upper()
        ):
            raise OperationalReportInputError("invalid equipment_id")
        if self.kind == "productivity":
            if self.limit is not None or (self.process_step and self.equipment_id):
                raise OperationalReportInputError("invalid productivity query filters")
        elif self.kind == "defects":
            if (
                self.equipment_id is not None
                or isinstance(self.limit, bool)
                or not isinstance(self.limit, int)
                or not 1 <= self.limit <= 25
            ):
                raise OperationalReportInputError("invalid defect query filters")
        elif (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 100
        ):
            raise OperationalReportInputError("invalid excursion query filters")

    @property
    def end_exclusive(self) -> date:
        try:
            return self.end + timedelta(days=1)
        except OverflowError as exc:
            raise OperationalReportInputError("end date cannot be represented") from exc


@dataclass(frozen=True, slots=True)
class OperationalReportSnapshot:
    query: OperationalReportQuery
    rows: tuple[dict[str, object], ...]
    source: ToolSource

    def __post_init__(self) -> None:
        if not isinstance(self.query, OperationalReportQuery) or not isinstance(
            self.source, ToolSource
        ):
            raise OperationalReportDataError("invalid operational-report snapshot")
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, dict) for row in self.rows
        ):
            raise OperationalReportDataError("invalid operational-report rows")


class OperationalReportsPort(Protocol):
    def fetch(
        self, query: OperationalReportQuery, principal: ToolPrincipal
    ) -> OperationalReportSnapshot: ...


def operational_report_scope(
    query: OperationalReportQuery, principal: ToolPrincipal
) -> ToolScope:
    return ToolScope(
        principal.tenant_id,
        query.start,
        query.end,
        (query.equipment_id,) if query.equipment_id else (),
        (query.process_step,) if query.process_step else (),
        grain={
            "productivity": "equipment_productivity",
            "defects": "defect_type",
            "excursions": "process_run",
        }[query.kind],
    )


def _count(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OperationalReportDataError(f"invalid {name} from source")


def _number(
    value: object, name: str, *, nullable: bool = False, nonnegative: bool = False
) -> None:
    if value is None and nullable:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise OperationalReportDataError(f"invalid {name} from source")
    if nonnegative and value < 0:
        raise OperationalReportDataError(f"invalid {name} from source")


_OUTPUT_PROPERTIES = {
    "productivity": {
        "equipment_id": {"type": "string", "minLength": 1},
        **{name: {"type": "number", "minimum": 0} for name in ("recorded_minutes", "productive_minutes", "unscheduled_down_minutes", "scheduled_down_minutes")},
        "productive_pct": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
    },
    "defects": {
        "defect_type": {"type": "string", "minLength": 1},
        "process_steps": {"type": "string", "minLength": 1},
        "defect_count": {"type": "integer", "minimum": 0},
        "affected_lots": {"type": "integer", "minimum": 0},
        "share_pct": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
    },
    "excursions": {
        **{name: {"type": "string"} for name in ("run_time", "lot_id", "equipment_id", "excursion_code", "measurement_name", "measurement_unit")},
        "process_step": {"enum": list(MANUFACTURING_STEPS)},
        **{name: {"type": ["number", "null"]} for name in ("thickness_nm", "uniformity_pct", "defect_density", "measurement_value", "spec_lsl", "spec_usl")},
    },
}
OPERATIONAL_OUTPUT_SCHEMAS = {
    kind: {
        "type": "array",
        "items": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
    }
    for kind, properties in _OUTPUT_PROPERTIES.items()
}


def validate_equipment_productivity_output(value: object) -> object:
    fields = {
        "equipment_id",
        "recorded_minutes",
        "productive_minutes",
        "productive_pct",
        "unscheduled_down_minutes",
        "scheduled_down_minutes",
    }
    if not isinstance(value, list):
        raise OperationalReportDataError("equipment-productivity output must be a list")
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or not isinstance(row["equipment_id"], str)
            or not row["equipment_id"].strip()
        ):
            raise OperationalReportDataError(
                "equipment-productivity output has invalid fields"
            )
        for name in (
            "recorded_minutes",
            "productive_minutes",
            "unscheduled_down_minutes",
            "scheduled_down_minutes",
        ):
            _number(row[name], name, nonnegative=True)
        _number(
            row["productive_pct"], "productive_pct", nullable=True, nonnegative=True
        )
        if row["productive_pct"] is not None and row["productive_pct"] > 100:
            raise OperationalReportDataError("invalid productive_pct from source")
    return value


def validate_defect_pareto_output(value: object) -> object:
    fields = {
        "defect_type",
        "process_steps",
        "defect_count",
        "affected_lots",
        "share_pct",
    }
    if not isinstance(value, list):
        raise OperationalReportDataError("defect-pareto output must be a list")
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or not isinstance(row["defect_type"], str)
            or not row["defect_type"].strip()
            or not isinstance(row["process_steps"], str)
        ):
            raise OperationalReportDataError("defect-pareto output has invalid fields")
        if not row["process_steps"] or any(
            item not in MANUFACTURING_STEPS for item in row["process_steps"].split(",")
        ):
            raise OperationalReportDataError("invalid process_steps from source")
        _count(row["defect_count"], "defect_count")
        _count(row["affected_lots"], "affected_lots")
        _number(row["share_pct"], "share_pct", nullable=True, nonnegative=True)
        if row["share_pct"] is not None and row["share_pct"] > 100:
            raise OperationalReportDataError("invalid share_pct from source")
    return value


def validate_recent_excursions_output(value: object) -> object:
    fields = {
        "run_time",
        "lot_id",
        "process_step",
        "equipment_id",
        "excursion_code",
        "thickness_nm",
        "uniformity_pct",
        "defect_density",
        "measurement_name",
        "measurement_value",
        "measurement_unit",
        "spec_lsl",
        "spec_usl",
    }
    if not isinstance(value, list):
        raise OperationalReportDataError("recent-excursions output must be a list")
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or not isinstance(row["run_time"], str)
            or not isinstance(row["lot_id"], str)
            or not row["lot_id"].strip()
            or row["process_step"] not in MANUFACTURING_STEPS
            or not isinstance(row["equipment_id"], str)
            or not row["equipment_id"].strip()
            or not isinstance(row["excursion_code"], str)
            or not isinstance(row["measurement_name"], str)
            or not isinstance(row["measurement_unit"], str)
        ):
            raise OperationalReportDataError(
                "recent-excursions output has invalid fields"
            )
        for name in (
            "thickness_nm",
            "uniformity_pct",
            "defect_density",
            "measurement_value",
            "spec_lsl",
            "spec_usl",
        ):
            _number(row[name], name, nullable=True)
    return value
