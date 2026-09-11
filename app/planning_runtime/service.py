from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..manufacturing.playbooks import PlaybookSelection
from ..intent_runtime.contracts import IntentRoute
from .contracts import ExecutionPlan, PlanBudget
from .queries import _resolved_inputs
from .scope import _analysis_scope_contract
from .steps import _empty_budget, _generic_budget, _ready_steps


def _plan_id(question: str, route: IntentRoute, selection: PlaybookSelection) -> str:
    playbook = selection.selected_playbook
    identity = {
        "question": " ".join(question.split()),
        "route": route.to_dict(),
        "playbook_id": playbook.playbook_id if playbook else None,
        "playbook_version": playbook.playbook_version if playbook else None,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"plan-{digest}"


def create_execution_plan(
    question: str,
    route: IntentRoute,
    selection: PlaybookSelection,
) -> ExecutionPlan:
    plan_id = _plan_id(question, route, selection)
    playbook = selection.selected_playbook
    scope_contract = _analysis_scope_contract(route)
    if route.scope_resolution.scope_type == "product" and route.intent == "fab_diagnostic":
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="clarification_required",
            reason="产品范围无法由当前综合诊断的全部工具一致过滤，必须先确认分析目标。",
            route_intent=route.intent,
            playbook_id=playbook.playbook_id if playbook else None,
            playbook_version=playbook.playbook_version if playbook else None,
            scope_contract=scope_contract,
            required_evidence_ids=(),
            steps=(),
            budget=_empty_budget(),
            missing_inputs=("product_analysis_scope",),
            clarification_questions=(
                "已识别产品范围。请确认只分析该产品的良率和周期，或补充需要关联的具体制程。",
            ),
        )
    if selection.status == "clarification_required" or route.intent == "unknown" or route.clarification_needed:
        if route.scope_resolution.clarification_needed:
            missing_inputs = ("manufacturing_scope",)
            reason = "Router 检测到无法映射的制造范围，确认范围前不得执行工具。"
        elif route.intent == "capability_excursion" and not route.process_steps:
            missing_inputs = ("process_step",)
            reason = "Domain Playbook 的必需输入尚不完整。"
        elif selection.status == "clarification_required":
            missing_inputs = ("primary_intent",)
            reason = "路由匹配多个 Domain Playbook，必须先确认主分析目标。"
        else:
            missing_inputs = ("primary_intent",)
            reason = "Router 未识别明确分析目标，必须先补充问题范围。"
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="clarification_required",
            reason=reason,
            route_intent=route.intent,
            playbook_id=None,
            playbook_version=None,
            scope_contract=scope_contract,
            required_evidence_ids=(),
            steps=(),
            budget=_empty_budget(),
            missing_inputs=missing_inputs,
            clarification_questions=route.clarification_questions,
        )
    if playbook is None:
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="unsupported",
            reason="当前 Planner 仅实例化六类 Domain Playbook；该问题继续使用通用 Agent 路径。",
            route_intent=route.intent,
            playbook_id=None,
            playbook_version=None,
            scope_contract=scope_contract,
            required_evidence_ids=(),
            steps=(),
            budget=_generic_budget(),
            missing_inputs=(),
            clarification_questions=route.clarification_questions,
        )

    resolved, missing = _resolved_inputs(question, route, playbook)
    scope_contract = _analysis_scope_contract(route, resolved)
    if missing:
        questions = list(route.clarification_questions)
        labels = {
            "process_step": "请指定要分析的制程站点。",
            "lot_id": "请提供要追踪的完整批次编号。",
            "time_range": "请提供分析起止日期。",
            "query": "请说明要查询的规范主题。",
        }
        for name in missing:
            question_text = labels.get(name, f"请补充 {name}。")
            if question_text not in questions:
                questions.append(question_text)
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="clarification_required",
            reason="Domain Playbook 的必需输入尚不完整。",
            route_intent=route.intent,
            playbook_id=playbook.playbook_id,
            playbook_version=playbook.playbook_version,
            scope_contract=scope_contract,
            required_evidence_ids=tuple(
                item.evidence_id for item in playbook.evidence_requirements if item.required
            ),
            steps=(),
            budget=_empty_budget(),
            missing_inputs=missing,
            clarification_questions=tuple(questions),
        )

    steps = _ready_steps(question, route, playbook, resolved)
    planned_calls = len(steps)
    planned_per_tool = Counter(step.tool for step in steps)
    return ExecutionPlan(
        plan_id=plan_id,
        schema_version="1.1",
        planner_version="1.1.0",
        status="ready",
        reason="已将路由范围和 Domain Playbook 证据模板实例化为确定性工具计划。",
        route_intent=route.intent,
        playbook_id=playbook.playbook_id,
        playbook_version=playbook.playbook_version,
        scope_contract=scope_contract,
        required_evidence_ids=tuple(
            item.evidence_id for item in playbook.evidence_requirements if item.required
        ),
        steps=steps,
        budget=PlanBudget(
            planned_tool_calls=planned_calls,
            max_tool_calls=min(16, planned_calls + 2),
            max_model_iterations=6,
            max_rows_per_call=100,
            per_tool_limits={tool: count + 1 for tool, count in planned_per_tool.items()},
            max_identical_parameter_calls=1,
            max_no_progress_rounds=2,
        ),
        missing_inputs=(),
        clarification_questions=(),
    )


def planner_system_message(plan: ExecutionPlan) -> str:
    return (
        "以下 execution_plan 是 Router 与 Domain Playbook 的确定性实例化结果，不是已执行证据。"
        "status=ready 时按 depends_on 满足依赖，优先完成 required=true 的步骤，并使用给定参数。"
        "任一步无法满足 success_criteria 时必须报告证据缺口。"
        "budget 由运行时守卫强制执行，不得超过总调用、单工具、相同参数和无进展轮次限制。"
        "status=clarification_required 时先提出 clarification_questions，不调用工具。"
        "status=unsupported 时继续遵守通用 Agent 规则。\n"
        f"execution_plan={plan.to_prompt()}"
    )
