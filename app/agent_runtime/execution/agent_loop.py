from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .loop_answer import (
    finish_iteration_limit,
    finish_submission,
    finish_text_answer,
    is_submission_round,
)
from .loop_dispatch import LoopDispatchBinding
from .loop_model_call import ModelTurn, call_model
from .loop_request import LOOP_SYNTHESIS_MAX_TOKENS as LOOP_SYNTHESIS_MAX_TOKENS
from .loop_request import prepare_round_request
from .loop_response import classify_loop_response
from .loop_round_validation import validate_round
from .loop_state import LoopRunState, add_usage
from .loop_tool_round import execute_tool_round
from .runtime_contracts import RuntimeContractError

if TYPE_CHECKING:
    from ...evidence.answer_synthesizer import AnswerContract
    from ...evidence.validator import EvidenceObservation, EvidenceValidation
    from ...intent_runtime.contracts import IntentRoute
    from ...manufacturing.playbooks import DomainPlaybook, PlaybookSelection
    from ...memory_system.contracts import ContextResolution
    from ...model_gateway.gateway import ModelGatewayPort
    from ...planning_runtime.contracts import ExecutionPlan
    from ..contracts import ProgressCallback
    from ..ports import (
        AnswerContractFactory,
        AnswerStreamer,
        AnswerSynthesisEmitter,
        AuditEmitter,
        ContractMessageBuilder,
        EvidenceValidator,
        KnowledgeFallbackStateBuilder,
        LegacyAnswerSynthesizer,
        LoopResultBuilder,
        ModelFailureRecorder,
        ModelSuccessRecorder,
        OfflineAnswerer,
        ProgressSink,
        RegisteredToolExecutor,
        RuntimeModelConnection,
        RuntimeSettings,
        SubmissionSynthesizer,
        SynthesisCorrectionRequester,
        ValidationMessageBuilder,
    )
    from .loop_guard import ToolLoopGuard


@dataclass
class AgentLoopContext:
    settings: RuntimeSettings
    connection: RuntimeModelConnection
    intent_route: IntentRoute
    execution_plan: ExecutionPlan
    selected_playbook: DomainPlaybook | None
    loop_guard: ToolLoopGuard
    run_id: str
    progress: ProgressCallback | None
    thinking: bool
    main_recovery_trial: bool
    health_enabled: bool
    selected_model_id: str
    question: str
    analysis_question: str
    playbook_selection: PlaybookSelection
    context_resolution: ContextResolution
    messages: list[dict]
    trace: list[dict]
    sources: dict[str, dict]
    evidence_observations: list[EvidenceObservation]
    evidence_validation: EvidenceValidation
    answer_contract: AnswerContract
    total_usage: dict[str, int]
    knowledge_fallback: dict[str, Any]
    fallback_announced: bool
    applied_synthesis_reason: str | None
    health: dict[str, Any]
    build_result: LoopResultBuilder
    notify: ProgressSink
    stream_answer: AnswerStreamer
    emit_event: AuditEmitter
    model_gateway: ModelGatewayPort
    retryable_model_error: Callable[[Exception], bool]
    model_error_category: Callable[[Exception], str]
    model_failure_reason: Callable[[Exception], str]
    model_retry_delay: Callable[[float, int, Exception], float]
    record_model_success: ModelSuccessRecorder
    record_model_failure: ModelFailureRecorder
    audit_assistant: Callable[[dict], dict]
    tools: list[dict]
    submit_analysis_tool: dict
    parse_tool_arguments: Callable[[str], tuple[dict, Exception | None]]
    execute_tool: RegisteredToolExecutor
    usable_knowledge_result: Callable[[str, dict], bool]
    normalize_general_knowledge_answer: Callable[[str], str]
    has_knowledge_fallback_disclosure: Callable[[str], bool]
    knowledge_fallback_state: KnowledgeFallbackStateBuilder
    validate_evidence: EvidenceValidator
    create_answer_contract: AnswerContractFactory
    validator_system_message: ValidationMessageBuilder
    synthesizer_system_message: ContractMessageBuilder
    synthesize_legacy_answer: LegacyAnswerSynthesizer
    synthesize_submission: SubmissionSynthesizer
    emit_answer_synthesis: AnswerSynthesisEmitter
    emit_evidence_validation: Callable[[str, int, dict[str, Any]], None]
    offline_answer: OfflineAnswerer
    evidence_observation_type: type[EvidenceObservation]
    provider_request_options: Callable[[str, bool], dict]
    request_synthesis_correction: SynthesisCorrectionRequester
    dispatch_binding: LoopDispatchBinding | None = None
    native_fallback: Callable[[], Awaitable[dict]] | None = None


def _resolve_dispatch_binding(
    context: AgentLoopContext, dispatch_binding: LoopDispatchBinding | None
) -> LoopDispatchBinding | None:
    if (
        dispatch_binding is not None
        and context.dispatch_binding is not None
        and dispatch_binding is not context.dispatch_binding
    ):
        raise RuntimeContractError("Loop dispatch contract violated.")
    if dispatch_binding is None:
        dispatch_binding = context.dispatch_binding
    if dispatch_binding is not None:
        from .loop_dispatch import validate_loop_binding

        if not validate_loop_binding(
            context.execution_plan, context.loop_guard, context.run_id, dispatch_binding
        ):
            raise RuntimeContractError("Loop dispatch contract violated.")
    return dispatch_binding


async def run_agent_loop(
    context: AgentLoopContext, *, dispatch_binding: LoopDispatchBinding | None = None
) -> dict:
    """Run the non-ready model/tool loop with live dependencies injected by app.agent_runtime.service."""
    state = LoopRunState.from_context(context)
    dispatch_binding = _resolve_dispatch_binding(context, dispatch_binding)
    settings = context.settings
    loop_guard = context.loop_guard
    model_gateway = context.model_gateway
    model_endpoint = model_gateway.endpoint_for(
        context.connection,
        chat_template=getattr(settings, "chat_template_compat", None),
    )
    async with model_gateway.open(
        model_endpoint, timeout_seconds=settings.api_timeout_seconds
    ) as session:
        for iteration in range(loop_guard.max_model_iterations):
            request_payload = await prepare_round_request(
                context, state, dispatch_binding, iteration
            )
            turn = await call_model(
                context, state, session, request_payload, iteration, dispatch_binding
            )
            if not isinstance(turn, ModelTurn):
                return turn
            add_usage(context.total_usage, turn.usage)
            classified_response = (
                classify_loop_response(turn.assistant)
                if dispatch_binding is not None
                else None
            )
            context.messages.append(turn.assistant)
            tool_calls = (
                list(classified_response.tool_calls)
                if classified_response is not None
                else turn.assistant.get("tool_calls") or []
            )
            if not tool_calls:
                return await finish_text_answer(context, state, dispatch_binding, turn)
            if is_submission_round(classified_response, tool_calls):
                return await finish_submission(
                    context,
                    state,
                    dispatch_binding,
                    session,
                    turn,
                    request_payload,
                    classified_response,
                    tool_calls,
                    iteration,
                )
            await execute_tool_round(
                context, dispatch_binding, classified_response, tool_calls, iteration
            )
            await validate_round(context, state, dispatch_binding, iteration)
    return await finish_iteration_limit(context, state, dispatch_binding)
