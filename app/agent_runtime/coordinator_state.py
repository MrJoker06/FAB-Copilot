"""Invocation-local state shared by coordinator stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..conversation.turn_decision import TurnDecision
    from ..evidence.answer_synthesizer import AnswerContract
    from ..evidence.validator import EvidenceObservation, EvidenceValidation
    from ..intent_runtime.contracts import IntentRoute
    from ..manufacturing.playbooks import DomainPlaybook, PlaybookSelection
    from ..memory_system.contracts import ContextResolution
    from ..planning_runtime.contracts import ExecutionPlan
    from .contracts import PreparationResult, ProgressCallback
    from .execution.loop_guard import ToolLoopGuard
    from .ports import RuntimeModelConnection, RuntimeSettings, ToolRunBindings


class CoordinatorStateView:
    """Named live view over one run's single mutable state object."""

    def __init__(self, state: "CoordinatorRunState", names: tuple[str, ...]):
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_names", frozenset(names))

    def __getattr__(self, name: str) -> Any:
        if name in self._names:
            return getattr(self._state, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self._names:
            raise AttributeError(name)
        setattr(self._state, name, value)


@dataclass
class CoordinatorRunState:
    """Mutable state owned by exactly one Agent run."""

    question: str
    history: list[dict] | None
    run_id: str
    progress: ProgressCallback | None
    thinking: bool
    settings: RuntimeSettings | None = None
    preparation: PreparationResult | None = None
    context_resolution: ContextResolution | None = None
    context_usage: dict[str, Any] = field(default_factory=dict)
    health_enabled: bool = False
    selected_model_id: str | None = None
    analysis_question: str = ""
    intent_route: IntentRoute | None = None
    turn_decision: TurnDecision | None = None
    route_payload: dict[str, Any] = field(default_factory=dict)
    playbook_selection: PlaybookSelection | None = None
    playbook_payload: dict[str, Any] = field(default_factory=dict)
    selected_playbook: DomainPlaybook | None = None
    execution_plan: ExecutionPlan | None = None
    plan_payload: dict[str, Any] = field(default_factory=dict)
    thinking_answer_effective: bool = False
    loop_guard: ToolLoopGuard | None = None
    tool_run: ToolRunBindings | None = None
    evidence_observations: list[EvidenceObservation] = field(default_factory=list)
    evidence_validation: EvidenceValidation | None = None
    answer_contract: AnswerContract | None = None
    connection: RuntimeModelConnection | None = None
    model_health: dict[str, Any] = field(default_factory=dict)
    main_recovery_trial: bool = False
    messages: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)
    total_usage: dict[str, int] = field(default_factory=dict)
    applied_synthesis_reason: str | None = None
    health: dict[str, Any] = field(default_factory=dict)
    knowledge_fallback: dict[str, Any] = field(default_factory=dict)
    fallback_announced: bool = False
    retrieval_decision_payload: dict[str, Any] = field(default_factory=dict)
    preparation_state: CoordinatorStateView = field(init=False, repr=False)
    availability_state: CoordinatorStateView = field(init=False, repr=False)
    model_state: CoordinatorStateView = field(init=False, repr=False)
    result_state: CoordinatorStateView = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Views group stage concerns without introducing parallel mutable facts.
        self.preparation_state = CoordinatorStateView(self, (
            "settings", "preparation", "context_resolution", "context_usage", "health_enabled",
            "selected_model_id", "analysis_question", "intent_route", "turn_decision", "route_payload",
            "playbook_selection", "playbook_payload", "selected_playbook", "execution_plan",
            "plan_payload", "loop_guard", "evidence_validation", "answer_contract",
        ))
        self.availability_state = CoordinatorStateView(self, (
            "connection", "model_health", "main_recovery_trial", "health",
        ))
        self.model_state = CoordinatorStateView(self, (
            "messages", "total_usage", "knowledge_fallback", "fallback_announced",
            "retrieval_decision_payload", "thinking_answer_effective",
        ))
        self.result_state = CoordinatorStateView(self, (
            "trace", "sources", "evidence_observations", "evidence_validation", "answer_contract",
            "total_usage", "knowledge_fallback", "fallback_announced", "applied_synthesis_reason", "health",
        ))
