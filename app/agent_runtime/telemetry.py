"""Leaf progress and audit helpers with dependencies injected by the facade."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .contracts import ProgressCallback

if TYPE_CHECKING:
    from .execution.runtime_contracts import RuntimeEvent
    from .ports import AuditEmitter

RUNTIME_STAGE_AUDIT_EVENT = "runtime_stage_completed"


async def notify(progress: ProgressCallback | None, event: dict) -> None:
    if progress is None:
        return
    result = progress(event)
    if inspect.isawaitable(result):
        await result


async def stream_answer(
    progress: ProgressCallback | None,
    answer: str,
    *,
    notify_callback: Callable[[ProgressCallback | None, dict], Awaitable[None]],
    yield_control: Callable[[float], Awaitable[Any]],
) -> None:
    for start in range(0, len(answer), 120):
        await notify_callback(
            progress,
            {"event": "answer_delta", "delta": answer[start : start + 120]},
        )
        await yield_control(0)


def emit_answer_synthesis(
    run_id: str,
    report: Any,
    *,
    emit_event: Callable[..., None],
) -> None:
    payload = report.to_dict()
    emit_event(
        "answer_synthesis_completed",
        run_id,
        plan_id=report.plan_id,
        status=report.status,
        allowed_conclusion_strength=report.allowed_conclusion_strength,
        source_count=len(report.source_refs),
        invalid_source_count=len(report.invalid_source_refs),
        moved_claims=report.moved_claims,
        wording_adjustment_count=len(report.wording_adjustments),
        full_content={"answer_synthesis": payload},
    )


def trace_reference_counts(
    result: dict[str, Any],
    *,
    model_knowledge_ref: str,
) -> dict[str, int]:
    """Count final evidence references without conflating tools and documents."""

    synthesis = (
        result.get("answer_synthesis")
        if isinstance(result.get("answer_synthesis"), dict)
        else {}
    )
    references = {
        str(reference)
        for reference in synthesis.get("source_refs", [])
        if isinstance(reference, str) and reference
    }
    for source in result.get("sources", []):
        if not isinstance(source, dict):
            continue
        reference_id = source.get("reference_id")
        if isinstance(reference_id, str) and reference_id:
            references.add(reference_id)
    tool_references = {reference for reference in references if reference.startswith("TOOL:")}
    knowledge_references = references - tool_references - {model_knowledge_ref}
    return {
        "knowledge_source_count": len(knowledge_references),
        "tool_evidence_count": len(tool_references),
        "total_reference_count": len(knowledge_references | tool_references),
    }


def runtime_event_audit_fields(event: RuntimeEvent) -> dict[str, object]:
    """Map one payload-free ``RuntimeEvent`` to audit fields in a fixed order.

    Common: ``call_id``, ``kind``, ``status`` (enum value) and
    ``runtime_event_schema_version``; the audit envelope reserves
    ``schema_version`` and ``run_id`` (passed positionally).
    ``model_response`` adds ``prompt_tokens``, ``completion_tokens`` and
    ``total_tokens``; ``tool_result`` adds ``tool_name``, ``row_count`` and
    ``execution_state`` (enum value).
    """
    fields: dict[str, object] = {
        "call_id": event.call_id,
        "kind": event.kind,
        "status": event.status.value,
        "runtime_event_schema_version": event.schema_version,
    }
    if event.kind == "model_response":
        usage = event.usage
        fields["prompt_tokens"] = usage.prompt_tokens
        fields["completion_tokens"] = usage.completion_tokens
        fields["total_tokens"] = usage.total_tokens
    else:
        fields["tool_name"] = event.tool_name
        fields["row_count"] = event.row_count
        fields["execution_state"] = event.execution_state.value
    return fields


class AuditEventSink:
    """``EventSink`` adapter writing each runtime event as one audit record.

    Only explicit assemblies use it; the default coordinator path does not, so
    its audit stream is unchanged.  Emitter failures propagate to the publisher,
    as for every ``EventSink``.
    """

    __slots__ = ("_emit",)

    def __init__(self, emit: AuditEmitter) -> None:
        self._emit = emit

    async def emit(self, event: RuntimeEvent) -> None:
        self._emit(
            RUNTIME_STAGE_AUDIT_EVENT, event.run_id, **runtime_event_audit_fields(event)
        )
