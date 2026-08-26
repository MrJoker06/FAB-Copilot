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
