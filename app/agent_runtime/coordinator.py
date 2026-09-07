"""Agent run coordinator with explicitly injected live dependencies."""

from __future__ import annotations

from .contracts import AgentRunRequest, AgentRunResult, ProgressCallback
from .coordinator_state import CoordinatorRunState
from .dependencies import CoordinatorDependencies
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

    state = CoordinatorRunState(
        question=request.question,
        history=request.history,
        run_id=request.run_id,
        progress=progress,
        thinking=request.thinking,
    )
    prepared = await prepare_immediate(state, deps=deps)
    if prepared.result is not None:
        await deps.stream_answer(progress, prepared.result["answer"])
        return prepared.result
    availability = await handle_model_availability(state, deps=deps)
    if availability.result is not None:
        return availability.result
    await prepare_model_stage(state, deps=deps)
    ready_result = await execute_ready_synthesis(state, deps=deps)
    if ready_result is not None:
        return ready_result
    return await execute_agent_loop(state, deps=deps)
