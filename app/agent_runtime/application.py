"""Small per-run facade over the typed runtime-port pilot."""

from __future__ import annotations

from dataclasses import dataclass

from .definition import AgentDefinition
from .execution.pilot_stages import (
    execute_model_stage,
    execute_tool_stage,
    publish_stage_event,
)
from .execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeContractError,
    RuntimeEvent,
    StageResult,
)
from .execution.runtime_ports import EventSink, ModelResponsePort, ToolDispatcherPort
from .tools.contracts import ToolResult


@dataclass(frozen=True, slots=True)
class AgentRun:
    definition: AgentDefinition
    context: RuntimeContext
    model: ModelResponsePort
    dispatcher: ToolDispatcherPort
    events: EventSink
    tools_json: str

    async def model_stage(
        self, *, call_id: str, messages: tuple[ModelMessage, ...]
    ) -> StageResult[ModelResponse]:
        if not isinstance(messages, tuple) or any(
            not isinstance(message, ModelMessage) for message in messages
        ):
            raise RuntimeContractError("messages must be a tuple of ModelMessage")
        request = ModelRequest(
            call_id=call_id,
            messages=(ModelMessage("system", self.definition.instructions), *messages),
            tools_json=self.tools_json,
        )
        return await execute_model_stage(self.context, request, model=self.model)

    async def tool_stage(
        self,
        call: ModelToolCall,
        *,
        call_id: str,
        step_id: str | None = None,
    ) -> StageResult[ToolResult[object]]:
        return await execute_tool_stage(
            self.context,
            call,
            dispatcher=self.dispatcher,
            call_id=call_id,
            step_id=step_id,
        )

    async def publish(self, event: RuntimeEvent) -> None:
        if event.run_id != self.context.run_id:
            raise RuntimeContractError("runtime event does not belong to this run")
        await publish_stage_event(event, sink=self.events)
