"""Typed ports for coordinator dependency groups, run state and event channels.

Concrete domain types are imported only for type checking, so importing this
module loads nothing beyond the standard library.  Parameters which callers
always pass positionally are declared positional-only, which lets legacy
facades and test doubles satisfy a port whatever they name those parameters.
Each port lists only the arguments its runtime consumers actually pass.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    from ..conversation.turn_decision import TurnDecision
    from ..evidence.answer_synthesizer import (
        AnswerContract,
        AnswerSynthesisReport,
        SynthesizedAnswer,
    )
    from ..evidence.validator import EvidenceObservation, EvidenceValidation
    from ..intent_runtime.contracts import IntentRoute
    from ..knowledge.decision import RetrievalDecision
    from ..manufacturing.playbooks import DomainPlaybook, PlaybookSelection
    from ..memory_system.contracts import ContextResolution
    from ..model_gateway.gateway import ModelSessionPort
    from ..planning_runtime.contracts import ExecutionPlan
    from .contracts import PreparationResult, ProgressCallback
    from .coordinator_state import CoordinatorRunState
    from .execution.agent_loop import AgentLoopContext
    from .execution.loop_dispatch import LoopDispatchBinding
    from .execution.loop_guard import ToolLoopGuard
    from .execution.ready_dispatch import ReadyDispatchBinding
    from .preparation.pipeline import (
        PreparationDependencies as AgentPreparationDependencies,
    )
    from .synthesis.fallback import PrecomputedTools

JsonObject: TypeAlias = dict[str, Any]
ObservationList: TypeAlias = list["EvidenceObservation"]

# Configuration views ----------------------------------------------------------
# The runtime may not import the configuration module; these read-only views
# list the fields it reads, and ``core.settings.Settings`` / ``ModelConnection``
# satisfy them structurally.  Fields read through ``getattr`` with a default
# (``chat_template_compat``, ``model_context_timeout_seconds``) stay optional.


@runtime_checkable
class RuntimeModelConnection(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    @property
    def api_key(self) -> str: ...


@runtime_checkable
class RuntimeSettings(Protocol):
    @property
    def model_connection(self) -> RuntimeModelConnection: ...

    @property
    def api_timeout_seconds(self) -> float: ...

    @property
    def model_max_retries(self) -> int: ...

    @property
    def model_retry_base_seconds(self) -> float: ...

    @property
    def model_circuit_failure_threshold(self) -> int: ...

    @property
    def model_circuit_cooldown_seconds(self) -> int: ...

    @property
    def model_circuit_recovery_lease_seconds(self) -> int: ...


# Event channels -------------------------------------------------------------


class AuditEmitter(Protocol):
    """``app.telemetry.audit.emit``: one synchronous audit record per call."""

    def __call__(
        self,
        event: str,
        run_id: str,
        /,
        *,
        full_content: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> None: ...


class ProgressSink(Protocol):
    """The legacy ``notify(progress, event)`` UI progress channel."""

    async def __call__(
        self, progress: ProgressCallback | None, event: dict, /
    ) -> None: ...


class AnswerStreamer(Protocol):
    """The legacy ``stream_answer(progress, answer)`` answer-delta channel."""

    async def __call__(
        self, progress: ProgressCallback | None, answer: str, /
    ) -> None: ...


EvidenceValidationEmitter: TypeAlias = Callable[[str, int, JsonObject], None]
AnswerSynthesisEmitter: TypeAlias = Callable[[str, "AnswerSynthesisReport"], None]

# Preparation ----------------------------------------------------------------

Clock: TypeAlias = Callable[[], float]
SettingsProvider: TypeAlias = Callable[[], RuntimeSettings]
SettingsResolver: TypeAlias = Callable[[RuntimeSettings], RuntimeSettings]
AgentPreparationFactory: TypeAlias = Callable[[], "AgentPreparationDependencies"]


class AgentRunPreparer(Protocol):
    async def __call__(
        self,
        question: str,
        history: list[dict] | None,
        settings: RuntimeSettings,
        run_id: str,
        progress: ProgressCallback | None,
        thinking: bool,
        context_started: float,
        /,
        *,
        deps: AgentPreparationDependencies,
    ) -> PreparationResult: ...


class EvidenceValidator(Protocol):
    def __call__(
        self,
        plan: ExecutionPlan,
        playbook: DomainPlaybook | None,
        observations: list[EvidenceObservation],
        /,
    ) -> EvidenceValidation: ...


class AnswerContractFactory(Protocol):
    def __call__(
        self,
        validation: EvidenceValidation,
        sources: list[JsonObject] | None = None,
        /,
        *,
        allow_model_knowledge_fallback: bool = False,
        question: str = "",
        resolved_question: str = "",
        extra_limitations: Sequence[str] = (),
    ) -> AnswerContract: ...


class OfflineAnswerer(Protocol):
    def __call__(
        self,
        question: str,
        intent_route: IntentRoute,
        playbook_selection: PlaybookSelection,
        execution_plan: ExecutionPlan,
        loop_guard: ToolLoopGuard,
        context_resolution: ContextResolution | None = None,
        turn_decision: TurnDecision | None = None,
        runtime_context: dict | None = None,
        run_id: str | None = None,
        /,
        *,
        fallback_reason: str = "missing_api_key",
        precomputed_tools: PrecomputedTools | None = None,
    ) -> JsonObject: ...


# Model health and error classification --------------------------------------


class ModelHealthReader(Protocol):
    def __call__(self, model_id: str, /) -> dict: ...


class ModelCallClaimer(Protocol):
    def __call__(
        self, model_id: str, /, *, cooldown_seconds: int, lease_seconds: int
    ) -> tuple[bool, dict, str | None]: ...


class ModelSuccessRecorder(Protocol):
    def __call__(self, model_id: str, /) -> tuple[dict, str | None]: ...


class ModelFailureRecorder(Protocol):
    def __call__(
        self, model_id: str, category: str, /, *, threshold: int, cooldown_seconds: int
    ) -> tuple[dict, str | None]: ...


ModelErrorPredicate: TypeAlias = Callable[[Exception], bool]
ModelErrorClassifier: TypeAlias = Callable[[Exception], str]
ModelRetryDelay: TypeAlias = Callable[[float, int, Exception], float]

# Availability and Ready synthesis -------------------------------------------

ReadyPlanOutcome: TypeAlias = tuple[
    list[JsonObject], ObservationList, dict[str, JsonObject]
]


class ReadyPlanExecutor(Protocol):
    async def __call__(
        self,
        plan: ExecutionPlan,
        loop_guard: ToolLoopGuard,
        run_id: str,
        progress: ProgressCallback | None,
        /,
        *,
        dispatch_binding: ReadyDispatchBinding | None = None,
    ) -> ReadyPlanOutcome: ...


ReadySynthesisFallback: TypeAlias = Callable[
    ["EvidenceValidation", "AnswerContract", ObservationList, str],
    "SynthesizedAnswer",
]
ReadySynthesisMessages: TypeAlias = Callable[
    [str, "ExecutionPlan", "EvidenceValidation", "AnswerContract", ObservationList],
    list[dict[str, str]],
]
ReadyAssistantSynthesizer: TypeAlias = Callable[
    [
        JsonObject,
        "AnswerContract",
        list[JsonObject],
        "EvidenceValidation",
        ObservationList,
        str,
    ],
    "SynthesizedAnswer",
]


class ReadyUnavailableResultBuilder(Protocol):
    def __call__(
        self,
        answer: str,
        synthesis_report: AnswerSynthesisReport,
        /,
        *,
        trace: list[dict],
        route_payload: dict,
        playbook_payload: dict,
        plan_payload: dict,
        loop_guard: ToolLoopGuard,
        evidence_validation: EvidenceValidation,
        answer_contract: AnswerContract,
        context_resolution: ContextResolution,
        thinking: bool,
        turn_decision: TurnDecision,
        selected_model_id: str,
        fallback_reason: str,
        model_health: JsonObject,
        usage: dict[str, int],
    ) -> JsonObject: ...


class ReadySynthesisRequester(Protocol):
    async def __call__(
        self,
        session: ModelSessionPort,
        connection: RuntimeModelConnection,
        settings: RuntimeSettings,
        messages: list[dict[str, str]],
        run_id: str,
        thinking: bool,
        retry_budget: int,
        /,
    ) -> tuple[JsonObject, JsonObject, str | None, JsonObject]: ...


# Model messages and general knowledge ---------------------------------------

ContextMessageBuilder: TypeAlias = Callable[["ContextResolution"], str]
RouteMessageBuilder: TypeAlias = Callable[["IntentRoute"], str]
PlaybookMessageBuilder: TypeAlias = Callable[["PlaybookSelection"], str]
PlanMessageBuilder: TypeAlias = Callable[["ExecutionPlan"], str]
ValidationMessageBuilder: TypeAlias = Callable[["EvidenceValidation"], str]
ContractMessageBuilder: TypeAlias = Callable[["AnswerContract"], str]
RetrievalMessageBuilder: TypeAlias = Callable[
    ["RetrievalDecision", list[JsonObject]], str
]
KnowledgeFallbackStateBuilder: TypeAlias = Callable[
    ["IntentRoute", ObservationList, dict[str, JsonObject]], JsonObject
]
StageMemoryMessages: TypeAlias = Callable[
    [str, list[dict] | None], list[dict[str, str]]
]


class GeneralKnowledgePrefetcher(Protocol):
    async def __call__(
        self,
        question: str,
        run_id: str,
        loop_guard: ToolLoopGuard,
        observations: list[EvidenceObservation],
        trace: list[JsonObject],
        sources: dict[str, JsonObject],
        progress: ProgressCallback | None,
        /,
        *,
        dispatch_binding: LoopDispatchBinding | None = None,
    ) -> RetrievalDecision: ...


# Agent loop -----------------------------------------------------------------

ToolArgumentParser: TypeAlias = Callable[[str], tuple[JsonObject, Exception | None]]
RegisteredToolExecutor: TypeAlias = Callable[[str, JsonObject], object]
KnowledgeResultPredicate: TypeAlias = Callable[[str, JsonObject], bool]
AnswerNormalizer: TypeAlias = Callable[[str], str]
DisclosurePredicate: TypeAlias = Callable[[str], bool]
ProviderRequestOptions: TypeAlias = Callable[[str, bool], JsonObject]
AssistantAuditor: TypeAlias = Callable[[JsonObject | None], JsonObject]
LoopResultBuilder: TypeAlias = Callable[[str, "AnswerSynthesisReport"], JsonObject]
NativeFallback: TypeAlias = Callable[[], Awaitable[JsonObject]]


class ResultBuilder(Protocol):
    def __call__(
        self,
        answer: str,
        synthesis_report: AnswerSynthesisReport,
        /,
        *,
        trace: list[dict],
        sources: dict[str, dict],
        intent_route: IntentRoute,
        connection: RuntimeModelConnection,
        total_usage: dict[str, int],
        route_payload: dict,
        playbook_payload: dict,
        plan_payload: dict,
        loop_guard: ToolLoopGuard,
        evidence_validation: EvidenceValidation,
        answer_contract: AnswerContract,
        context_resolution: ContextResolution,
        knowledge_fallback: dict,
        retrieval_decision_payload: dict,
        thinking: bool,
        thinking_answer_effective: bool,
        turn_decision: TurnDecision,
    ) -> JsonObject: ...


class AgentLoopRunner(Protocol):
    async def __call__(self, context: AgentLoopContext, /) -> JsonObject: ...


class LegacyAnswerSynthesizer(Protocol):
    def __call__(
        self,
        answer: str,
        contract: AnswerContract,
        sources: list[JsonObject] | None = None,
        /,
        *,
        repair_events: tuple[JsonObject, ...] = (),
    ) -> SynthesizedAnswer: ...


class SubmissionSynthesizer(Protocol):
    def __call__(
        self,
        payload: JsonObject,
        contract: AnswerContract,
        sources: list[JsonObject] | None = None,
        /,
        *,
        status: str = "structured",
        repair_events: tuple[JsonObject, ...] = (),
    ) -> SynthesizedAnswer: ...


class SynthesisCorrectionRequester(Protocol):
    async def __call__(
        self,
        session: ModelSessionPort,
        connection: RuntimeModelConnection,
        messages: list[dict[str, str]],
        invalid_arguments: str,
        completion_token_budget: int,
        wall_time_seconds: float,
        run_id: str,
        iteration: int,
        /,
    ) -> tuple[JsonObject | None, JsonObject, str | None, str]: ...


# Per-run native tool assembly -----------------------------------------------


class ToolRunBindings(Protocol):
    """Per-run dispatcher bindings; ``None`` selects the historical path."""

    @property
    def ready(self) -> ReadyDispatchBinding | None: ...

    @property
    def loop(self) -> LoopDispatchBinding | None: ...


class ToolRunFactory(Protocol):
    def __call__(
        self,
        *,
        settings: RuntimeSettings,
        plan: ExecutionPlan,
        guard: ToolLoopGuard,
        run_id: str,
    ) -> ToolRunBindings: ...


class OfflineToolRunner(Protocol):
    async def __call__(
        self, state: CoordinatorRunState, /
    ) -> PrecomputedTools | None: ...


__all__ = [
    "AgentLoopRunner",
    "AgentPreparationFactory",
    "AgentRunPreparer",
    "AnswerContractFactory",
    "AnswerNormalizer",
    "AnswerStreamer",
    "AnswerSynthesisEmitter",
    "AssistantAuditor",
    "AuditEmitter",
    "Clock",
    "ContextMessageBuilder",
    "ContractMessageBuilder",
    "DisclosurePredicate",
    "EvidenceValidationEmitter",
    "EvidenceValidator",
    "GeneralKnowledgePrefetcher",
    "JsonObject",
    "KnowledgeFallbackStateBuilder",
    "KnowledgeResultPredicate",
    "LegacyAnswerSynthesizer",
    "LoopResultBuilder",
    "ModelCallClaimer",
    "ModelErrorClassifier",
    "ModelErrorPredicate",
    "ModelFailureRecorder",
    "ModelHealthReader",
    "ModelRetryDelay",
    "ModelSuccessRecorder",
    "NativeFallback",
    "ObservationList",
    "OfflineAnswerer",
    "OfflineToolRunner",
    "PlanMessageBuilder",
    "PlaybookMessageBuilder",
    "ProgressSink",
    "ProviderRequestOptions",
    "ReadyAssistantSynthesizer",
    "ReadyPlanExecutor",
    "ReadyPlanOutcome",
    "ReadySynthesisFallback",
    "ReadySynthesisMessages",
    "ReadySynthesisRequester",
    "ReadyUnavailableResultBuilder",
    "RegisteredToolExecutor",
    "ResultBuilder",
    "RetrievalMessageBuilder",
    "RouteMessageBuilder",
    "RuntimeModelConnection",
    "RuntimeSettings",
    "SettingsProvider",
    "SettingsResolver",
    "StageMemoryMessages",
    "SubmissionSynthesizer",
    "SynthesisCorrectionRequester",
    "ToolArgumentParser",
    "ToolRunBindings",
    "ToolRunFactory",
    "ValidationMessageBuilder",
]
