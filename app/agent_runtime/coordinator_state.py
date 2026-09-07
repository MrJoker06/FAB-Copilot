"""Invocation-local state shared by coordinator stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CoordinatorStateView:
    """Named live view over one run's single mutable state object."""

    def __init__(self, state: "CoordinatorRunState", names: tuple[str, ...]):
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_names", frozenset(names))

    def __getattr__(self, name: str) -> Any:
        if name in self._names:
            return getattr(self._state, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name not in self._names:
            raise AttributeError(name)
        setattr(self._state, name, value)


@dataclass
class CoordinatorRunState:
    """Mutable state owned by exactly one Agent run."""

    question: str
    history: list[dict] | None
    run_id: str
    progress: Any
    thinking: bool
    settings: Any = None
    preparation: Any = None
    context_resolution: Any = None
    context_usage: dict[str, Any] = field(default_factory=dict)
    health_enabled: bool = False
    selected_model_id: str | None = None
    analysis_question: str = ""
    intent_route: Any = None
    turn_decision: Any = None
    route_payload: dict[str, Any] = field(default_factory=dict)
    playbook_selection: Any = None
    playbook_payload: dict[str, Any] = field(default_factory=dict)
    selected_playbook: Any = None
    execution_plan: Any = None
    plan_payload: dict[str, Any] = field(default_factory=dict)
    thinking_answer_effective: bool = False
    loop_guard: Any = None
    evidence_observations: list[Any] = field(default_factory=list)
    evidence_validation: Any = None
    answer_contract: Any = None
    connection: Any = None
    model_health: dict[str, Any] = field(default_factory=dict)
    main_recovery_trial: bool = False
    messages: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)
    endpoint: str = ""
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
            "messages", "endpoint", "total_usage", "knowledge_fallback", "fallback_announced",
            "retrieval_decision_payload", "thinking_answer_effective",
        ))
        self.result_state = CoordinatorStateView(self, (
            "trace", "sources", "evidence_observations", "evidence_validation", "answer_contract",
            "total_usage", "knowledge_fallback", "fallback_announced", "applied_synthesis_reason", "health",
        ))
