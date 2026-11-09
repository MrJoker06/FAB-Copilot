"""Single mutable run state for one model/tool loop execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...evidence.answer_synthesizer import AnswerContract
    from ...evidence.validator import EvidenceValidation
    from .agent_loop import AgentLoopContext
    from .loop_dispatch import LoopDispatchBinding


@dataclass(slots=True)
class LoopRunState:
    """The loop's only copy of the facts it rewrites during one run.

    Values are snapshotted from the context once at run start. The context is
    written back only on the dispatched path, and only where the loop has
    always done so (after each tool round and before building a result).
    """

    evidence_validation: EvidenceValidation
    answer_contract: AnswerContract
    knowledge_fallback: dict[str, Any]
    fallback_announced: bool
    applied_synthesis_reason: str | None
    health: dict[str, Any]
    thinking_answer_effective: bool = False

    @classmethod
    def from_context(cls, context: AgentLoopContext) -> LoopRunState:
        return cls(
            evidence_validation=context.evidence_validation,
            answer_contract=context.answer_contract,
            knowledge_fallback=context.knowledge_fallback,
            fallback_announced=context.fallback_announced,
            applied_synthesis_reason=context.applied_synthesis_reason,
            health=context.health,
        )

    def sync_to_context(self, context: AgentLoopContext) -> None:
        context.evidence_validation = self.evidence_validation
        context.answer_contract = self.answer_contract
        context.knowledge_fallback = self.knowledge_fallback
        context.fallback_announced = self.fallback_announced
        context.applied_synthesis_reason = self.applied_synthesis_reason
        context.health = self.health

    def build_result(
        self,
        context: AgentLoopContext,
        dispatch_binding: LoopDispatchBinding | None,
        answer: str,
        report: Any,
    ) -> dict:
        if dispatch_binding is not None:
            self.sync_to_context(context)
        result = context.build_result(answer, report)
        result["thinking_policy"]["answer_effective"] = self.thinking_answer_effective
        return result


def add_usage(total_usage: dict[str, int], usage: dict) -> None:
    for key in total_usage:
        total_usage[key] += int(usage.get(key, 0) or 0)
