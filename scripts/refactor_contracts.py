"""Collect and compare the behavior contract used by folder-level refactors."""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from datetime import date
from difflib import unified_diff
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = PROJECT_DIR / "evaluations" / "refactor_contract_v1.json"
sys.path.insert(0, str(PROJECT_DIR))

from fastapi.routing import APIRoute  # noqa: E402

from app.agent import TOOLS  # noqa: E402
from app.main import app  # noqa: E402
from scripts.evaluate_trace_replay import load_dataset, replay_case  # noqa: E402


def _canonical_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=indent,
        separators=None if indent is not None else (",", ":"),
        sort_keys=True,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class _PageContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.element_ids: list[str] = []
        self.script_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.element_ids.append(str(attributes["id"]))
        if tag == "script" and attributes.get("src"):
            self.script_sources.append(str(attributes["src"]))


def collect_tool_contract() -> dict[str, Any]:
    return {
        "names": [item["function"]["name"] for item in TOOLS],
        "schema_sha256": _sha256(TOOLS),
    }


def collect_api_contract() -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or []):
            routes.append({
                "method": method,
                "name": route.name,
                "path": route.path,
                "success_status": route.status_code or 200,
            })
    routes.sort(key=lambda item: (item["path"], item["method"]))
    return {
        "openapi_sha256": _sha256(app.openapi()),
        "routes": routes,
    }


def _collect_page_contract(name: str) -> dict[str, Any]:
    parser = _PageContractParser()
    parser.feed((PROJECT_DIR / "app" / "static" / f"{name}.html").read_text(encoding="utf-8"))
    if len(parser.element_ids) != len(set(parser.element_ids)):
        raise ValueError(f"duplicate DOM id in {name}.html")
    return {
        "element_ids": sorted(parser.element_ids),
        "script_sources": parser.script_sources,
    }


def collect_frontend_contract() -> dict[str, Any]:
    return {
        "admin": _collect_page_contract("admin"),
        "index": _collect_page_contract("index"),
    }


def _event_label(event: dict[str, Any]) -> str:
    label = str(event.get("event") or "")
    if event.get("stage"):
        label += f":{event['stage']}"
    return label


def collect_agent_contract() -> dict[str, Any]:
    dataset = load_dataset()
    current_date = date.fromisoformat(dataset["current_date"])
    cases: dict[str, Any] = {}
    with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
        for case in dataset["cases"]:
            if not case.get("system_replay"):
                continue
            result = replay_case(case, current_date=current_date)
            trace = result.get("tool_trace") or []
            cases[case["id"]] = {
                "event_sequence": [
                    _event_label(event)
                    for event in result["replay"]["progress_events"]
                ],
                "result_keys": sorted(key for key in result if key != "replay"),
                "trace_item_keys": sorted({
                    key
                    for item in trace
                    for key in item
                }),
            }
    return {"cases": cases}


def collect_contract() -> dict[str, Any]:
    return {
        "api": collect_api_contract(),
        "agent": collect_agent_contract(),
        "contract_version": "1.0",
        "data_classification": "synthetic_redacted",
        "execution_policy": {
            "network_calls": 0,
            "real_model_calls": 0,
        },
        "frontend": collect_frontend_contract(),
        "tools": collect_tool_contract(),
    }


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("contract_version") != "1.0":
        raise ValueError("refactor contract_version must be 1.0")
    if contract.get("data_classification") != "synthetic_redacted":
        raise ValueError("refactor contract must be synthetic_redacted")
    if contract.get("execution_policy") != {"network_calls": 0, "real_model_calls": 0}:
        raise ValueError("refactor contract must prohibit model and network calls")
    return contract


def contract_diff(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    return "".join(unified_diff(
        _canonical_json(expected, indent=2).splitlines(keepends=True),
        _canonical_json(actual, indent=2).splitlines(keepends=True),
        fromfile="expected/refactor_contract_v1.json",
        tofile="actual/current_implementation.json",
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-current",
        action="store_true",
        help="Print the current normalized contract without writing the baseline.",
    )
    arguments = parser.parse_args()
    actual = collect_contract()
    if arguments.print_current:
        print(_canonical_json(actual, indent=2))
        return 0
    expected = load_contract()
    difference = contract_diff(expected, actual)
    if difference:
        print(difference)
        return 1
    print("Refactor compatibility contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
