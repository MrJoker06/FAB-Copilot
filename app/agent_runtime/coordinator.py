"""Agent run coordinator with explicitly injected live dependencies."""

from __future__ import annotations

from .contracts import AgentRunRequest, AgentRunResult, ProgressCallback
from .coordinator_state import CoordinatorRunState
from .dependencies import CoordinatorDependencies
from .stages.ready import finish_evidence_failure
from .stages import (
    execute_agent_loop,
    execute_ready_synthesis,
    handle_model_availability,
    prepare_immediate,
    prepare_model_stage,
)


async def coordinate_agent_run(
    request: AgentRunRequest,
    progress: ProgressCallback | None,
    *,
    deps: CoordinatorDependencies,
) -> AgentRunResult:
    """Coordinate one complete Agent run using supplied live dependencies."""
    factory = getattr(deps, "result_access_factory", None)
    if factory is None:
        return await _coordinate_stages(request, progress, deps=deps)
    access = factory(request.session_id, request.run_id)
    try:
        with access.activate():
            if request.result_ref:
                from .result_review import review_saved_result
                result = await review_saved_result(access, request.result_ref, request.result_cursor, progress)
            else:
                if request.session_id and not access.authorized():
                    from .result_access_run import ResultRequestLimit
                    raise ResultRequestLimit("会话已不可用，未执行业务来源查询")
                result = await _coordinate_stages(request, progress, deps=deps)
            await access.flush(progress)
            if access.notices:
                result["tool_result_access"] = list(access.notices)
            return result
    finally:
        access.close()


async def _coordinate_stages(request, progress, *, deps):
    from .result_access_run import current_result_access

    state = CoordinatorRunState(
        question=request.question,
        history=request.history,
        run_id=request.run_id,
        progress=progress,
        thinking=request.thinking,
        thinking_effort=request.thinking_effort,
        thinking_dialect=request.thinking_dialect,
    )
    prepared = await prepare_immediate(state, deps=deps)
    if prepared.result is not None:
        await deps.stream_answer(progress, prepared.result["answer"])
        return prepared.result
    if getattr(state.evidence_validation, "assessment_status", None) == "check_failed":
        return await finish_evidence_failure(state, deps=deps)
    if deps.tool_run_factory is not None:
        state.tool_run = deps.tool_run_factory(
            settings=state.settings,
            plan=state.execution_plan,
            guard=state.loop_guard,
            run_id=state.run_id,
        )
    access = current_result_access()
    if access is not None:
        dispatcher = getattr(state.tool_run, "dispatcher", None)
        access.bind(state.loop_guard, getattr(dispatcher, "registry", None))
        if state.intent_route.intent in {"general_knowledge", "conversation"}:
            access.enabled = False
            access.unavailable_reason = "PATH_READ_UNSUPPORTED"
    availability = await handle_model_availability(state, deps=deps)
    if availability.result is not None:
        return availability.result
    await prepare_model_stage(state, deps=deps)
    ready_result = await execute_ready_synthesis(state, deps=deps)
    if ready_result is not None:
        return ready_result
    return await execute_agent_loop(state, deps=deps)
