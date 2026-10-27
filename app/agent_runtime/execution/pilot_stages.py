"""Single-call consumers for the typed runtime-port pilot."""

from __future__ import annotations

from ..tools.contracts import ToolResult, ToolStatus
from .runtime_contracts import (
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeContractError,
    RuntimeEvent,
    StageResult,
)
from .runtime_ports import EventSink, ModelResponsePort, ToolDispatcherPort

_INVALID_MODEL_RESPONSE = "model port returned an invalid response"
_INVALID_TOOL_RESULT = "tool dispatcher returned an invalid result"
_MISMATCHED_TOOL_RESULT = "tool dispatcher returned a mismatched result"


async def execute_model_stage(
    context: RuntimeContext,
    request: ModelRequest,
    *,
    model: ModelResponsePort,
) -> StageResult[ModelResponse]:
    response = await model.complete(request, context)
    if not isinstance(response, ModelResponse):
        raise RuntimeContractError(_INVALID_MODEL_RESPONSE)
    event = RuntimeEvent(
        run_id=context.run_id,
        call_id=request.call_id,
        kind="model_response",
        status=ToolStatus.SUCCEEDED,
        usage=response.usage,
    )
    return StageResult(response, event)


async def execute_tool_stage(
    context: RuntimeContext,
    call: ModelToolCall,
    *,
    dispatcher: ToolDispatcherPort,
    call_id: str,
    step_id: str | None = None,
) -> StageResult[ToolResult[object]]:
    tool_context = context.for_tool_call(call_id, step_id)
    result = await dispatcher.dispatch(call.name, call.arguments, tool_context)
    if not isinstance(result, ToolResult):
        raise RuntimeContractError(_INVALID_TOOL_RESULT)
    if result.call_id != call_id or result.tool_name != call.name:
        raise RuntimeContractError(_MISMATCHED_TOOL_RESULT)
    event = RuntimeEvent(
        run_id=context.run_id,
        call_id=call_id,
        kind="tool_result",
        status=result.status,
        tool_name=result.tool_name,
        row_count=result.row_count,
        execution_state=result.execution_state,
    )
    return StageResult(result, event)


async def publish_stage_event(event: RuntimeEvent, *, sink: EventSink) -> None:
    await sink.emit(event)
