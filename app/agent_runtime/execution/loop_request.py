"""Per-round request construction for the model/tool loop."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .runtime_contracts import RuntimeContractError

if TYPE_CHECKING:
    from .agent_loop import AgentLoopContext
    from .loop_dispatch import LoopDispatchBinding
    from .loop_state import LoopRunState

LOOP_SYNTHESIS_MAX_TOKENS = 8192


async def prepare_round_request(
    context: AgentLoopContext,
    state: LoopRunState,
    dispatch_binding: LoopDispatchBinding | None,
    iteration: int,
) -> dict:
    """Apply the round's synthesis gate, announce the stage and build the model request."""
    loop_guard = context.loop_guard
    messages = context.messages
    connection = context.connection
    thinking = context.thinking
    submit_analysis_tool = context.submit_analysis_tool
    if iteration == loop_guard.max_model_iterations - 1 and loop_guard.total_calls > 0:
        loop_guard.reserve_final_iteration()
    synthesis_only = loop_guard.force_synthesis
    if synthesis_only and state.applied_synthesis_reason != loop_guard.stop_reason:
        messages.append(
            {"role": "system", "content": loop_guard.synthesis_instruction()}
        )
        state.applied_synthesis_reason = loop_guard.stop_reason
    await context.notify(
        context.progress,
        {
            "event": "stage",
            "stage": "synthesis" if synthesis_only else "planning",
            "iteration": iteration + 1,
            "message": (
                f"工具执行已停止，正在基于现有证据组织结论 · {loop_guard.stop_message}"
                if synthesis_only
                else "正在理解问题并规划分析路径"
                if iteration == 0
                else "正在结合工具结果判断是否继续，并组织结论"
            ),
        },
    )
    request_payload = {
        "model": connection.model,
        "messages": messages,
        "temperature": 0.15,
        **context.provider_request_options(connection.provider, thinking),
    }
    if context.intent_route.intent not in {"general_knowledge", "conversation"}:
        answer_contract = state.answer_contract
        loop_tools = context.tools
        if dispatch_binding is not None:
            try:
                bound_tools = json.loads(dispatch_binding.tools_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                raise RuntimeContractError("Loop dispatch contract violated.") from None
            if not isinstance(bound_tools, list):
                raise RuntimeContractError("Loop dispatch contract violated.")
            loop_tools = [*bound_tools, submit_analysis_tool]
        request_payload["tools"] = (
            [submit_analysis_tool]
            if synthesis_only and answer_contract.status == "required"
            else loop_tools
        )
        if not (connection.provider == "deepseek" and thinking):
            request_payload["tool_choice"] = (
                "none"
                if synthesis_only and answer_contract.status != "required"
                else "auto"
            )
        if answer_contract.status == "required":
            request_payload["max_tokens"] = LOOP_SYNTHESIS_MAX_TOKENS
    return request_payload
