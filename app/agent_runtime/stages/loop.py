"""Non-ready Agent loop stage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .model import build_result
from ..coordinator_state import CoordinatorRunState

if TYPE_CHECKING:
    from ..dependencies import CoordinatorDependencies


async def execute_agent_loop(
    state: CoordinatorRunState, *, deps: "CoordinatorDependencies",
) -> dict:
    """Build the legacy loop context while retaining state as the coordinator truth."""
    context: Any = None

    def build_loop_result(answer: str, report: Any) -> dict:
        # The execution loop mutates the reference containers supplied below.  Copy
        # its context back before constructing the external result so later stages
        # do not retain a parallel source of mutable coordinator state.
        state.messages = context.messages
        state.trace = context.trace
        state.sources = context.sources
        state.evidence_observations = context.evidence_observations
        state.evidence_validation = context.evidence_validation
        state.answer_contract = context.answer_contract
        state.total_usage = context.total_usage
        state.knowledge_fallback = context.knowledge_fallback
        state.fallback_announced = context.fallback_announced
        state.applied_synthesis_reason = context.applied_synthesis_reason
        state.health = context.health
        return build_result(state, deps, answer, report)

    context = deps.agent_loop_context_type(
        settings=state.settings, connection=state.connection, intent_route=state.intent_route,
        execution_plan=state.execution_plan, selected_playbook=state.selected_playbook,
        loop_guard=state.loop_guard, run_id=state.run_id, progress=state.progress,
        thinking=state.thinking, main_recovery_trial=state.main_recovery_trial,
        health_enabled=state.health_enabled, selected_model_id=state.selected_model_id,
        question=state.question,
        analysis_question=state.analysis_question, playbook_selection=state.playbook_selection,
        context_resolution=state.context_resolution, messages=state.messages, trace=state.trace,
        sources=state.sources, evidence_observations=state.evidence_observations,
        evidence_validation=state.evidence_validation, answer_contract=state.answer_contract,
        total_usage=state.total_usage, knowledge_fallback=state.knowledge_fallback,
        fallback_announced=state.fallback_announced,
        applied_synthesis_reason=state.applied_synthesis_reason, health=state.health,
        build_result=build_loop_result, notify=deps.notify, stream_answer=deps.stream_answer,
        emit_event=deps.emit, stream_completion=deps.stream_completion,
        retryable_model_error=deps.retryable_model_error, model_error_category=deps.model_error_category,
        model_failure_reason=deps.model_failure_reason, model_retry_delay=deps.model_retry_delay,
        record_model_success=deps.record_model_success, record_model_failure=deps.record_model_failure,
        audit_assistant=deps.audit_assistant, tools=deps.tools,
        submit_analysis_tool=deps.submit_analysis_tool,
        parse_tool_arguments=deps.parse_tool_arguments, execute_tool=deps.execute_registered_tool,
        usable_knowledge_result=deps.usable_knowledge_result,
        normalize_general_knowledge_answer=deps.normalize_general_knowledge_answer,
        has_knowledge_fallback_disclosure=deps.has_knowledge_fallback_disclosure,
        knowledge_fallback_state=deps.knowledge_fallback_state,
        validate_evidence=deps.validate_evidence, create_answer_contract=deps.create_answer_contract,
        validator_system_message=deps.validator_system_message,
        synthesizer_system_message=deps.synthesizer_system_message,
        synthesize_legacy_answer=deps.synthesize_legacy_answer,
        synthesize_submission=deps.synthesize_submission,
        emit_answer_synthesis=deps.emit_answer_synthesis,
        emit_evidence_validation=deps.emit_evidence_validation, offline_answer=deps.offline_answer,
        evidence_observation_type=deps.evidence_observation_type,
        provider_request_options=deps.provider_request_options,
    )
    return await deps.run_agent_loop(context)
