from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.knowledge.rag import search_knowledge  # noqa: E402
from app.manufacturing.seed import seed_reference_data  # noqa: E402


def evaluate() -> dict:
    seed_reference_data()
    dataset = json.loads((PROJECT_DIR / "evaluations" / "rag_gold.json").read_text(encoding="utf-8"))
    details = []
    reciprocal_ranks = []
    for item in dataset:
        results = search_knowledge(item["query"], limit=6, **item.get("filters", {}))
        references = [result["reference_id"] for result in results]
        source_types = {result["source_type"] for result in results}
        ranks = [references.index(reference) + 1 for reference in item["expected_any"] if reference in references]
        hit = bool(ranks)
        reciprocal_ranks.append(1 / min(ranks) if ranks else 0)
        source_coverage = set(item.get("required_source_types", [])).issubset(source_types)
        forbidden_hits = [reference for reference in item.get("forbidden", []) if reference in references]
        details.append({
            "id": item["id"],
            "hit": hit,
            "source_coverage": source_coverage,
            "forbidden_hits": forbidden_hits,
            "references": references,
        })
    total = len(details)
    return {
        "queries": total,
        "hit_rate": round(sum(item["hit"] for item in details) / total, 4),
        "source_coverage_rate": round(sum(item["source_coverage"] for item in details) / total, 4),
        "mrr": round(sum(reciprocal_ranks) / total, 4),
        "forbidden_hits": sum(len(item["forbidden_hits"]) for item in details),
        "passed": all(item["hit"] and item["source_coverage"] and not item["forbidden_hits"] for item in details),
        "details": details,
    }


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
