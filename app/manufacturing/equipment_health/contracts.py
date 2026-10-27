"""Pure equipment-health input, port, and output contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Protocol

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource
from ...agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from ..processes import MANUFACTURING_STEPS


class EquipmentHealthInputError(ToolInputError):
    """A public input validation failure before any adapter call."""


class EquipmentHealthDataError(ToolDataSourceError):
    """A sanitized adapter or source-contract failure."""


class EquipmentHealthTimeoutError(EquipmentHealthDataError, ToolSourceTimeout):
    """The local equipment-health source exceeded its execution deadline."""


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EquipmentHealthInputError(f"{name} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class EquipmentHealthInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step", "equipment_id"):
            _optional_string(getattr(self, name), name)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> EquipmentHealthInput:
        if not isinstance(arguments, Mapping):
            raise EquipmentHealthInputError("arguments must be an object")
        allowed = {"start", "end", "process_step", "equipment_id"}
        unknown = set(arguments) - allowed
        if unknown:
            raise EquipmentHealthInputError("unknown equipment-health argument")
        values = {key: _optional_string(arguments.get(key), key) for key in allowed}
        if any(arguments.get(key) is None and key in arguments for key in allowed):
            raise EquipmentHealthInputError(
                "null equipment-health arguments are not allowed"
            )
        return cls(**values)

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

    def resolve(self, as_of: date) -> EquipmentHealthQuery:
        if not isinstance(as_of, date):
            raise EquipmentHealthInputError("as_of must be a date")
        try:
            start = (
                date.fromisoformat(self.start)
                if self.start
                else as_of - timedelta(days=89)
            )
            end = date.fromisoformat(self.end) if self.end else as_of
        except (TypeError, ValueError, OverflowError) as exc:
            raise EquipmentHealthInputError("日期必须使用 YYYY-MM-DD 格式") from exc
        if start > end:
            raise EquipmentHealthInputError("开始日期不能晚于结束日期")
        if (end - start).days > 730:
            raise EquipmentHealthInputError("单次查询范围不能超过 730 天")
        if end == date.max:
            raise EquipmentHealthInputError("end date cannot be represented")
        process = self.process_step.upper() if self.process_step else None
        equipment = self.equipment_id.upper() if self.equipment_id else None
        if process is not None and process not in MANUFACTURING_STEPS:
            raise EquipmentHealthInputError(
                "process_step is not a known manufacturing step"
            )
        if equipment is not None and not equipment.strip():
            raise EquipmentHealthInputError("equipment_id must not be blank")
        return EquipmentHealthQuery(
            start, end, None if equipment else process, equipment
        )


@dataclass(frozen=True, slots=True)
class EquipmentHealthQuery:
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
            raise EquipmentHealthInputError("query dates must be dates")
        if self.start > self.end or (self.end - self.start).days > 730:
            raise EquipmentHealthInputError("invalid equipment-health date range")
        if self.end == date.max:
            raise EquipmentHealthInputError("end date cannot be represented")
        if (
            self.process_step is not None
            and self.process_step not in MANUFACTURING_STEPS
        ):
            raise EquipmentHealthInputError("invalid process_step")
        if self.equipment_id is not None and (
            not isinstance(self.equipment_id, str)
            or not self.equipment_id.strip()
            or self.equipment_id != self.equipment_id.upper()
        ):
            raise EquipmentHealthInputError("invalid equipment_id")
        if self.process_step is not None and self.equipment_id is not None:
            raise EquipmentHealthInputError(
                "query cannot combine process_step and equipment_id"
            )

    @property
    def end_exclusive(self) -> date:
        try:
            return self.end + timedelta(days=1)
        except OverflowError as exc:
            raise EquipmentHealthInputError("end date cannot be represented") from exc


@dataclass(frozen=True, slots=True)
class EquipmentHealthAggregate:
    equipment_id: str
    runs: int
    excursions: int
    avg_defect_density: float
    pass_pct: float
    events: int
    downtime_minutes: float

    def __post_init__(self) -> None:
        if not isinstance(self.equipment_id, str) or not self.equipment_id.strip():
            raise EquipmentHealthDataError("invalid equipment identifier from source")
        for name in ("runs", "excursions", "events"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EquipmentHealthDataError("invalid count from source")
        for name in ("avg_defect_density", "pass_pct", "downtime_minutes"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise EquipmentHealthDataError("invalid metric from source")
        if self.pass_pct > 100 or self.excursions > self.runs:
            raise EquipmentHealthDataError("inconsistent source metrics")


@dataclass(frozen=True, slots=True)
class EquipmentHealthSnapshot:
    query: EquipmentHealthQuery
    rows: tuple[EquipmentHealthAggregate, ...]
    source: ToolSource

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, EquipmentHealthAggregate) for row in self.rows
        ):
            raise EquipmentHealthDataError("invalid snapshot rows")


class EquipmentHealthPort(Protocol):
    def fetch(
        self, query: EquipmentHealthQuery, principal: ToolPrincipal
    ) -> EquipmentHealthSnapshot: ...


def validate_equipment_health_output(value: object) -> object:
    required = {
        "equipment_id",
        "runs",
        "excursions",
        "avg_defect_density",
        "pass_pct",
        "events",
        "downtime_minutes",
        "health",
    }
    if not isinstance(value, list):
        raise EquipmentHealthDataError("equipment-health output must be a list")
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != required
            or row["health"] not in {"Critical", "Watch", "Healthy"}
        ):
            raise EquipmentHealthDataError("equipment-health output has invalid fields")
        EquipmentHealthAggregate(**{key: row[key] for key in required - {"health"}})
    return value
