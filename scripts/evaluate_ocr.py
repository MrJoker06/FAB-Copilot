"""Strict, deterministic, offline OCR golden-set evaluator."""
from __future__ import annotations

import json
import math
import sys
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.ocr import extract_image_result
from app.ocr_quality import POLICY_VERSION
from app.personal_knowledge import _extract_sections

ROOT = PROJECT_DIR / "evaluations" / "ocr_samples"
DATASET = PROJECT_DIR / "evaluations" / "ocr_gold.json"
REPORT = PROJECT_DIR / "runtime" / "quality" / "ocr_gold_report.json"
CATEGORY_ORDER = (
    "chinese",
    "english",
    "device_screenshot",
    "table",
    "formula",
    "scanned_pdf",
    "mixed_pdf",
    "multipage_tiff",
)
REQUIRED = set(CATEGORY_ORDER)
SUFFIXES = {
    "chinese": ".png",
    "english": ".png",
    "device_screenshot": ".png",
    "table": ".png",
    "formula": ".png",
    "scanned_pdf": ".pdf",
    "mixed_pdf": ".pdf",
    "multipage_tiff": ".tiff",
}
METRICS = {
    "cer",
    "wer",
    "field_recall",
    "cell_recall",
    "formula_token_recall",
    "page_retention",
}
BASE_CASE_KEYS = {"id", "category", "path", "expected_text", "pages"}
CATEGORY_EXPECTATION_KEYS = {
    "device_screenshot": "fields",
    "scanned_pdf": "fields",
    "mixed_pdf": "fields",
    "multipage_tiff": "fields",
    "table": "cells",
    "formula": "formula_tokens",
}


def norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def lev(left: list[str] | str, right: list[str] | str) -> int:
    row = list(range(len(right) + 1))
    for index, left_item in enumerate(left, 1):
        next_row = [index] + [0] * len(right)
        for column, right_item in enumerate(right, 1):
            next_row[column] = min(row[column] + 1, next_row[column - 1] + 1, row[column - 1] + (left_item != right_item))
        row = next_row
    return row[-1]


def cer(actual: str, expected: str) -> float:
    return lev(norm(actual), norm(expected)) / max(1, len(norm(expected)))


def wer(actual: str, expected: str) -> float:
    left, right = norm(actual).split(), norm(expected).split()
    return lev(left, right) / max(1, len(right))


def recall(actual: str | list[str], expected: list[str]) -> float:
    text = " ".join(actual) if isinstance(actual, list) else actual
    return sum(norm(item) in norm(text) for item in expected) / len(expected)


def _validate_thresholds(value: Any) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"global", "categories"}
        or not isinstance(value["global"], dict)
        or not isinstance(value["categories"], dict)
        or set(value["categories"]) != REQUIRED
    ):
        raise ValueError("invalid OCR threshold schema")
    for group in [value["global"], *value["categories"].values()]:
        if not isinstance(group, dict):
            raise ValueError("invalid OCR threshold group")
        for key, number in group.items():
            metric = key.removesuffix("_min").removesuffix("_max")
            if (
                metric not in METRICS or not key.endswith(("_min", "_max"))
                or isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not 0 <= number <= 1
            ):
                raise ValueError("invalid OCR threshold")


def _validate_path(root: Path, category: str, name: str) -> None:
    relative = Path(name)
    target = root / relative
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or target.suffix.lower() != SUFFIXES[category]
        or target.is_symlink()
        or any(parent.is_symlink() for parent in target.parents if parent != root.parent)
        or root.resolve() not in target.resolve().parents
        or not target.is_file()
    ):
        raise ValueError("unsafe OCR gold sample path")


def load_dataset(path: Path = DATASET, sample_root: Path = ROOT) -> dict[str, Any]:
    if not sample_root.is_dir() or sample_root.is_symlink():
        raise ValueError("invalid OCR sample root")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "thresholds", "cases"}
        or not isinstance(data.get("version"), str)
        or not data["version"]
        or not isinstance(data.get("cases"), list)
    ):
        raise ValueError("invalid OCR gold schema")
    _validate_thresholds(data["thresholds"])
    ids, categories = set(), set()
    for case in data["cases"]:
        if not isinstance(case, dict):
            raise ValueError("invalid OCR gold case")
        category = case.get("category")
        expectation_key = CATEGORY_EXPECTATION_KEYS.get(category)
        expected_keys = BASE_CASE_KEYS | ({expectation_key} if expectation_key else set())
        if set(case) != expected_keys:
            raise ValueError("invalid OCR gold case keys")
        if (
            not all(
                isinstance(case.get(key), str) and case[key]
                for key in ("id", "category", "path", "expected_text")
            )
            or case["id"] in ids
            or category not in REQUIRED
        ):
            raise ValueError("invalid OCR gold case")
        pages = case.get("pages")
        if (
            not isinstance(pages, list)
            or not pages
            or len(set(pages)) != len(pages)
            or any(
                isinstance(page, bool) or not isinstance(page, int) or page < 1
                for page in pages
            )
        ):
            raise ValueError("invalid OCR gold case pages")
        if expectation_key and (
            not isinstance(case.get(expectation_key), list)
            or not case[expectation_key]
            or any(
                not isinstance(item, str) or not item
                for item in case[expectation_key]
            )
        ):
            raise ValueError("missing OCR category expectations")
        _validate_path(sample_root, category, case["path"])
        ids.add(case["id"])
        categories.add(case["category"])
    if categories != REQUIRED:
        raise ValueError("OCR gold required category missing")
    return data


def evaluate(dataset_path: Path = DATASET, report_path: Path = REPORT, sample_root: Path = ROOT) -> dict[str, Any]:
    data = load_dataset(dataset_path, sample_root)
    details: list[dict[str, Any]] = []
    for case in data["cases"]:
        path = sample_root / case["path"]
        suffix = path.suffix.lower()
        if suffix in {".pdf", ".tiff"}:
            sections = _extract_sections(path, suffix, case["id"])
            text = "\n".join(section.content for section in sections)
            pages = [section.page_number for section in sections]
        else:
            text = extract_image_result(path.read_bytes()).text
            pages = [1]
        metrics = {"cer": cer(text, case["expected_text"])}
        if case["category"] == "english":
            metrics["wer"] = wer(text, case["expected_text"])
        if suffix in {".pdf", ".tiff"}:
            metrics["page_retention"] = recall(
                [str(page) for page in pages],
                [str(page) for page in case["pages"]],
            )
        for key, metric in (
            ("fields", "field_recall"),
            ("cells", "cell_recall"),
            ("formula_tokens", "formula_token_recall"),
        ):
            if key in case:
                metrics[metric] = recall(text, case[key])
        thresholds = {**data["thresholds"]["global"], **data["thresholds"]["categories"][case["category"]]}
        reasons = []
        for metric, value in metrics.items():
            lower, upper = f"{metric}_min", f"{metric}_max"
            if (lower in thresholds) == (upper in thresholds):
                raise ValueError(f"metric {metric} requires exactly one threshold")
            if lower in thresholds and value < thresholds[lower]:
                reasons.append(f"{metric} < {thresholds[lower]}")
            if upper in thresholds and value > thresholds[upper]:
                reasons.append(f"{metric} > {thresholds[upper]}")
        details.append(
            {
                "id": case["id"],
                "category": case["category"],
                "metrics": metrics,
                "failed_reasons": reasons,
            }
        )
    categories = {
        category: {"cases": 0, "failed_cases": [], "passed": True, "metrics": {}}
        for category in CATEGORY_ORDER
    }
    for detail in details:
        aggregate = categories[detail["category"]]
        aggregate["cases"] += 1
        if detail["failed_reasons"]:
            aggregate["failed_cases"].append(detail["id"])
        aggregate["passed"] = not aggregate["failed_cases"]
        for name, value in detail["metrics"].items():
            aggregate["metrics"].setdefault(name, []).append(value)
    for aggregate in categories.values():
        aggregate["failed"] = len(aggregate["failed_cases"])
        aggregate["metrics"] = {
            name: round(sum(values) / len(values), 4)
            for name, values in aggregate["metrics"].items()
        }
    report = {
        "dataset_version": data["version"],
        "policy_version": POLICY_VERSION,
        "thresholds": data["thresholds"],
        "details": details,
        "categories": categories,
        "passed": not any(item["failed_reasons"] for item in details),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
