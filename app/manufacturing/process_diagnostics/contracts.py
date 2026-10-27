"""Consumer-owned contracts for process capability and sensor diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from typing import Literal, Protocol

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolScope, ToolSource
from ...agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
    ToolSourceTimeout,
)
from ..processes import MANUFACTURING_STEPS


class DiagnosticsInputError(ToolInputError):
    """A public diagnostics input validation failure."""


class DiagnosticsDataError(ToolDataSourceError):
    """A sanitized diagnostics adapter or source-contract failure."""


class DiagnosticsTimeoutError(DiagnosticsDataError, ToolSourceTimeout):
    """A diagnostics source exceeded its execution deadline."""


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DiagnosticsInputError(f"{name} must be a string")
    return value


def _input_values(
    arguments: Mapping[str, object], allowed: set[str]
) -> dict[str, str | None]:
    if not isinstance(arguments, Mapping):
        raise DiagnosticsInputError("arguments must be an object")
    if set(arguments) - allowed:
        raise DiagnosticsInputError("unknown diagnostics argument")
    if any(key in arguments and arguments[key] is None for key in allowed):
        raise DiagnosticsInputError("null diagnostics arguments are not allowed")
    return {key: _optional_string(arguments.get(key), key) for key in allowed}


def _resolve_dates(
    start_value: str | None, end_value: str | None, as_of: date
) -> tuple[date, date]:
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise DiagnosticsInputError("as_of must be a date")
    try:
        start = (
            date.fromisoformat(start_value)
            if start_value
            else as_of - timedelta(days=89)
        )
        end = date.fromisoformat(end_value) if end_value else as_of
    except (TypeError, ValueError, OverflowError) as exc:
        raise DiagnosticsInputError("日期必须使用 YYYY-MM-DD 格式") from exc
    if start > end:
        raise DiagnosticsInputError("开始日期不能晚于结束日期")
    if (end - start).days > 730:
        raise DiagnosticsInputError("单次查询范围不能超过 730 天")
    if end == date.max:
        raise DiagnosticsInputError("end date cannot be represented")
    return start, end


def _resolve_process(process_step: str | None) -> str | None:
    if process_step is None:
        return None
    process = process_step.upper()
    if process not in MANUFACTURING_STEPS:
        raise DiagnosticsInputError("process_step is not a known manufacturing step")
    return process


@dataclass(frozen=True, slots=True)
class ProcessCapabilityInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step"):
            _optional_string(getattr(self, name), name)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ProcessCapabilityInput:
        return cls(**_input_values(arguments, {"start", "end", "process_step"}))

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
            },
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> DiagnosticsQuery:
        start, end = _resolve_dates(self.start, self.end, as_of)
        return DiagnosticsQuery(
            "capability", start, end, _resolve_process(self.process_step)
        )


@dataclass(frozen=True, slots=True)
class SensorSummaryInput:
    start: str | None = None
    end: str | None = None
    process_step: str | None = None
    equipment_id: str | None = None
    signal_name: str | None = None

    def __post_init__(self) -> None:
        for name in ("start", "end", "process_step", "equipment_id", "signal_name"):
            _optional_string(getattr(self, name), name)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> SensorSummaryInput:
        return cls(
            **_input_values(
                arguments,
                {"start", "end", "process_step", "equipment_id", "signal_name"},
            )
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
                "signal_name": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def resolve(self, as_of: date) -> DiagnosticsQuery:
        start, end = _resolve_dates(self.start, self.end, as_of)
        equipment, signal = self.equipment_id, self.signal_name
        if equipment is not None and not equipment.strip():
            raise DiagnosticsInputError("equipment_id must not be blank")
        if signal is not None and not signal.strip():
            raise DiagnosticsInputError("signal_name must not be blank")
        return DiagnosticsQuery(
            "sensors",
            start,
            end,
            _resolve_process(self.process_step),
            equipment,
            signal,
        )


@dataclass(frozen=True, slots=True)
class DiagnosticsQuery:
    kind: Literal["capability", "sensors"]
    start: date
    end: date
    process_step: str | None = None
    equipment_id: str | None = None
    signal_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"capability", "sensors"}:
            raise DiagnosticsInputError("invalid diagnostics query kind")
        if (
            isinstance(self.start, datetime)
            or isinstance(self.end, datetime)
            or not isinstance(self.start, date)
            or not isinstance(self.end, date)
        ):
            raise DiagnosticsInputError("query dates must be dates")
        if self.start > self.end or (self.end - self.start).days > 730:
            raise DiagnosticsInputError("invalid diagnostics date range")
        if self.end == date.max:
            raise DiagnosticsInputError("end date cannot be represented")
        if (
            self.process_step is not None
            and self.process_step not in MANUFACTURING_STEPS
        ):
            raise DiagnosticsInputError("invalid process_step")
        for name in ("equipment_id", "signal_name"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise DiagnosticsInputError(f"invalid {name}")
        if self.kind == "capability" and (
            self.equipment_id is not None or self.signal_name is not None
        ):
            raise DiagnosticsInputError(
                "capability query cannot filter equipment or signal"
            )

    @property
    def end_exclusive(self) -> date:
        try:
            return self.end + timedelta(days=1)
        except OverflowError as exc:
            raise DiagnosticsInputError("end date cannot be represented") from exc


@dataclass(frozen=True, slots=True)
class DiagnosticsSnapshot:
    query: DiagnosticsQuery
    rows: tuple[dict[str, object], ...]
    source: ToolSource

    def __post_init__(self) -> None:
        if not isinstance(self.query, DiagnosticsQuery):
            raise DiagnosticsDataError("invalid snapshot query")
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, dict) for row in self.rows
        ):
            raise DiagnosticsDataError("invalid snapshot rows")
        if not isinstance(self.source, ToolSource):
            raise DiagnosticsDataError("invalid snapshot source")


class ProcessDiagnosticsPort(Protocol):
    def fetch(
        self, query: DiagnosticsQuery, principal: ToolPrincipal
    ) -> DiagnosticsSnapshot: ...


def diagnostics_scope(query: DiagnosticsQuery, principal: ToolPrincipal) -> ToolScope:
    if not isinstance(query, DiagnosticsQuery):
        raise DiagnosticsDataError("invalid diagnostics query")
    return ToolScope(
        principal.tenant_id,
        query.start,
        query.end,
        (query.equipment_id,) if query.equipment_id else (),
        (query.process_step,) if query.process_step else (),
        grain="equipment_distribution"
        if query.kind == "capability"
        else "equipment_signal",
    )


def _finite_number(value: object, name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise DiagnosticsDataError(f"invalid {name} from source")


def _optional_text(value: object, name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DiagnosticsDataError(f"invalid {name} from source")


_CAPABILITY_FIELDS = {
    "process_step",
    "equipment_id",
    "samples",
    "mean_value",
    "sigma",
    "min_value",
    "max_value",
    "cpk",
    "metric_name",
    "metric_unit",
    "spec_lsl",
    "spec_usl",
}
_SENSOR_FIELDS = {
    "process_step",
    "equipment_id",
    "signal_name",
    "signal_unit",
    "samples",
    "missing_samples",
    "flagged_outliers",
    "mean_value",
    "min_value",
    "max_value",
}


def _required_step_and_equipment(row: dict[str, object]) -> None:
    process_step = row["process_step"]
    if not isinstance(process_step, str) or process_step not in MANUFACTURING_STEPS:
        raise DiagnosticsDataError("invalid process_step from source")
    if not isinstance(row["equipment_id"], str) or not row["equipment_id"].strip():
        raise DiagnosticsDataError("invalid equipment_id from source")


def validate_process_capability_output(value: object) -> object:
    if not isinstance(value, list):
        raise DiagnosticsDataError("process-capability output must be a list")
    for row in value:
        if not isinstance(row, dict) or set(row) != _CAPABILITY_FIELDS:
            raise DiagnosticsDataError("process-capability output has invalid fields")
        _required_step_and_equipment(row)
        samples = row["samples"]
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise DiagnosticsDataError("invalid samples from source")
        for name in ("mean_value", "min_value", "max_value"):
            _finite_number(row[name], name)
        for name in ("sigma", "cpk", "spec_lsl", "spec_usl"):
            _finite_number(row[name], name, nullable=True)
        sigma = row["sigma"]
        if sigma is not None and sigma < 0:
            raise DiagnosticsDataError("invalid sigma from source")
        _optional_text(row["metric_name"], "metric_name")
        _optional_text(row["metric_unit"], "metric_unit")
    return value


def validate_sensor_summary_output(value: object) -> object:
    if not isinstance(value, list):
        raise DiagnosticsDataError("sensor-summary output must be a list")
    for row in value:
        if not isinstance(row, dict) or set(row) != _SENSOR_FIELDS:
            raise DiagnosticsDataError("sensor-summary output has invalid fields")
        _required_step_and_equipment(row)
        if not isinstance(row["signal_name"], str) or not row["signal_name"].strip():
            raise DiagnosticsDataError("invalid signal_name from source")
        _optional_text(row["signal_unit"], "signal_unit")
        samples = row["samples"]
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise DiagnosticsDataError("invalid samples from source")
        for name in ("missing_samples", "flagged_outliers"):
            count = row[name]
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or not 0 <= count <= samples
            ):
                raise DiagnosticsDataError(f"invalid {name} from source")
        statistics = tuple(
            row[name] for name in ("min_value", "mean_value", "max_value")
        )
        if any(value is None for value in statistics):
            if any(value is not None for value in statistics):
                raise DiagnosticsDataError("incomplete sensor statistics from source")
            if row["missing_samples"] != samples:
                raise DiagnosticsDataError(
                    "inconsistent missing sensor statistics from source"
                )
            continue
        for name, statistic in zip(
            ("min_value", "mean_value", "max_value"), statistics, strict=True
        ):
            _finite_number(statistic, name)
        minimum, mean, maximum = statistics
        if not minimum <= mean <= maximum:
            raise DiagnosticsDataError("invalid sensor statistic range from source")
    return value
