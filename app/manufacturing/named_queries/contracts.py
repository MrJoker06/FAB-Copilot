"""Consumer-owned contracts for fixed manufacturing named queries."""

from __future__ import annotations

import re
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
from ..processes import MANUFACTURING_STEPS


class NamedQueryInputError(ToolInputError):
    """The caller supplied invalid named-query arguments."""


class NamedQueryDataError(ToolDataSourceError):
    """The named-query source was unavailable or returned invalid data."""


class NamedQueryTimeoutError(NamedQueryDataError, ToolSourceTimeout):
    """A named-query source exceeded its deadline."""


TOOL_KINDS = {
    "get_product_yield_breakdown": "product_yield",
    "get_equipment_event_timeline": "equipment_events",
    "get_equipment_excursion_history": "equipment_excursions",
    "get_lot_identity": "lot_identity",
    "get_lot_process_history": "lot_process_history",
    "get_lot_excursion_history": "lot_excursions",
    "get_lot_defect_history": "lot_defects",
    "get_lot_wafer_map_patterns": "lot_wafer_maps",
}
_KINDS = frozenset(TOOL_KINDS.values())
_DATED_KINDS = frozenset({"product_yield", "equipment_events", "equipment_excursions"})
_LOT_KINDS = _KINDS - _DATED_KINDS
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(value: object, name: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise NamedQueryInputError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise NamedQueryInputError(f"{name} must be a string")
    value = value.strip()
    if not value:
        raise NamedQueryInputError(f"{name} must not be blank")
    return value


def _arguments(arguments: Mapping[str, object], allowed: set[str]) -> dict[str, object]:
    if not isinstance(arguments, Mapping):
        raise NamedQueryInputError("arguments must be an object")
    if set(arguments) - allowed:
        raise NamedQueryInputError("unknown named-query argument")
    if any(value is None for value in arguments.values()):
        raise NamedQueryInputError("null named-query arguments are not allowed")
    return dict(arguments)


def _resolve_dates(
    start: str | None, end: str | None, as_of: date
) -> tuple[date, date]:
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise NamedQueryInputError("as_of must be a date")
    try:
        first = (
            as_of - timedelta(days=89) if start is None else _parse_date(start, "start")
        )
        last = as_of if end is None else _parse_date(end, "end")
    except OverflowError as exc:
        raise NamedQueryInputError("date range cannot be represented") from exc
    if first > last:
        raise NamedQueryInputError("start must not be after end")
    if (last - first).days > 730:
        raise NamedQueryInputError("date range must not exceed 730 days")
    if last == date.max:
        raise NamedQueryInputError("end date cannot be represented")
    return first, last


def _parse_date(value: object, name: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise NamedQueryInputError(f"{name} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise NamedQueryInputError(f"{name} must use YYYY-MM-DD") from exc


def _process(value: str | None) -> str | None:
    value = _text(value, "process_step")
    if value is None:
        return None
    result = value.upper()
    if result not in MANUFACTURING_STEPS:
        raise NamedQueryInputError("process_step is not a known manufacturing step")
    return result


def _fixed_kind(kind: object, expected: str) -> str:
    if kind != expected:
        raise NamedQueryInputError("invalid named-query kind for input")
    return expected


def _schema(
    properties: dict[str, object], required: list[str] | None = None
) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


class _DatedInput:
    start: str | None
    end: str | None

    def _dates(self, as_of: date) -> tuple[date, date]:
        return _resolve_dates(self.start, self.end, as_of)


@dataclass(frozen=True, slots=True)
class ProductYieldInput(_DatedInput):
    start: str | None = None
    end: str | None = None
    product: str | None = None

    def __post_init__(self) -> None:
        _text(self.start, "start")
        _text(self.end, "end")
        if self.start is not None:
            _parse_date(self.start, "start")
        if self.end is not None:
            _parse_date(self.end, "end")
        object.__setattr__(self, "product", _text(self.product, "product"))

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ProductYieldInput:
        values = _arguments(arguments, {"start", "end", "product"})
        return cls(**values)  # type: ignore[arg-type]

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return _schema(
            {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "product": {"type": "string"},
            }
        )

    def resolve(self, kind: str, as_of: date) -> NamedQuery:
        _fixed_kind(kind, "product_yield")
        start, end = self._dates(as_of)
        return NamedQuery(
            "product_yield", start, end, product=_text(self.product, "product")
        )


@dataclass(frozen=True, slots=True)
class EquipmentEventsInput(_DatedInput):
    start: str | None = None
    end: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.start, "start")
        _text(self.end, "end")
        if self.start is not None:
            _parse_date(self.start, "start")
        if self.end is not None:
            _parse_date(self.end, "end")
        object.__setattr__(
            self, "equipment_id", _text(self.equipment_id, "equipment_id")
        )

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> EquipmentEventsInput:
        return cls(**_arguments(arguments, {"start", "end", "equipment_id"}))  # type: ignore[arg-type]

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return _schema(
            {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "equipment_id": {"type": "string"},
            }
        )

    def resolve(self, kind: str, as_of: date) -> NamedQuery:
        _fixed_kind(kind, "equipment_events")
        start, end = self._dates(as_of)
        return NamedQuery(
            "equipment_events",
            start,
            end,
            equipment_id=_text(self.equipment_id, "equipment_id"),
        )


@dataclass(frozen=True, slots=True)
class EquipmentExcursionsInput(_DatedInput):
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.start, "start")
        _text(self.end, "end")
        if self.start is not None:
            _parse_date(self.start, "start")
        if self.end is not None:
            _parse_date(self.end, "end")
        object.__setattr__(self, "process_step", _process(self.process_step))
        object.__setattr__(
            self, "equipment_id", _text(self.equipment_id, "equipment_id")
        )

    @classmethod
    def from_arguments(
        cls, arguments: Mapping[str, object]
    ) -> EquipmentExcursionsInput:
        return cls(
            **_arguments(arguments, {"start", "end", "process_step", "equipment_id"})
        )  # type: ignore[arg-type]

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return _schema(
            {
                "start": {"type": "string"},
                "end": {"type": "string"},
                "process_step": {"type": "string", "enum": list(MANUFACTURING_STEPS)},
                "equipment_id": {"type": "string"},
            }
        )

    def resolve(self, kind: str, as_of: date) -> NamedQuery:
        _fixed_kind(kind, "equipment_excursions")
        start, end = self._dates(as_of)
        return NamedQuery(
            "equipment_excursions",
            start,
            end,
            process_step=_process(self.process_step),
            equipment_id=_text(self.equipment_id, "equipment_id"),
        )


@dataclass(frozen=True, slots=True)
class LotQueryInput:
    lot_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "lot_id", _text(self.lot_id, "lot_id", required=True))

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> LotQueryInput:
        values = _arguments(arguments, {"lot_id"})
        if "lot_id" not in values:
            raise NamedQueryInputError("lot_id is required")
        return cls(values["lot_id"])  # type: ignore[arg-type]

    @classmethod
    def json_schema(cls) -> dict[str, object]:
        return _schema({"lot_id": {"type": "string"}}, ["lot_id"])

    def resolve(self, kind: str, as_of: date) -> NamedQuery:
        del as_of
        if not isinstance(kind, str) or kind not in _LOT_KINDS:
            raise NamedQueryInputError("invalid named-query kind for input")
        return NamedQuery(kind, lot_id=_text(self.lot_id, "lot_id", required=True))


@dataclass(frozen=True, slots=True)
class NamedQuery:
    kind: str
    start: date | None = None
    end: date | None = None
    product: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None
    lot_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _KINDS:
            raise NamedQueryInputError("invalid named-query kind")
        if self.kind in _DATED_KINDS:
            if any(
                isinstance(item, datetime) or not isinstance(item, date)
                for item in (self.start, self.end)
            ):
                raise NamedQueryInputError("dated query requires date start and end")
            if (
                self.start > self.end
                or (self.end - self.start).days > 730
                or self.end == date.max
            ):  # type: ignore[operator]
                raise NamedQueryInputError("invalid named-query date range")
            if self.lot_id is not None:
                raise NamedQueryInputError("dated query cannot include lot_id")
        elif self.start is not None or self.end is not None:
            raise NamedQueryInputError("lot query cannot include dates")
        for name in ("product", "equipment_id", "lot_id"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise NamedQueryInputError(f"invalid {name}")
        if self.process_step is not None and (
            not isinstance(self.process_step, str)
            or self.process_step not in MANUFACTURING_STEPS
        ):
            raise NamedQueryInputError("invalid process_step")
        expected = {
            "product_yield": {"product"},
            "equipment_events": {"equipment_id"},
            "equipment_excursions": {"process_step", "equipment_id"},
        }.get(self.kind, {"lot_id"})
        actual = {
            name
            for name in ("product", "process_step", "equipment_id", "lot_id")
            if getattr(self, name) is not None
        }
        if not actual <= expected or (self.kind in _LOT_KINDS and self.lot_id is None):
            raise NamedQueryInputError("invalid named-query filters")

    @property
    def end_exclusive(self) -> date:
        if self.end is None:
            raise NamedQueryInputError("lot query has no end date")
        return self.end + timedelta(days=1)


@dataclass(frozen=True, slots=True)
class NamedQuerySnapshot:
    query: NamedQuery
    rows: tuple[dict[str, object], ...]
    source: ToolSource

    def __post_init__(self) -> None:
        if (
            not isinstance(self.query, NamedQuery)
            or not isinstance(self.source, ToolSource)
            or not isinstance(self.rows, tuple)
            or any(not isinstance(row, dict) for row in self.rows)
        ):
            raise NamedQueryDataError("invalid named-query snapshot")


class NamedQueryPort(Protocol):
    def fetch(
        self, query: NamedQuery, principal: ToolPrincipal
    ) -> NamedQuerySnapshot: ...


def named_query_scope(query: NamedQuery, principal: ToolPrincipal) -> ToolScope:
    grains = {
        "product_yield": "product",
        "equipment_events": "event",
        "equipment_excursions": "event",
        "lot_identity": "lot",
        "lot_process_history": "process_run",
        "lot_excursions": "event",
        "lot_defects": "defect_event",
        "lot_wafer_maps": "wafer",
    }
    return ToolScope(
        principal.tenant_id,
        query.start,
        query.end,
        (query.equipment_id,) if query.equipment_id else (),
        (query.process_step,) if query.process_step else (),
        (query.lot_id,) if query.lot_id else (),
        grains[query.kind],
    )


_FIELDS = {
    "product_yield": {"product", "technology_nm", "lots", "wafers", "yield_pct"},
    "equipment_events": {
        "equipment_id",
        "event_time",
        "event_type",
        "duration_minutes",
        "severity",
        "reason",
    },
    "equipment_excursions": {
        "lot_id",
        "run_time",
        "process_step",
        "equipment_id",
        "excursion_code",
        "measurement_name",
        "measurement_value",
        "measurement_unit",
        "spec_lsl",
        "spec_usl",
    },
    "lot_identity": {
        "lot_id",
        "product",
        "technology_nm",
        "route",
        "priority",
        "start_time",
        "complete_time",
        "status",
        "wafer_count",
        "good_wafers",
        "yield_rate",
        "cycle_time_hours",
        "hold_hours",
    },
    "lot_process_history": {
        "lot_id",
        "operation_seq",
        "layer_name",
        "process_step",
        "equipment_id",
        "chamber",
        "recipe",
        "run_time",
        "queue_hours",
        "rework_flag",
    },
    "lot_excursions": {
        "lot_id",
        "operation_seq",
        "run_time",
        "process_step",
        "equipment_id",
        "excursion_code",
        "measurement_name",
        "measurement_value",
        "measurement_unit",
        "spec_lsl",
        "spec_usl",
    },
    "lot_defects": {
        "lot_id",
        "detected_time",
        "process_step",
        "defect_type",
        "count",
        "disposition",
    },
    "lot_wafer_maps": {
        "lot_id",
        "wafer_no",
        "detected_time",
        "process_step",
        "equipment_id",
        "pattern_class",
        "tested_dies",
        "failed_dies",
    },
}


def _number(
    value: object, *, nullable: bool = False, minimum: float | None = None
) -> bool:
    if value is None:
        return nullable
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        return False
    return minimum is None or value >= minimum


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _timestamp(value: object, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str):
        return False
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_named_query_output(kind: str, value: object) -> object:
    if not isinstance(kind, str) or kind not in _FIELDS or not isinstance(value, list):
        raise NamedQueryDataError("invalid named-query output")
    for row in value:
        if not isinstance(row, dict) or set(row) != _FIELDS[kind]:
            raise NamedQueryDataError("named-query output has invalid fields")
        if any(
            not isinstance(item, str)
            for name, item in row.items()
            if name
            not in {
                "technology_nm",
                "lots",
                "wafers",
                "yield_pct",
                "duration_minutes",
                "measurement_value",
                "spec_lsl",
                "spec_usl",
                "wafer_count",
                "good_wafers",
                "yield_rate",
                "cycle_time_hours",
                "hold_hours",
                "operation_seq",
                "queue_hours",
                "rework_flag",
                "count",
                "wafer_no",
                "tested_dies",
                "failed_dies",
                "complete_time",
            }
        ):
            raise NamedQueryDataError("invalid text from source")
        if "technology_nm" in row and not _positive_int(row["technology_nm"]):
            raise NamedQueryDataError("invalid technology_nm from source")
        if "process_step" in row and row["process_step"] not in MANUFACTURING_STEPS:
            raise NamedQueryDataError("invalid process_step from source")
        for name in (
            "duration_minutes",
            "cycle_time_hours",
            "hold_hours",
            "queue_hours",
        ):
            if name in row and not _number(row[name], minimum=0):
                raise NamedQueryDataError("invalid non-negative duration from source")
        for name in ("measurement_value", "spec_lsl", "spec_usl"):
            if name in row and not _number(row[name], nullable=True):
                raise NamedQueryDataError("invalid measurement from source")
        if "yield_pct" in row and not _number(
            row["yield_pct"], nullable=True, minimum=0
        ):
            raise NamedQueryDataError("invalid yield_pct from source")
        if row.get("yield_pct") is not None and row["yield_pct"] > 100:
            raise NamedQueryDataError("invalid yield_pct from source")
        if "yield_rate" in row and (
            not _number(row["yield_rate"], minimum=0) or row["yield_rate"] > 1
        ):
            raise NamedQueryDataError("invalid yield_rate from source")
        for name in ("wafers", "good_wafers", "count", "tested_dies", "failed_dies"):
            if name in row and not _nonnegative_int(row[name]):
                raise NamedQueryDataError("invalid count from source")
        if "lots" in row and not _positive_int(row["lots"]):
            raise NamedQueryDataError("invalid lots from source")
        if "wafer_count" in row and not _positive_int(row["wafer_count"]):
            raise NamedQueryDataError("invalid wafer_count from source")
        for name in ("operation_seq", "wafer_no"):
            if name in row and not _positive_int(row[name]):
                raise NamedQueryDataError("invalid sequence from source")
        if "good_wafers" in row and row["good_wafers"] > row["wafer_count"]:
            raise NamedQueryDataError("invalid good_wafers from source")
        if "failed_dies" in row and row["failed_dies"] > row["tested_dies"]:
            raise NamedQueryDataError("invalid failed_dies from source")
        if "rework_flag" in row and not (
            isinstance(row["rework_flag"], bool)
            or (isinstance(row["rework_flag"], int) and row["rework_flag"] in {0, 1})
        ):
            raise NamedQueryDataError("invalid rework_flag from source")
        for name in (
            "event_time",
            "run_time",
            "start_time",
            "complete_time",
            "detected_time",
        ):
            if name in row and not _timestamp(
                row[name], nullable=name == "complete_time"
            ):
                raise NamedQueryDataError("invalid timestamp from source")
    return value
