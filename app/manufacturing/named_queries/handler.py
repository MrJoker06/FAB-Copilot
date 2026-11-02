"""Pure fixed-kind named-query handlers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime

from ...agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolSource,
    ToolStatus,
)
from .contracts import (
    TOOL_KINDS,
    EquipmentEventsInput,
    EquipmentExcursionsInput,
    LotQueryInput,
    NamedQuery,
    NamedQueryDataError,
    NamedQueryInputError,
    NamedQueryPort,
    NamedQuerySnapshot,
    ProductYieldInput,
    named_query_scope,
    validate_named_query_output,
)

NamedQueryInput = (
    ProductYieldInput | EquipmentEventsInput | EquipmentExcursionsInput | LotQueryInput
)


@dataclass(frozen=True, slots=True)
class NamedQueryDependencies:
    port: NamedQueryPort
    kind: str
    as_of: date

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in TOOL_KINDS.values():
            raise NamedQueryInputError("invalid named-query dependency kind")
        if (
            isinstance(self.as_of, datetime)
            or not isinstance(self.as_of, date)
            or self.as_of == date.max
        ):
            raise NamedQueryInputError("as_of must be a representable date")


def _row_date(value: object) -> date:
    if not isinstance(value, str):
        raise NamedQueryDataError("source returned row outside requested scope")
    try:
        return (
            date.fromisoformat(value)
            if len(value) == 10
            else datetime.fromisoformat(value).date()
        )
    except ValueError as exc:
        raise NamedQueryDataError(
            "source returned row outside requested scope"
        ) from exc


def _snapshot(
    query: NamedQuery, context: ToolExecutionContext[NamedQueryDependencies]
) -> tuple[list[dict[str, object]], ToolSource]:
    try:
        snapshot = context.dependencies.port.fetch(query, context.principal)
    except NamedQueryDataError:
        raise
    except Exception as exc:
        raise NamedQueryDataError("named-query source is unavailable") from exc
    if (
        not isinstance(snapshot, NamedQuerySnapshot)
        or snapshot.query != query
        or snapshot.source.scope != named_query_scope(query, context.principal)
    ):
        raise NamedQueryDataError("source returned an inconsistent scope")
    try:
        rows = deepcopy([dict(row) for row in snapshot.rows])
    except Exception as exc:
        raise NamedQueryDataError("source returned invalid rows") from exc
    if len(rows) > (10 if query.kind == "lot_identity" else 100):
        raise NamedQueryDataError("source returned too many rows")
    validate_named_query_output(query.kind, rows)
    for row in rows:
        if query.product is not None and row.get("product") != query.product:
            raise NamedQueryDataError("source returned row outside requested scope")
        if (
            query.equipment_id is not None
            and row.get("equipment_id") != query.equipment_id
        ):
            raise NamedQueryDataError("source returned row outside requested scope")
        if (
            query.process_step is not None
            and row.get("process_step") != query.process_step
        ):
            raise NamedQueryDataError("source returned row outside requested scope")
        if query.lot_id is not None and row.get("lot_id") != query.lot_id:
            raise NamedQueryDataError("source returned row outside requested scope")
        column = {
            "equipment_events": "event_time",
            "equipment_excursions": "run_time",
        }.get(query.kind)
        if column is not None:
            row_date = _row_date(row.get(column))
            if not query.start <= row_date <= query.end:  # type: ignore[operator]
                raise NamedQueryDataError("source returned row outside requested scope")
    return rows, snapshot.source


def named_query_handler(
    input_value: NamedQueryInput, context: ToolExecutionContext[NamedQueryDependencies]
) -> ToolResult[list[dict[str, object]]]:
    try:
        kind = context.dependencies.kind
        query = input_value.resolve(kind, context.dependencies.as_of)
        if query.kind != kind:
            raise NamedQueryDataError("named-query binding kind mismatch")
        rows, source = _snapshot(query, context)
    except (NamedQueryDataError, NamedQueryInputError):
        raise
    except Exception as exc:
        raise NamedQueryDataError("named-query source returned invalid data") from exc
    tool_name = next(
        name for name, mapped_kind in TOOL_KINDS.items() if mapped_kind == kind
    )
    return ToolResult(
        context.call_id,
        tool_name,
        "1.0.0",
        ToolStatus.SUCCEEDED,
        ToolExecutionState.COMPLETED,
        data=rows,
        sources=(source,),
        row_count=len(rows),
    )
