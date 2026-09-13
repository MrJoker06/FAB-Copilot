"""Evaluate deterministic Router, Playbook selection, and Planner golden cases."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = PROJECT_DIR / "evaluations" / "playbook_gold.json"
DEFAULT_REPORT = PROJECT_DIR / "runtime" / "quality" / "playbook_gold_report.json"
REQUIRED_INTENTS = {
    "capability_excursion", "yield_decline", "equipment_fault",
    "lot_trace", "sop_lookup", "fab_diagnostic",
}
CASE_FIELDS = {
    "id": str,
    "question": str,
    "intent": str,
    "playbook_id": str,
    "plan_status": str,
    "tool_path": list,
    "required_evidence_ids": list,
}

sys.path.insert(0, str(PROJECT_DIR))

from app.manufacturing.playbooks import DOMAIN_PLAYBOOKS, select_playbook  # noqa: E402
from app.intent_runtime.routing import route_question  # noqa: E402
from app.planning_runtime.service import create_execution_plan  # noqa: E402


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("dataset root must be an object")
    return data


def validate_dataset(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    try:
        date.fromisoformat(data.get("current_date", ""))
    except (TypeError, ValueError):
        errors.append("current_date must be an ISO date")
    cases = data.get("cases")
    if not isinstance(cases, list):
        return [*errors, "cases must be a list"]
    ids: set[str] = set()
    intent_counts: dict[str, int] = {}
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field, expected_type in CASE_FIELDS.items():
            if not isinstance(case.get(field), expected_type) or not case.get(field):
                errors.append(f"{prefix}.{field} must be a non-empty {expected_type.__name__}")
        case_id = case.get("id")
        if isinstance(case_id, str):
            if case_id in ids:
                errors.append(f"duplicate case id: {case_id}")
            ids.add(case_id)
        intent = case.get("intent")
        if isinstance(intent, str):
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        for list_field in ("tool_path", "required_evidence_ids"):
            value = case.get(list_field)
            if isinstance(value, list) and not all(isinstance(item, str) and item for item in value):
                errors.append(f"{prefix}.{list_field} must contain only non-empty strings")
    missing = REQUIRED_INTENTS - set(intent_counts)
    if missing:
        errors.append("missing required intents: " + ", ".join(sorted(missing)))
    for intent in sorted(REQUIRED_INTENTS):
        count = intent_counts.get(intent, 0)
        if count and count < 2:
            errors.append(f"intent {intent} requires at least 2 cases, got {count}")
    return errors


def evaluate_dataset(data: dict[str, Any]) -> dict[str, Any]:
    errors = validate_dataset(data)
    if errors:
        return {"passed": False, "cases": 0, "failed_cases": [{"id": "dataset", "reasons": errors}]}
    current_date = date.fromisoformat(data["current_date"])
    details: list[dict[str, Any]] = []
    for case in data["cases"]:
        route = route_question(case["question"], current_date=current_date)
        selection = select_playbook(route)
        plan = create_execution_plan(case["question"], route, selection)
        reasons: list[str] = []
        if route.intent != case["intent"]:
            reasons.append(f"intent expected {case['intent']}, got {route.intent}")
        selected_id = selection.selected_playbook.playbook_id if selection.selected_playbook else None
        if selected_id != case["playbook_id"]:
            reasons.append(f"playbook_id expected {case['playbook_id']}, got {selected_id}")
        if plan.status != case["plan_status"]:
            reasons.append(f"plan_status expected {case['plan_status']}, got {plan.status}")
        actual_path = [step.tool for step in plan.steps]
        if actual_path != case["tool_path"]:
            reasons.append(f"tool_path expected {case['tool_path']}, got {actual_path}")
        expected_evidence = set(case["required_evidence_ids"])
        actual_evidence = set(plan.required_evidence_ids)
        if actual_evidence != expected_evidence:
            reasons.append(f"required_evidence_ids expected {sorted(expected_evidence)}, got {sorted(actual_evidence)}")
        playbook = DOMAIN_PLAYBOOKS.get(case["intent"])
        playbook_required = {item.evidence_id for item in playbook.evidence_requirements if item.required} if playbook else set()
        if expected_evidence != playbook_required:
            reasons.append("gold required_evidence_ids do not match the Playbook required evidence")
        covered_evidence = {evidence_id for step in plan.steps if step.required for evidence_id in step.evidence_ids}
        missing_evidence = actual_evidence - covered_evidence
        if missing_evidence:
            reasons.append("required evidence has no required step: " + ", ".join(sorted(missing_evidence)))
        if plan.budget.planned_tool_calls != len(plan.steps):
            reasons.append("budget planned_tool_calls does not equal number of plan steps")
        if plan.budget.max_tool_calls < plan.budget.planned_tool_calls:
            reasons.append("budget max_tool_calls is below planned_tool_calls")
        details.append({"id": case["id"], "passed": not reasons, "reasons": reasons})
    failed_cases = [detail for detail in details if not detail["passed"]]
    return {"passed": not failed_cases, "cases": len(details), "passed_cases": len(details) - len(failed_cases), "failed_cases": failed_cases, "details": details}


def evaluate(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    return evaluate_dataset(load_dataset(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = evaluate(args.dataset)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
