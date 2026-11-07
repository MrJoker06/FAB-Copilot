"""Invocation-local dependency groups for the Agent coordinator."""

from __future__ import annotations

from dataclasses import dataclass, fields
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..evidence.validator import EvidenceObservation
    from ..model_gateway.gateway import ModelGatewayPort
    from .execution.agent_loop import AgentLoopContext
    from .execution.loop_guard import ToolLoopGuard
    from .ports import (
        AgentLoopRunner,
        AgentPreparationFactory,
        AgentRunPreparer,
        AnswerContractFactory,
        AnswerNormalizer,
        AnswerStreamer,
        AnswerSynthesisEmitter,
        AssistantAuditor,
        AuditEmitter,
        Clock,
        ContextMessageBuilder,
        ContractMessageBuilder,
        DisclosurePredicate,
        EvidenceValidationEmitter,
        EvidenceValidator,
        GeneralKnowledgePrefetcher,
        JsonObject,
        KnowledgeFallbackStateBuilder,
        KnowledgeResultPredicate,
        LegacyAnswerSynthesizer,
        ModelCallClaimer,
        ModelErrorClassifier,
        ModelErrorPredicate,
        ModelFailureRecorder,
        ModelHealthReader,
        ModelRetryDelay,
        ModelSuccessRecorder,
        OfflineAnswerer,
        OfflineToolRunner,
        PlanMessageBuilder,
        PlaybookMessageBuilder,
        ProgressSink,
        ProviderRequestOptions,
        ReadyAssistantSynthesizer,
        ReadyPlanExecutor,
        ReadySynthesisFallback,
        ReadySynthesisMessages,
        ReadySynthesisRequester,
        ReadyUnavailableResultBuilder,
        RegisteredToolExecutor,
        ResultBuilder,
        RetrievalMessageBuilder,
        RouteMessageBuilder,
        RuntimeSettings,
        SettingsProvider,
        SettingsResolver,
        StageMemoryMessages,
        SubmissionSynthesizer,
        SynthesisCorrectionRequester,
        ToolArgumentParser,
        ToolRunFactory,
        ValidationMessageBuilder,
    )


@lru_cache(maxsize=32)
def _dependency_field_names(group_type: type[object]) -> frozenset[str]:
    """Return immutable structural metadata without retaining a run's values."""
    return frozenset(item.name for item in fields(group_type))


@dataclass(frozen=True)
class PreparationDependencies:
    system_prompt: str
    perf_counter: Clock
    settings_type: type[RuntimeSettings]
    effective_agent_settings: SettingsResolver
    get_settings: SettingsProvider
    prepare_agent_run: AgentRunPreparer
    agent_preparation_dependencies: AgentPreparationFactory
    tool_loop_guard_type: type[ToolLoopGuard]
    validate_evidence: EvidenceValidator
    create_answer_contract: AnswerContractFactory
    emit: AuditEmitter
    notify: ProgressSink
    offline_answer: OfflineAnswerer
    emit_evidence_validation: EvidenceValidationEmitter
    stream_answer: AnswerStreamer


@dataclass(frozen=True)
class AvailabilityDependencies:
    get_model_health: ModelHealthReader
    claim_model_call: ModelCallClaimer
    execute_ready_plan: ReadyPlanExecutor
    ready_synthesis_fallback: ReadySynthesisFallback
    emit_answer_synthesis: AnswerSynthesisEmitter
    build_ready_model_unavailable_result: ReadyUnavailableResultBuilder


@dataclass(frozen=True)
class ModelDependencies:
    context_system_message: ContextMessageBuilder
    routing_system_message: RouteMessageBuilder
    playbook_system_message: PlaybookMessageBuilder
    planner_system_message: PlanMessageBuilder
    validator_system_message: ValidationMessageBuilder
    synthesizer_system_message: ContractMessageBuilder
    prefetch_general_knowledge: GeneralKnowledgePrefetcher
    retrieval_system_message: RetrievalMessageBuilder
    knowledge_fallback_state: KnowledgeFallbackStateBuilder
    stage_memory_messages: StageMemoryMessages


@dataclass(frozen=True)
class ReadyDependencies:
    model_gateway: ModelGatewayPort
    ready_synthesis_messages: ReadySynthesisMessages
    request_ready_synthesis: ReadySynthesisRequester
    record_model_success: ModelSuccessRecorder
    synthesize_ready_assistant: ReadyAssistantSynthesizer
    retryable_model_error: ModelErrorPredicate
    record_model_failure: ModelFailureRecorder
    model_error_category: ModelErrorClassifier


@dataclass(frozen=True)
class LoopDependencies:
    build_result: ResultBuilder
    run_agent_loop: AgentLoopRunner
    agent_loop_context_type: type[AgentLoopContext]
    tools: list[JsonObject]
    submit_analysis_tool: JsonObject
    parse_tool_arguments: ToolArgumentParser
    execute_registered_tool: RegisteredToolExecutor
    usable_knowledge_result: KnowledgeResultPredicate
    normalize_general_knowledge_answer: AnswerNormalizer
    has_knowledge_fallback_disclosure: DisclosurePredicate
    synthesize_legacy_answer: LegacyAnswerSynthesizer
    synthesize_submission: SubmissionSynthesizer
    provider_request_options: ProviderRequestOptions
    evidence_observation_type: type[EvidenceObservation]
    model_gateway: ModelGatewayPort
    model_failure_reason: ModelErrorClassifier
    model_retry_delay: ModelRetryDelay
    audit_assistant: AssistantAuditor
    request_synthesis_correction: SynthesisCorrectionRequester


@dataclass(frozen=True)
class CoordinatorDependencies:
    """One immutable snapshot, grouped by stage while preserving legacy access."""

    preparation: PreparationDependencies
    availability: AvailabilityDependencies
    model: ModelDependencies
    ready: ReadyDependencies
    loop: LoopDependencies
    tool_run_factory: ToolRunFactory | None = None
    offline_tool_runner: OfflineToolRunner | None = None

    def __getattr__(self, name: str) -> Any:
        """Keep existing ``deps.name`` consumers and patch tests source-compatible."""
        for group in (self.preparation, self.availability, self.model, self.ready, self.loop):
            if name in _dependency_field_names(type(group)):
                return getattr(group, name)
        raise AttributeError(name)

    def bind_compatibility_globals(self) -> None:
        raise RuntimeError("Coordinator dependencies must be read locally.")
