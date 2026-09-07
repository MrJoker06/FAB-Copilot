"""Invocation-local dependency groups for the Agent coordinator."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class PreparationDependencies:
    system_prompt: str
    perf_counter: Any
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


@dataclass(frozen=True)
class AvailabilityDependencies:
    get_model_health: Any
    claim_model_call: Any
    execute_ready_plan: Any
    ready_synthesis_fallback: Any
    emit_answer_synthesis: Any
    build_ready_model_unavailable_result: Any


@dataclass(frozen=True)
class ModelDependencies:
    context_system_message: Any
    routing_system_message: Any
    playbook_system_message: Any
    planner_system_message: Any
    validator_system_message: Any
    synthesizer_system_message: Any
    prefetch_general_knowledge: Any
    retrieval_system_message: Any
    knowledge_fallback_state: Any


@dataclass(frozen=True)
class ReadyDependencies:
    async_client: Any
    ready_synthesis_messages: Any
    request_ready_synthesis: Any
    record_model_success: Any
    synthesize_ready_assistant: Any
    retryable_model_error: Any
    record_model_failure: Any
    model_error_category: Any


@dataclass(frozen=True)
class LoopDependencies:
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


@dataclass(frozen=True)
class CoordinatorDependencies:
    """One immutable snapshot, grouped by stage while preserving legacy access."""

    preparation: PreparationDependencies
    availability: AvailabilityDependencies
    model: ModelDependencies
    ready: ReadyDependencies
    loop: LoopDependencies

    def __getattr__(self, name: str) -> Any:
        """Keep existing ``deps.name`` consumers and patch tests source-compatible."""
        for group in (self.preparation, self.availability, self.model, self.ready, self.loop):
            if name in {item.name for item in fields(group)}:
                return getattr(group, name)
        raise AttributeError(name)

    def bind_compatibility_globals(self) -> None:
        raise RuntimeError("Coordinator dependencies must be read locally.")
