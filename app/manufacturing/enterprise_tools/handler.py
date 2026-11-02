"""Pure enterprise-data handlers."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from ...agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolSourceKind,
    ToolStatus,
)
from .contracts import (
    EnterpriseDataError,
    EnterpriseDataPort,
    EnterpriseManifestInput,
    EnterpriseQuery,
    EnterpriseSampleInput,
    EnterpriseSnapshot,
    EnterpriseSummaryInput,
    EnterpriseWindow,
    enterprise_scope,
    validate_enterprise_manifest_output,
    validate_enterprise_sample_output,
    validate_enterprise_summary_output,
)

InputT = TypeVar(
    "InputT", EnterpriseManifestInput, EnterpriseSummaryInput, EnterpriseSampleInput
)
Validator = Callable[[object], object]


@dataclass(frozen=True, slots=True)
class EnterpriseToolsDependencies:
    port: EnterpriseDataPort
    window: EnterpriseWindow


def _failure() -> EnterpriseDataError:
    return EnterpriseDataError("enterprise-data source returned invalid data")


def _validate_summary(data: dict[str, object], query: EnterpriseQuery) -> None:
    payload = data["query"]
    lineage = data["lineage"]
    equipment = data["equipment"]
    if (
        not isinstance(payload, dict)
        or not isinstance(lineage, dict)
        or not isinstance(equipment, list)
    ):
        raise _failure()
    if (
        payload["filters"] != query.filter_dict()
        or payload["effective_start"] != query.effective_start.isoformat()
        or payload["effective_end"] != query.effective_end.isoformat()
        or not isinstance(lineage["as_of"], str)
        or lineage["as_of"][:10] != query.as_of.isoformat()
        or lineage["source"] != data["provider"]
    ):
        raise _failure()
    equipment_id = query.filter_dict().get("equipment_id")
    if equipment_id is not None and any(
        row["equipment_id"] != equipment_id for row in equipment
    ):
        raise _failure()
    if data["simulated"] is True:
        aggregation = data["aggregation"]
        if (
            not isinstance(aggregation, dict)
            or aggregation["semantics"] != "deterministic_projection"
            or aggregation["exact"] is not False
            or lineage["classification"] != "synthetic_non_production"
        ):
            raise _failure()


def _validate_sample(data: dict[str, object], query: EnterpriseQuery) -> None:
    if (
        data["entity"] != query.entity
        or data["filters"] != query.filter_dict()
        or not isinstance(data["page"], dict)
        or data["page"]["limit"] != query.limit
        or not isinstance(data["records"], list)
    ):
        raise _failure()
    timestamp_key = {
        "lots": "start_time",
        "process-runs": "run_time",
        "sensor-events": "sample_time",
    }[query.entity]
    for row in data["records"]:
        if not isinstance(row, dict) or row["synthetic"] != data["simulated"]:
            raise _failure()
        try:
            recorded = datetime.fromisoformat(row[timestamp_key]).date()
        except (TypeError, ValueError) as exc:
            raise _failure() from exc
        if not query.effective_start <= recorded <= query.effective_end:
            raise _failure()
        for key, value in query.filter_dict().items():
            if key not in {"start", "end"} and row.get(key) != value:
                raise _failure()


def _result(
    name: str,
    input_value: InputT,
    context: ToolExecutionContext[EnterpriseToolsDependencies],
    validator: Validator,
) -> ToolResult[object]:
    query = input_value.resolve(context.dependencies.window)
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except EnterpriseDataError:
        raise
    except Exception as exc:
        raise EnterpriseDataError("enterprise-data source is unavailable") from exc
    if (
        not isinstance(snapshot, EnterpriseSnapshot)
        or snapshot.query != query
        or snapshot.source.scope != enterprise_scope(query, context.principal)
    ):
        raise _failure()
    try:
        data = deepcopy(snapshot.data)
        validator(data)
        if data["tenant_id"] != context.principal.tenant_id:
            raise _failure()
        if (
            snapshot.source.source_kind is ToolSourceKind.FAKE
            and data["simulated"] is not True
        ):
            raise _failure()
        if query.kind == "manifest":
            if data["retention_days"] != context.dependencies.window.retention_days:
                raise _failure()
            if (
                data["simulated"] is True
                and data["data_classification"] != "synthetic_non_production"
            ):
                raise _failure()
        elif query.kind == "summary":
            _validate_summary(data, query)
        else:
            _validate_sample(data, query)
    except EnterpriseDataError:
        raise
    except Exception as exc:
        raise _failure() from exc
    return ToolResult(
        context.call_id,
        name,
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=data,
        sources=(snapshot.source,),
        row_count=1,
    )


def enterprise_manifest_handler(
    input_value: EnterpriseManifestInput,
    context: ToolExecutionContext[EnterpriseToolsDependencies],
) -> ToolResult[object]:
    return _result(
        "get_enterprise_data_manifest",
        input_value,
        context,
        validate_enterprise_manifest_output,
    )


def enterprise_summary_handler(
    input_value: EnterpriseSummaryInput,
    context: ToolExecutionContext[EnterpriseToolsDependencies],
) -> ToolResult[object]:
    return _result(
        "get_enterprise_fab_summary",
        input_value,
        context,
        validate_enterprise_summary_output,
    )


def enterprise_sample_handler(
    input_value: EnterpriseSampleInput,
    context: ToolExecutionContext[EnterpriseToolsDependencies],
) -> ToolResult[object]:
    return _result(
        "query_enterprise_data", input_value, context, validate_enterprise_sample_output
    )
