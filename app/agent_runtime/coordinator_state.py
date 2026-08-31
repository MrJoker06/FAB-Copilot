"""Invocation-local state shared by coordinator stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
