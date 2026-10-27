"""Adapter exposing the existing LoopGuard as the dispatcher budget protocol."""

from __future__ import annotations

from collections.abc import Mapping

from ..tools.dispatch_contracts import BudgetDecision
from .loop_guard import ToolLoopGuard


class LoopGuardToolBudget:
    """Do not duplicate LoopGuard accounting; delegate every decision to it."""

    def __init__(self, guard: ToolLoopGuard) -> None:
        if not isinstance(guard, ToolLoopGuard):
            raise TypeError("guard must be a ToolLoopGuard")
        self.guard = guard

    def claim(
        self, name: str, decoded_arguments: Mapping[str, object]
    ) -> BudgetDecision:
        decision = self.guard.check_call(name, dict(decoded_arguments))
        if decision.allowed:
            return BudgetDecision(True)
        return BudgetDecision(
            False,
            decision.reason_code or "BUDGET",
            decision.message or "Tool budget blocked the call.",
        )

    def record_result(self, name: str, data: object, success: bool) -> bool:
        return self.guard.record_result(name, data, success)
