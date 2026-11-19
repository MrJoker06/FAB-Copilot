"""Evaluate labelled routing decisions offline, including an exported baseline."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


def execution_decision(route) -> str:
    if route.clarification_needed or route.intent in {"unknown", "ambiguous"}:
        return "clarify"
    if route.intent == "conversation":
        return "conversation"
    if route.intent in {"general_knowledge", "sop_lookup"}:
        return "knowledge"
    return "business"


def evaluate(route_question, gold: dict) -> dict:
    if not gold.get("cases"):
        raise ValueError("routing evaluation requires labelled cases")
    identifiers = [case["id"] for case in gold["cases"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("routing evaluation case IDs must be unique")
    results = []
    current_date = date.fromisoformat(gold["current_date"])
    confusion = Counter()
    for case in gold["cases"]:
        route = route_question(case["question"], current_date=current_date)
        decision = execution_decision(route)
        kind = getattr(route, "request_type", None)
        topics = getattr(route, "business_topics", ())
        confusion[f"{case['decision']}->{decision}"] += 1
        results.append(
            {
                "id": case["id"],
                "intent": route.intent,
                "decision": decision,
                "expected_decision": case["decision"],
                "decision_correct": decision == case["decision"],
                "request_type": kind,
                "expected_request_type": case["request_type"],
                "request_type_correct": kind == case["request_type"],
                "business_topics": list(topics),
                "topics_correct": set(case["topics_contains"]) <= set(topics),
            }
        )
    has_classification = all(r["request_type"] is not None for r in results)
    return {
        "cases": len(results),
        "decisions_correct": sum(r["decision_correct"] for r in results),
        "request_types_correct": sum(r["request_type_correct"] for r in results)
        if has_classification
        else None,
        "topics_correct": sum(r["topics_correct"] for r in results)
        if has_classification
        else None,
        "business_misactivation": sum(
            r["decision"] == "business" and r["expected_decision"] != "business"
            for r in results
        ),
        "business_missed": sum(
            r["expected_decision"] == "business" and r["decision"] != "business"
            for r in results
        ),
        "knowledge_misrouted": sum(
            r["expected_decision"] == "knowledge" and r["decision"] != "knowledge"
            for r in results
        ),
        "confusion": dict(sorted(confusion.items())),
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_DIR,
        help="Source root, optionally a git export",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=PROJECT_DIR / "evaluations/intent_request_gold.json",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    expected_source = args.root.resolve() / "app/intent_runtime/routing.py"
    if not expected_source.is_file():
        raise ValueError("routing source root is unavailable")
    sys.path.insert(0, str(args.root.resolve()))
    from app.intent_runtime.routing import route_question

    if Path(inspect.getsourcefile(route_question)).resolve() != expected_source:
        raise ValueError("routing evaluation source root mismatch")
    result = evaluate(route_question, json.loads(args.gold.read_text(encoding="utf-8")))
    result["source_root"] = str(args.root.resolve())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "results"}, ensure_ascii=False
        )
    )
    complete = result["decisions_correct"] == result["cases"] and all(
        result[key] in {None, result["cases"]}
        for key in ("request_types_correct", "topics_correct")
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
