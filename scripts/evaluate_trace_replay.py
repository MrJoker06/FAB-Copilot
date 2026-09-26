"""Replay the QA-004 sanitized trace matrix without a model or network."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = PROJECT_DIR / "evaluations" / "trace_replay_matrix.json"
DEFAULT_REPORT = PROJECT_DIR / "runtime" / "quality" / "trace_replay_report.json"
sys.path.insert(0, str(PROJECT_DIR))

from app.evidence.answer_synthesizer import (  # noqa: E402
    create_answer_contract,
    synthesize_legacy_answer,
    synthesize_submission,
)
from app.memory_system.context.resolver import (  # noqa: E402
    semantic_context_resolution,
    unresolved_context,
)
from app.conversation.decision_arbiter import arbitrate_decision, recover_active_flow  # noqa: E402
from app.manufacturing.playbooks import select_playbook  # noqa: E402
from app.evidence.validator import EvidenceObservation, validate_evidence  # noqa: E402
from app.intent_runtime.rules import INTENT_LABELS  # noqa: E402
from app.intent_runtime.routing import route_question  # noqa: E402
from app.knowledge.decision import required_scopes  # noqa: E402
from app.planning_runtime.service import create_execution_plan  # noqa: E402
from app.conversation.turn_decision import build_turn_decision  # noqa: E402


_REQUIRED_EXPECTED_FIELDS = {
    "route", "action", "plan_status", "primary_scope_type",
    "primary_scope_ids", "tool_path", "evidence_strength",
    "structured_submit", "model_calls", "business_tool_calls",
}
_FORBIDDEN_DATASET_KEYS = {
    "api_key", "authorization", "cookie", "password", "secret", "token",
    "raw_prompt", "reasoning_content", "chain_of_thought",
}


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("trace replay dataset schema_version must be 1.0")
    if payload.get("data_classification") != "synthetic_redacted":
        raise ValueError("trace replay dataset must be synthetic_redacted")
    policy = payload.get("execution_policy")
    if not isinstance(policy, dict) or any(policy.get(key) != 0 for key in (
        "network_calls", "real_model_calls", "model_business_tool_selection_calls",
    )):
        raise ValueError("trace replay execution policy must prohibit external calls")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("trace replay dataset requires cases")
    identifiers: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("every trace replay case requires an id")
        if case["id"] in identifiers:
            raise ValueError(f"duplicate trace replay case id: {case['id']}")
        identifiers.add(case["id"])
        expected = case.get("expected")
        if not isinstance(expected, dict) or _REQUIRED_EXPECTED_FIELDS - set(expected):
            raise ValueError(f"trace replay case {case['id']} has incomplete expectations")
    forbidden = sorted(_forbidden_keys(payload))
    if forbidden:
        raise ValueError(f"trace replay dataset contains forbidden fields: {', '.join(forbidden)}")
    return payload


def _forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).lower() for key in value if str(key).lower() in _FORBIDDEN_DATASET_KEYS}
        return found | set().union(*(_forbidden_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_forbidden_keys(item) for item in value), set())
    return set()


def _fixture_value(field: str, *, process_step: str, step_id: str) -> Any:
    values: dict[str, Any] = {
        "equipment_id": f"{process_step or 'FAB'}-R01",
        "process_step": process_step or "CMP",
        "samples": 64,
        "lots": 48,
        "wafers": 1200,
        "runs": 96,
        "tested_dies": 6400,
        "recorded_minutes": 1440,
        "passed_runs": 92,
        "yield_pct": 94.2,
        "pass_pct": 95.8,
        "cpk": 1.41,
        "mean_value": 50.0,
        "sigma": 1.2,
        "min_value": 46.2,
        "max_value": 53.8,
        "measurement_value": 50.2,
        "spec_lsl": 45.0,
        "spec_usl": 55.0,
        "missing_samples": 0,
        "flagged_outliers": 1,
        "defect_count": 12,
        "affected_lots": 4,
        "share_pct": 32.0,
        "events": 8,
        "excursions": 2,
        "downtime_minutes": 36,
        "avg_defect_density": 0.08,
        "productive_minutes": 1050,
        "standby_minutes": 180,
        "engineering_minutes": 90,
        "scheduled_downtime_minutes": 60,
        "unscheduled_downtime_minutes": 60,
        "productive_pct": 72.9,
        "status": "effective",
        "version": "QA004-1",
        "effective_date": "2026-01-01",
        "reference_id": f"KB-QA004-{step_id}",
        "source_type": "knowledge",
        "source": "sanitized-offline-fixture",
        "section": "QA-004",
        "retrieval": {"confidence": "high", "score": 0.93},
        "start": "2026-08-01",
        "end": "2026-08-07",
        "period": "2026-W31",
        "week_start": "2026-08-03",
        "run_time": "2026-08-04T08:00:00",
        "event_time": "2026-08-04T08:00:00",
        "detected_time": "2026-08-04T09:00:00",
        "lot_id": "LOT-QA004-001",
        "product": "DEMO-P1",
        "technology_nm": "7",
        "metric_name": "removal_rate",
        "metric_unit": "nm/min",
        "measurement_name": "removal_rate",
        "measurement_unit": "nm/min",
        "signal_name": "motor_current",
        "excursion_code": "QA004-DEMO",
        "defect_type": "demo_defect",
        "health": "watch",
        "event_type": "demo_event",
        "duration_minutes": 12,
        "severity": "medium",
        "reason": "sanitized fixture",
        "route": "DEMO_ROUTE",
        "priority": "normal",
        "start_time": "2026-08-01T00:00:00",
        "complete_time": "2026-08-02T00:00:00",
        "wafer_count": 25,
        "good_wafers": 24,
        "yield_rate": 0.96,
        "cycle_time_hours": 24.0,
        "hold_hours": 0.0,
        "operation_seq": 10,
        "layer_name": "DEMO",
        "chamber": "A",
        "recipe": "QA004-R1",
        "queue_hours": 0.5,
        "rework_flag": 0,
        "count": 12,
        "disposition": "review",
    }
    return values.get(field, f"sanitized-{field}")


def _synthetic_observations(plan: Any, playbook: Any) -> tuple[list[EvidenceObservation], list[dict[str, Any]]]:
    requirements = {
        item.evidence_id: item
        for item in (playbook.evidence_requirements if playbook else ())
    }
    observations: list[EvidenceObservation] = []
    sources: list[dict[str, Any]] = []
    for step in plan.steps:
        fields = {
            field
            for evidence_id in step.evidence_ids
            if evidence_id in requirements
            for field in requirements[evidence_id].required_fields
        }
        process_step = str(step.parameters.get("process_step") or "")
        row = {
            field: _fixture_value(field, process_step=process_step, step_id=step.step_id)
            for field in sorted(fields)
        }
        observation = EvidenceObservation(
            step.tool,
            dict(step.parameters),
            "success",
            [row],
            source_ref=f"TOOL:{step.step_id}",
        )
        observations.append(observation)
        if step.tool == "search_knowledge" and row.get("reference_id"):
            sources.append(dict(row))
    return observations, sources


def _submission_for_contract(contract: Any) -> dict[str, Any]:
    reference = next(
        (item for item in contract.permitted_source_refs if item.startswith("TOOL:S")),
        contract.permitted_source_refs[0] if contract.permitted_source_refs else "",
    )
    semantics = contract.source_semantics.get(reference, {})
    claim = {
        "claim_kind": semantics.get("kind", "record"),
        "semantic_id": semantics.get("semantic_id", "offline_trace"),
        "scope": semantics.get("scope", {}),
        "grain": semantics.get("grain", "record"),
        "time_range": {"start": semantics.get("start"), "end": semantics.get("end")},
        "claim_role": "background" if semantics.get("scope_role") == "context_only" else "primary",
    }
    return {
        "conclusion": "脱敏回放证据覆盖了当前计划要求，结论仅用于链路契约验证。",
        "conclusion_evidence_refs": [reference] if reference else [],
        "conclusion_claim": claim,
        "facts": [{
            "statement": "回放使用的证据来自固定离线夹具。",
            "evidence_refs": [reference] if reference else [],
            **claim,
        }],
        "inferences": [],
        "hypotheses": [],
        "recommendations": [{
            "action": "仅将该结果用于自动化回归",
            "rationale": "数据为脱敏合成夹具",
            "requires_review": False,
        }],
        "limitations": ["该回放不代表真实生产数据或模型质量。"],
        "source_refs": [reference] if reference else [],
    }


def replay_case(case: dict[str, Any], *, current_date: date) -> dict[str, Any]:
    """Run one deterministic case through the production policy components."""
    question = str(case["question"])
    history = list(case.get("history") or [])
    context_fixture = case.get("context_fixture")
    context = (
        semantic_context_resolution(question, context_fixture, history)
        if isinstance(context_fixture, dict)
        else unresolved_context(question)
    )
    direct_route = route_question(question, current_date=current_date)
    resolved_question = context.resolved_question
    resolved_route = (
        route_question("介绍一下你自己", current_date=current_date)
        if context.strategy in {"semantic_recall", "context_clarification"}
        else route_question(resolved_question, current_date=current_date)
        if context.applied
        else direct_route
    )
    arbitration = arbitrate_decision(
        original_question=question,
        resolved_question=resolved_question,
        original_route=direct_route,
        resolved_route=resolved_route,
        context=context,
        raw_model_actions=list(context.turn_actions) if context.turn_actions else None,
        previous_active_flow=recover_active_flow(history),
    )
    route = arbitration.route
    effective_question = arbitration.effective_question
    turn_decision = build_turn_decision(
        route=route.intent,
        relation=context.relation,
        confidence=context.confidence,
        question=effective_question,
        model_actions=[item.to_dict() for item in arbitration.model_actions] or None,
        context_failure_reason=context.failure_reason,
        valid_route_intents=set(INTENT_LABELS) - {"conversation", "unknown", "ambiguous"},
    )
    primary_action = next(
        (item for item in turn_decision.actions if item.type in {"answer_meta", "route_task"}),
        turn_decision.actions[0],
    )
    active_flow = arbitration.active_flow
    if primary_action.type == "answer_meta" and primary_action.subject:
        active_flow = f"meta:{primary_action.subject}"
    elif primary_action.type == "route_task" and primary_action.target_intent:
        active_flow = f"task:{primary_action.target_intent}"
    turn_decision = replace(
        turn_decision,
        active_flow=active_flow,
        selected_origin=arbitration.selected_origin,
        policy_reason=arbitration.policy_reason,
        candidates=tuple(item.to_dict() for item in arbitration.candidates),
    )
    selection = select_playbook(route)
    plan = create_execution_plan(effective_question, route, selection)

    observations: list[EvidenceObservation] = []
    sources: list[dict[str, Any]] = []
    if plan.status == "ready":
        observations, sources = _synthetic_observations(plan, selection.selected_playbook)
    validation = validate_evidence(plan, selection.selected_playbook, observations)
    contract = create_answer_contract(validation, sources)

    if plan.status == "ready":
        synthesized = synthesize_submission(_submission_for_contract(contract), contract, sources)
        tool_path = [step.tool for step in plan.steps]
        structured_submit = synthesized.report.status == "structured"
    elif route.intent == "general_knowledge":
        tool_path = ["search_knowledge" for _ in required_scopes(effective_question)]
        knowledge_ref = "KB-QA004-GENERAL"
        sources = [{
            "reference_id": knowledge_ref,
            "source_type": "knowledge",
            "source": "sanitized-offline-fixture",
            "section": "QA-004",
            "retrieval": {"confidence": "high", "score": 0.93},
        }]
        contract = create_answer_contract(validation, sources)
        synthesized = synthesize_legacy_answer(
            f"化学机械抛光通过化学反应与机械作用协同实现表面平坦化。[来源 {knowledge_ref}]",
            contract,
            sources,
        )
        structured_submit = False
    else:
        tool_path = []
        synthesized = synthesize_legacy_answer("这是一次脱敏的确定性会话动作回放。", contract)
        structured_submit = False

    model_calls = 1 if context_fixture or route.intent == "general_knowledge" or plan.status == "ready" else 0
    progress_events: list[dict[str, Any]] = [
        {"event": "run_started", "run_id": f"qa004-{case['id']}", "message": "离线回放已创建"},
        {"event": "stage", "stage": "routing", "route": route.to_dict(), "message": "路由完成"},
        {"event": "stage", "stage": "plan", "plan": plan.to_dict(), "message": "计划完成"},
    ]
    for step in plan.steps:
        progress_events.extend((
            {
                "event": "tool_started", "tool": step.tool,
                "arguments": dict(step.parameters), "plan_step_id": step.step_id,
                "execution_mode": "offline_replay",
            },
            {
                "event": "tool_finished", "tool": step.tool,
                "arguments": dict(step.parameters), "plan_step_id": step.step_id,
                "status": "ok", "rows": 1, "execution_mode": "offline_replay",
            },
        ))
    progress_events.append({"event": "stage", "stage": "synthesis", "message": "离线综合完成"})
    for start in range(0, len(synthesized.answer), 120):
        progress_events.append({"event": "answer_delta", "delta": synthesized.answer[start:start + 120]})

    return {
        "answer": synthesized.answer,
        "tool_trace": [
            {
                "tool": step.tool,
                "arguments": dict(step.parameters),
                "plan_step_id": step.step_id,
                "status": "ok",
                "rows": 1,
                "execution_mode": "offline_replay",
            }
            for step in plan.steps
        ],
        "sources": sources,
        "mode": "offline_trace_replay",
        "model": "deterministic-fixture",
        "run_id": f"qa004-{case['id']}",
        "intent_route": route.to_dict(),
        "turn_decision": turn_decision.to_dict(),
        "domain_playbook": selection.to_dict(),
        "execution_plan": plan.to_dict(),
        "evidence_validation": validation.to_dict(),
        "answer_contract": contract.to_dict(),
        "answer_synthesis": synthesized.report.to_dict(),
        "context_resolution": context.to_dict(),
        "trace_semantics": {
            "schema_version": "1.0",
            "stream_duration_ms": None,
            "network_calls": 0,
            "real_model_calls": 0,
            "simulated_model_calls": model_calls,
            "model_business_tool_selection_calls": 0,
            "business_tool_calls": len(tool_path),
        },
        "replay": {
            "schema_version": "1.0",
            "case_id": case["id"],
            "data_classification": "synthetic_redacted",
            "tool_path": tool_path,
            "structured_submit": structured_submit,
            "progress_events": progress_events,
        },
    }


def _case_errors(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    expected = case["expected"]
    decision = result["turn_decision"]
    action = decision["actions"][0]
    plan = result["execution_plan"]
    actual = {
        "route": result["intent_route"]["intent"],
        "action": action["type"],
        "subject": action.get("subject"),
        "detail": action.get("detail"),
        "active_flow": decision.get("active_flow"),
        "plan_status": plan["status"],
        "primary_scope_type": plan["scope_contract"]["primary_scope_type"],
        "primary_scope_ids": plan["scope_contract"]["primary_scope_ids"],
        "tool_path": result["replay"]["tool_path"],
        "evidence_strength": result["evidence_validation"]["allowed_conclusion_strength"],
        "structured_submit": result["replay"]["structured_submit"],
        "model_calls": result["trace_semantics"]["simulated_model_calls"],
        "business_tool_calls": result["trace_semantics"]["business_tool_calls"],
    }
    errors = [
        f"{key}: expected {value!r}, got {actual.get(key)!r}"
        for key, value in expected.items()
        if key in actual and actual.get(key) != value
    ]
    forbidden_scopes = set(expected.get("forbidden_primary_scope_ids", []))
    if forbidden_scopes.intersection(actual["primary_scope_ids"]):
        errors.append("forbidden primary scope selected")
    primary_tools = {
        step["tool"] for step in plan["steps"] if step.get("scope_role") == "primary"
    }
    if set(expected.get("forbidden_primary_tools", [])).intersection(primary_tools):
        errors.append("forbidden primary tool selected")
    if result["trace_semantics"]["model_business_tool_selection_calls"] != 0:
        errors.append("model selected a business tool")
    if result["trace_semantics"]["network_calls"] != 0 or result["trace_semantics"]["real_model_calls"] != 0:
        errors.append("external call observed")
    if plan["status"] == "ready" and actual["business_tool_calls"] != plan["budget"]["planned_tool_calls"]:
        errors.append("business tool calls differ from planned_tool_calls")
    if "".join(
        item.get("delta", "") for item in result["replay"]["progress_events"]
        if item.get("event") == "answer_delta"
    ) != result["answer"]:
        errors.append("streamed answer differs from final answer")
    return errors


def evaluate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    current_date = date.fromisoformat(dataset["current_date"])
    details: list[dict[str, Any]] = []
    groups: Counter[str] = Counter()
    for case in dataset["cases"]:
        result = replay_case(case, current_date=current_date)
        errors = _case_errors(case, result)
        groups[str(case["group"])] += 1
        details.append({
            "id": case["id"],
            "group": case["group"],
            "passed": not errors,
            "errors": errors,
            "route": result["intent_route"]["intent"],
            "action": result["turn_decision"]["actions"][0]["type"],
            "plan_status": result["execution_plan"]["status"],
            "primary_scope_type": result["execution_plan"]["scope_contract"]["primary_scope_type"],
            "primary_scope_ids": result["execution_plan"]["scope_contract"]["primary_scope_ids"],
            "tool_path": result["replay"]["tool_path"],
            "evidence_strength": result["evidence_validation"]["allowed_conclusion_strength"],
            "structured_submit": result["replay"]["structured_submit"],
            "model_calls": result["trace_semantics"]["simulated_model_calls"],
            "business_tool_calls": result["trace_semantics"]["business_tool_calls"],
        })
    failed = [item["id"] for item in details if not item["passed"]]
    return {
        "schema_version": dataset["schema_version"],
        "dataset_id": dataset["dataset_id"],
        "execution_mode": "offline_deterministic_replay",
        "data_classification": dataset["data_classification"],
        "passed": not failed,
        "cases": len(details),
        "passed_cases": len(details) - len(failed),
        "failed_cases": failed,
        "groups": dict(sorted(groups.items())),
        "external_calls": {"network": 0, "real_model": 0},
        "details": details,
    }


def evaluate(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    return evaluate_dataset(load_dataset(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = evaluate(args.dataset)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
