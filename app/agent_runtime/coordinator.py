"""Agent run coordinator with explicitly injected live dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import AgentRunRequest, AgentRunResult, ProgressCallback
from .coordinator_prepare import prepare_immediate
from .coordinator_availability import handle_model_availability
from .coordinator_model import prepare_model_stage
from .coordinator_loop import execute_agent_loop
from .coordinator_ready import execute_ready_synthesis
from .coordinator_state import CoordinatorRunState


@dataclass(frozen=True)
class CoordinatorDependencies:
    """Dependencies captured from app.agent for one coordinator invocation."""

    system_prompt: str
    perf_counter: Any
    async_client: Any
    settings_type: type
    effective_agent_settings: Any
    get_settings: Any
    prepare_agent_run: Any
    agent_preparation_dependencies: Any
    tool_loop_guard_type: Any
    validate_evidence: Any
    create_answer_contract: Any
    emit: Any
    notify: Any
    offline_answer: Any
    emit_evidence_validation: Any
    stream_answer: Any
    get_model_health: Any
    claim_model_call: Any
    execute_ready_plan: Any
    ready_synthesis_fallback: Any
    emit_answer_synthesis: Any
    build_ready_model_unavailable_result: Any
    context_system_message: Any
    routing_system_message: Any
    playbook_system_message: Any
    planner_system_message: Any
    validator_system_message: Any
    synthesizer_system_message: Any
    prefetch_general_knowledge: Any
    retrieval_system_message: Any
    knowledge_fallback_state: Any
    ready_synthesis_messages: Any
    request_ready_synthesis: Any
    record_model_success: Any
    synthesize_ready_assistant: Any
    retryable_model_error: Any
    record_model_failure: Any
    model_error_category: Any
    build_result: Any
    run_agent_loop: Any
    agent_loop_context_type: Any
    tools: Any
    submit_analysis_tool: Any
    parse_tool_arguments: Any
    execute_registered_tool: Any
    usable_knowledge_result: Any
    normalize_general_knowledge_answer: Any
    has_knowledge_fallback_disclosure: Any
    synthesize_legacy_answer: Any
    synthesize_submission: Any
    provider_request_options: Any
    evidence_observation_type: Any
    stream_completion: Any
    model_failure_reason: Any
    model_retry_delay: Any
    audit_assistant: Any

    def bind_compatibility_globals(self) -> None:
        raise RuntimeError("Coordinator dependencies must be read locally.")


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
