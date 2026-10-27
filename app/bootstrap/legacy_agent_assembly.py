"""Legacy coordinator dependency assembly from an invocation-local namespace."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent_runtime.dependencies import CoordinatorDependencies


def build_legacy_coordinator_dependencies(
    namespace: Mapping[str, Any],
) -> CoordinatorDependencies:
    """Build one legacy dependency snapshot without bypassing live patch bindings."""
    return namespace["CoordinatorDependencies"](
        preparation=namespace["CoordinatorPreparationDependencies"](
            system_prompt=namespace["SYSTEM_PROMPT"],
            perf_counter=namespace["time"].perf_counter,
            settings_type=namespace["Settings"],
            effective_agent_settings=namespace["effective_agent_settings"],
            get_settings=namespace["get_settings"],
            prepare_agent_run=namespace["prepare_agent_run"],
            agent_preparation_dependencies=namespace["_agent_preparation_dependencies"],
            tool_loop_guard_type=namespace["ToolLoopGuard"],
            validate_evidence=namespace["validate_evidence"],
            create_answer_contract=namespace["create_answer_contract"],
            emit=namespace["emit"],
            notify=namespace["_notify"],
            offline_answer=namespace["_offline_answer"],
            emit_evidence_validation=namespace["_emit_evidence_validation"],
            stream_answer=namespace["_stream_answer"],
        ),
        availability=namespace["CoordinatorAvailabilityDependencies"](
            get_model_health=namespace["get_model_health"],
            claim_model_call=namespace["claim_model_call"],
            execute_ready_plan=namespace["_execute_ready_plan"],
            ready_synthesis_fallback=namespace["_ready_synthesis_fallback"],
            emit_answer_synthesis=namespace["_emit_answer_synthesis"],
            build_ready_model_unavailable_result=namespace[
                "_build_ready_model_unavailable_result_runtime"
            ],
        ),
        model=namespace["CoordinatorModelDependencies"](
            context_system_message=namespace["context_system_message"],
            routing_system_message=namespace["routing_system_message"],
            playbook_system_message=namespace["playbook_system_message"],
            planner_system_message=namespace["planner_system_message"],
            validator_system_message=namespace["validator_system_message"],
            synthesizer_system_message=namespace["synthesizer_system_message"],
            prefetch_general_knowledge=namespace["_prefetch_general_knowledge"],
            retrieval_system_message=namespace["retrieval_system_message"],
            knowledge_fallback_state=namespace["_knowledge_fallback_state"],
            stage_memory_messages=namespace["build_stage_memory_messages"],
        ),
        ready=namespace["CoordinatorReadyDependencies"](
            async_client=namespace["httpx"].AsyncClient,
            ready_synthesis_messages=namespace["_ready_synthesis_messages"],
            request_ready_synthesis=namespace["_request_ready_synthesis"],
            record_model_success=namespace["record_model_success"],
            synthesize_ready_assistant=namespace["_synthesize_ready_assistant"],
            retryable_model_error=namespace["_retryable_model_error"],
            record_model_failure=namespace["record_model_failure"],
            model_error_category=namespace["_model_error_category"],
        ),
        loop=namespace["CoordinatorLoopDependencies"](
            build_result=namespace["_build_result_runtime"],
            run_agent_loop=namespace["_run_agent_loop_runtime"],
            agent_loop_context_type=namespace["AgentLoopContext"],
            tools=namespace["TOOLS"],
            submit_analysis_tool=namespace["SUBMIT_ANALYSIS_TOOL"],
            parse_tool_arguments=namespace["_parse_tool_arguments"],
            execute_registered_tool=namespace["_execute_registered_tool"],
            usable_knowledge_result=namespace["_usable_knowledge_result"],
            normalize_general_knowledge_answer=namespace[
                "_normalize_general_knowledge_answer"
            ],
            has_knowledge_fallback_disclosure=namespace[
                "_has_knowledge_fallback_disclosure"
            ],
            synthesize_legacy_answer=namespace["synthesize_legacy_answer"],
            synthesize_submission=namespace["synthesize_submission"],
            provider_request_options=namespace["provider_request_options"],
            evidence_observation_type=namespace["EvidenceObservation"],
            stream_completion=namespace["_stream_completion"],
            model_failure_reason=namespace["_model_failure_reason"],
            model_retry_delay=namespace["_model_retry_delay"],
            audit_assistant=namespace["_audit_assistant"],
            request_synthesis_correction=namespace["_request_synthesis_correction"],
        ),
    )
