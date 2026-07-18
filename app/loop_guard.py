from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from .planner import ExecutionPlan


@dataclass(frozen=True)
class ToolCallDecision:
    allowed: bool
    reason_code: str | None
    message: str | None
    signature_hash: str


class ToolLoopGuard:
    def __init__(self, plan: ExecutionPlan):
        self.plan = plan
        self.total_calls = 0
        self.tool_calls: Counter[str] = Counter()
        self.signature_calls: Counter[str] = Counter()
        self.evidence_fingerprints: set[str] = set()
        self.blocked_calls: Counter[str] = Counter()
        self.consecutive_no_progress_rounds = 0
        self.round_had_progress = False
        self.round_allowed_calls = 0
        self.stop_reason: str | None = None
        self.stop_message: str | None = None
        if plan.status == "clarification_required":
            self.enter_synthesis(
                "clarification_required",
                "执行计划缺少必要输入，必须先向用户澄清，禁止调用工具。",
            )

    @property
    def force_synthesis(self) -> bool:
        return self.stop_reason is not None

    @property
    def max_model_iterations(self) -> int:
        return max(1, self.plan.budget.max_model_iterations)

    def begin_round(self) -> None:
        self.round_had_progress = False
        self.round_allowed_calls = 0

    def enter_synthesis(self, reason_code: str, message: str) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason_code
            self.stop_message = message

    def _signature(self, tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
        canonical = json.dumps(
            {"tool": tool, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return canonical, digest

    def _blocked(self, code: str, message: str, signature_hash: str) -> ToolCallDecision:
        self.blocked_calls[code] += 1
        return ToolCallDecision(False, code, message, signature_hash)

    def check_call(self, tool: str, arguments: dict[str, Any]) -> ToolCallDecision:
        signature, signature_hash = self._signature(tool, arguments)
        if self.force_synthesis:
            return self._blocked(
                "synthesis_only",
                f"运行时守卫已进入仅综合模式：{self.stop_message}",
                signature_hash,
            )

        budget = self.plan.budget
        if budget.max_tool_calls <= 0:
            return self._blocked("tool_budget_disabled", "当前执行计划不允许调用工具。", signature_hash)
        if self.signature_calls[signature] >= budget.max_identical_parameter_calls:
            return self._blocked(
                "duplicate_arguments",
                "相同工具和参数已经调用过，重复调用不会产生新证据。",
                signature_hash,
            )
        if self.total_calls >= budget.max_tool_calls:
            self.enter_synthesis(
                "total_tool_budget_exhausted",
                f"工具调用已达到总预算 {budget.max_tool_calls} 次。",
            )
            return self._blocked("total_tool_budget_exhausted", self.stop_message or "工具总预算已用尽。", signature_hash)

        tool_limit = budget.per_tool_limits.get(tool, budget.per_tool_limits.get("*", budget.max_tool_calls))
        if self.tool_calls[tool] >= tool_limit:
            return self._blocked(
                "per_tool_budget_exhausted",
                f"{tool} 已达到单工具预算 {tool_limit} 次，请改用已有证据或其他计划步骤。",
                signature_hash,
            )

        self.total_calls += 1
        self.tool_calls[tool] += 1
        self.signature_calls[signature] += 1
        self.round_allowed_calls += 1
        return ToolCallDecision(True, None, None, signature_hash)

    def record_result(self, tool: str, result: Any, success: bool) -> bool:
        if not success or result is None or result == [] or result == {} or result == "":
            return False
        canonical = json.dumps(
            {"tool": tool, "result": result},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
        if fingerprint in self.evidence_fingerprints:
            return False
        self.evidence_fingerprints.add(fingerprint)
        self.round_had_progress = True
        return True

    def finish_round(self) -> bool:
        if self.round_had_progress:
            self.consecutive_no_progress_rounds = 0
        else:
            self.consecutive_no_progress_rounds += 1

        budget = self.plan.budget
        if budget.max_tool_calls > 0 and self.total_calls >= budget.max_tool_calls:
            self.enter_synthesis(
                "total_tool_budget_exhausted",
                f"工具调用已达到总预算 {budget.max_tool_calls} 次。",
            )
        if self.consecutive_no_progress_rounds >= budget.max_no_progress_rounds:
            self.enter_synthesis(
                "no_progress",
                f"连续 {self.consecutive_no_progress_rounds} 轮没有获得新证据。",
            )
        return self.force_synthesis

    def reserve_final_iteration(self) -> None:
        self.enter_synthesis(
            "final_synthesis_iteration",
            "已进入最后一个模型轮次，只允许基于现有证据组织答案。",
        )

    def synthesis_instruction(self) -> str:
        return (
            "runtime_guard 已停止继续调用工具。"
            f"原因：{self.stop_message or '执行预算或进展条件已触发。'}"
            f"已执行 {self.total_calls}/{self.plan.budget.max_tool_calls} 次工具调用，"
            f"获得 {len(self.evidence_fingerprints)} 组新证据。"
            "请仅基于已有工具结果给出结论，明确证据缺口、未完成步骤和需要用户补充的信息。"
        )

    def termination_answer(self) -> str:
        return (
            "执行路径已由运行时守卫终止。\n\n"
            f"原因：{self.stop_message or '达到运行限制。'}\n\n"
            f"已执行 {self.total_calls} 次工具调用，获得 {len(self.evidence_fingerprints)} 组新证据。"
            "模型未在允许轮次内形成最终答案，请缩小问题范围或补充缺失条件后重试。"
        )

    def summary(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan.plan_id,
            "enforcement": self.plan.budget.enforcement,
            "budget": asdict(self.plan.budget),
            "total_calls": self.total_calls,
            "per_tool_calls": dict(self.tool_calls),
            "unique_evidence_results": len(self.evidence_fingerprints),
            "blocked_calls": sum(self.blocked_calls.values()),
            "blocked_reasons": dict(self.blocked_calls),
            "consecutive_no_progress_rounds": self.consecutive_no_progress_rounds,
            "force_synthesis": self.force_synthesis,
            "stop_reason": self.stop_reason,
            "stop_message": self.stop_message,
        }
