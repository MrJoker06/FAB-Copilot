from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

PlanStatus = Literal["ready", "clarification_required", "unsupported"]
ScopeRole = Literal["primary", "context_only"]


@dataclass(frozen=True)
class PlanBudget:
    planned_tool_calls: int
    max_tool_calls: int
    max_model_iterations: int
    max_rows_per_call: int
    per_tool_limits: dict[str, int]
    max_identical_parameter_calls: int
    max_no_progress_rounds: int
    enforcement: Literal["runtime"] = "runtime"


@dataclass(frozen=True)
class AnalysisScopeContract:
    primary_scope_type: str
    primary_scope_ids: tuple[str, ...]
    primary_scope_labels: tuple[str, ...]
    context_only_tools: tuple[str, ...]


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    title: str
    tool: str
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]
    evidence_ids: tuple[str, ...]
    depends_on: tuple[str, ...]
    required: bool
    success_criteria: tuple[str, ...]
    estimated_result_limit: int
    scope_role: ScopeRole
    # Declarative metadata consumed by evidence validation; it never contains
    # a process-name-specific rule.
    semantic_id: str = "unknown"
    grain: str = "unknown"
    filter_provenance: str = "planner"
    evidence_kind: str = "unknown"
    evidence_scope: dict[str, tuple[str, ...]] | None = None
    evidence_start: str | None = None
    evidence_end: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    schema_version: str
    planner_version: str
    status: PlanStatus
    reason: str
    route_intent: str
    playbook_id: str | None
    playbook_version: str | None
    scope_contract: AnalysisScopeContract
    required_evidence_ids: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    budget: PlanBudget
    missing_inputs: tuple[str, ...]
    clarification_questions: tuple[str, ...]

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, default=str))

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
