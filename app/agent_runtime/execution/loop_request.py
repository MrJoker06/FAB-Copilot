"""Per-round request construction for the model/tool loop."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..result_access_run import current_result_access
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
    access = current_result_access()
    if access is not None and synthesis_only:
        access.begin_synthesis(context.settings.api_timeout_seconds, LOOP_SYNTHESIS_MAX_TOKENS)
        if (access.request_count >= 5 or iteration == loop_guard.max_model_iterations - 1) and access.reader is not None:
            access.reader.phase = "final"
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
        **context.provider_request_options(
            connection.provider,
            thinking,
            context.thinking_effort,
            connection.model,
            context.thinking_dialect,
        ),
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
        if access is not None and access.can_read() and any(item.get("status") == "saved" for item in access.notices):
            request_payload["tools"] = [*request_payload["tools"], access.tool_view()]
            if messages and not any(item.get("_fab_read_instruction") for item in messages):
                messages.append({"role":"system","content":"业务工具已停止。允许在剩余额度内单独调用 read_tool_result 读取已保存快照，或单独最终提交；不得重新查询业务来源。","_fab_read_instruction":True})
        if not (connection.provider == "deepseek" and thinking):
            request_payload["tool_choice"] = (
                "none"
                if synthesis_only and answer_contract.status != "required" and not (access is not None and access.can_read())
                else "auto"
            )
        if answer_contract.status == "required":
            request_payload["max_tokens"] = LOOP_SYNTHESIS_MAX_TOKENS
    return request_payload
