"""Evaluate AGENT-038 with a deterministic, offline synthetic cost model."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = PROJECT_DIR / "evaluations" / "ready_execution_benchmark.json"
DEFAULT_REPORT = PROJECT_DIR / "runtime" / "quality" / "ready_execution_report.json"
sys.path.insert(0, str(PROJECT_DIR))

from app.agent import (  # noqa: E402
    SUBMIT_ANALYSIS_TOOL,
    SYSTEM_PROMPT,
    TOOLS,
    _ready_synthesis_messages,
)
from app.answer_synthesizer import create_answer_contract, synthesizer_system_message  # noqa: E402
from app.domain_playbooks import playbook_system_message, select_playbook  # noqa: E402
from app.evidence_validator import EvidenceObservation, validate_evidence, validator_system_message  # noqa: E402
from app.intent_router import route_question, routing_system_message  # noqa: E402
from app.planner import create_execution_plan, planner_system_message  # noqa: E402


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark dataset root must be an object")
    if payload.get("schema_version") != "1.0":
        raise ValueError("benchmark schema_version must be 1.0")
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise ValueError("benchmark requires non-empty cases")
    return payload


def _estimated_tokens(value: Any, bytes_per_token: int) -> int:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return max(1, math.ceil(len(serialized.encode("utf-8")) / bytes_per_token))


def _synthetic_observations(plan) -> list[EvidenceObservation]:
    return [
        EvidenceObservation(
            step.tool,
            step.parameters,
            "success",
            [{"synthetic_step": step.step_id, "tool": step.tool, "rows": 1}],
            source_ref=f"TOOL:{step.step_id}",
        )
        for step in plan.steps
    ]


def _dependency_batches(plan) -> list[list[Any]]:
    levels: dict[str, int] = {}
    for step in plan.steps:
        levels[step.step_id] = 1 + max((levels[item] for item in step.depends_on), default=0)
    return [
        [step for step in plan.steps if levels[step.step_id] == level]
        for level in sorted(set(levels.values()))
    ]


def _legacy_prompt_tokens(question, route, selection, plan, validation, contract, observations, cost) -> tuple[int, int]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": routing_system_message(route)},
        {"role": "system", "content": playbook_system_message(selection)},
        {"role": "system", "content": planner_system_message(plan)},
        {"role": "system", "content": validator_system_message(validate_evidence(plan, selection.selected_playbook, []))},
        {"role": "system", "content": synthesizer_system_message(create_answer_contract(validate_evidence(plan, selection.selected_playbook, [])))},
        {"role": "user", "content": question},
    ]
    total = 0
    observations_by_ref = {item.source_ref: item for item in observations}
    batches = _dependency_batches(plan)
    for batch in batches:
        total += _estimated_tokens({"messages": messages, "tools": TOOLS}, cost["utf8_bytes_per_token"])
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"legacy-{step.step_id}",
                "type": "function",
                "function": {
                    "name": step.tool,
                    "arguments": json.dumps(step.parameters, ensure_ascii=False, separators=(",", ":")),
                },
            } for step in batch],
        })
        for step in batch:
            observation = observations_by_ref[f"TOOL:{step.step_id}"]
            messages.append({
                "role": "tool",
                "tool_call_id": f"legacy-{step.step_id}",
                "content": json.dumps({"ok": True, "data": observation.result}, ensure_ascii=False, separators=(",", ":")),
            })
    messages.extend([
        {"role": "system", "content": validator_system_message(validation)},
        {"role": "system", "content": synthesizer_system_message(contract)},
    ])
    total += _estimated_tokens(
        {"messages": messages, "tools": [SUBMIT_ANALYSIS_TOOL]},
        cost["utf8_bytes_per_token"],
    )
    return total, len(batches)


def evaluate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    current_date = date.fromisoformat(dataset["current_date"])
    cost = dataset["cost_model"]
    thresholds = dataset["thresholds"]
    details: list[dict[str, Any]] = []
    for case in dataset["cases"]:
        question = str(case["question"])
        route = route_question(question, current_date=current_date)
        selection = select_playbook(route)
        plan = create_execution_plan(question, route, selection)
        if plan.status != "ready":
            details.append({"id": case.get("id"), "passed": False, "error": f"plan status is {plan.status}"})
            continue
        observations = _synthetic_observations(plan)
        validation = validate_evidence(plan, selection.selected_playbook, observations)
        contract = create_answer_contract(validation)
        legacy_prompt, legacy_selection_calls = _legacy_prompt_tokens(
            question, route, selection, plan, validation, contract, observations, cost,
        )
        candidate_messages = _ready_synthesis_messages(question, plan, validation, contract, observations)
        candidate_prompt = _estimated_tokens(
            {"messages": candidate_messages, "tools": [SUBMIT_ANALYSIS_TOOL]},
            cost["utf8_bytes_per_token"],
        )
        legacy_calls = legacy_selection_calls + 1
        candidate_calls = 1
        legacy_tokens = (
            legacy_prompt
            + legacy_selection_calls * cost["tool_selection_output_tokens"]
            + cost["final_output_tokens"]
        )
        candidate_tokens = candidate_prompt + cost["final_output_tokens"]
        tool_time = len(plan.steps) * cost["tool_call_ms"]
        legacy_latency = (
            tool_time
            + legacy_calls * cost["model_call_base_ms"]
            + legacy_prompt * cost["prompt_token_ms"]
        )
        candidate_latency = (
            tool_time
            + candidate_calls * cost["model_call_base_ms"]
            + candidate_prompt * cost["prompt_token_ms"]
        )
        token_reduction = round(100.0 * (legacy_tokens - candidate_tokens) / legacy_tokens, 1)
        latency_reduction = round(100.0 * (legacy_latency - candidate_latency) / legacy_latency, 1)
        passed = (
            token_reduction >= thresholds["total_token_reduction_pct_min"]
            and latency_reduction >= thresholds["first_final_answer_reduction_pct_min"]
            and candidate_calls == 1
        )
        details.append({
            "id": case["id"],
            "passed": passed,
            "planned_steps": len(plan.steps),
            "legacy": {
                "model_calls": legacy_calls,
                "model_tool_selection_calls": legacy_selection_calls,
                "estimated_total_tokens": legacy_tokens,
                "estimated_first_final_answer_ms": round(legacy_latency, 1),
            },
            "candidate": {
                "model_calls": candidate_calls,
                "model_tool_selection_calls": 0,
                "estimated_total_tokens": candidate_tokens,
                "estimated_first_final_answer_ms": round(candidate_latency, 1),
            },
            "improvement": {
                "total_token_reduction_pct": token_reduction,
                "first_final_answer_reduction_pct": latency_reduction,
            },
        })
    failed = [item for item in details if not item.get("passed")]
    return {
        "schema_version": dataset["schema_version"],
        "passed": not failed,
        "metric_kind": "deterministic_synthetic_estimate",
        "measurement_note": (
            "Token 使用 UTF-8 字节/固定比例估算，延迟使用版本化成本模型；"
            "结果用于离线架构回归，不代表真实供应商计费或网络 SLA。"
        ),
        "thresholds": thresholds,
        "cases": len(details),
        "passed_cases": len(details) - len(failed),
        "failed_cases": [item["id"] for item in failed],
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
