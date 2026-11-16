"""Small per-run facade over the typed runtime-port pilot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from .result_access_run import ResultAccessRun


@dataclass(frozen=True, slots=True)
class AgentRun:
    definition: AgentDefinition
    context: RuntimeContext
    model: ModelResponsePort
    dispatcher: ToolDispatcherPort
    events: EventSink
    tools_json: str
    skill_context: tuple[ModelMessage, ...] = ()
    skill_metadata: tuple[tuple[str, str], ...] = ()
    result_access: ResultAccessRun | None = None

    async def model_stage(
        self, *, call_id: str, messages: tuple[ModelMessage, ...]
    ) -> StageResult[ModelResponse]:
        if not isinstance(messages, tuple) or any(
            not isinstance(message, ModelMessage) for message in messages
        ):
            raise RuntimeContractError("messages must be a tuple of ModelMessage")
        request = ModelRequest(
            call_id=call_id,
            messages=(
                ModelMessage("system", self.definition.instructions),
                *self.skill_context,
                *messages,
            ),
            tools_json=self.tools_json,
        )
        if self.result_access is None:
            return await execute_model_stage(self.context, request, model=self.model)
        from .result_access_run import typed_model_stage
        return await typed_model_stage(self, request, model_stage=execute_model_stage)

    async def tool_stage(
        self,
        call: ModelToolCall,
        *,
        call_id: str,
        step_id: str | None = None,
    ) -> StageResult[ToolResult[object]]:
        if self.result_access is not None and self.result_access.closed:
            raise RuntimeContractError("Run is closed")
        dispatcher = self.dispatcher
        if self.result_access is not None and call.name == "read_tool_result":
            if self.result_access.dispatcher is None:
                raise RuntimeContractError("Result access is unavailable")
            dispatcher = self.result_access
        stage = await execute_tool_stage(
            self.context,
            call,
            dispatcher=dispatcher,
            call_id=call_id,
            step_id=step_id,
        )
        if self.result_access is not None:
            from .result_access_run import typed_result_view
            typed_result_view(self, call, call_id, stage.value)
        return stage

    def begin_synthesis(self, *, timeout: float = 60, max_output: int = 8192) -> None:
        if self.result_access is None:
            raise RuntimeContractError("Result access is unavailable")
        self.result_access.begin_synthesis(timeout, max_output)

    def close(self) -> None:
        if self.result_access is not None:
            self.result_access.close()

    async def publish(self, event: RuntimeEvent) -> None:
        if event.run_id != self.context.run_id:
            raise RuntimeContractError("runtime event does not belong to this run")
        await publish_stage_event(event, sink=self.events)
