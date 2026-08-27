"""Small, side-effect-free contracts for an Agent run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeAlias


ProgressCallback = Callable[[dict], Any]
AgentRunResult: TypeAlias = dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """The legacy Agent implementation input without normalization or copies."""

    question: str
    history: list[dict] | None
    run_id: str
    thinking: bool = False


@dataclass(slots=True)
class AgentRunLifecycle:
    """Timing state owned by the public Agent run entrypoint."""

    started_monotonic: float
    started_at: str
    first_answer_delta_monotonic: float | None = None

    def observe_progress(self, event: dict, now: float) -> None:
        if (
            event.get("event") == "answer_delta"
            and self.first_answer_delta_monotonic is None
        ):
            self.first_answer_delta_monotonic = now

    def duration_ms(self, completed_monotonic: float) -> float:
        return round((completed_monotonic - self.started_monotonic) * 1000, 1)

    def first_token_ms(self) -> float | None:
        if self.first_answer_delta_monotonic is None:
            return None
        return round(
            (self.first_answer_delta_monotonic - self.started_monotonic) * 1000,
            1,
        )


@dataclass(frozen=True, slots=True)
class ContextStageResult:
    """Context-stage values passed unchanged to routing."""

    resolution: Any
    usage: dict
    direct_route: Any
    selected_model_id: str


@dataclass(frozen=True, slots=True)
class RoutingStageResult:
    """Routing-stage values passed unchanged to planning and execution."""

    analysis_question: str
    intent_route: Any
    turn_decision: Any
    started_monotonic: float


@dataclass(frozen=True, slots=True)
class PlanningStageResult:
    """Planning-stage values passed unchanged to execution."""

    playbook_selection: Any
    playbook_payload: dict
    execution_plan: Any
    plan_payload: dict


@dataclass(frozen=True, slots=True)
class PreparationResult:
    """The complete pre-tool preparation result without domain-object copies."""

    context: ContextStageResult
    routing: RoutingStageResult
    planning: PlanningStageResult
