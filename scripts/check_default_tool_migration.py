"""Verify the default MOD-008 v2 native capability boundary without I/O."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_DIR / "evaluations" / "mod_008_default_capabilities_v2.json"
sys.path.insert(0, str(PROJECT_DIR))

from app.agent_runtime import service as agent
from app.agent_runtime.tools import catalog as compatibility_catalog
from app.agent_runtime.tools import registry as compatibility_registry
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
from app.bootstrap.default_coordinator_assembly import (
    build_default_coordinator_dependencies,
)
from app.bootstrap.tool_catalog import TOOLS
from app.bootstrap.tool_definitions import (
    BUSINESS_TOOL_DEFINITIONS,
    DEFAULT_CAPABILITY_VERSION,
)
from app.intent_runtime.routing import route_question
from app.manufacturing.named_playbooks import (
    _TOOL_REPLACEMENTS,
    NAMED_PLAYBOOK_VERSION,
    NAMED_QUERY_CAPABILITY_VERSION,
    select_named_playbook,
)
from app.planning_runtime.named_planner import create_named_execution_plan


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("v2 capability manifest must be an object")
    return payload


def _names(tools: list[dict[str, object]]) -> list[str]:
    return [str(item["function"]["name"]) for item in tools]


def _assert_no_sql(value: object, path: str = "catalog") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() == "sql":
                raise AssertionError(f"SQL parameter restored at {path}.{key}")
            _assert_no_sql(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_sql(nested, f"{path}[{index}]")
    elif isinstance(value, str) and "query_manufacturing_data" in value:
        raise AssertionError(f"retired SQL capability restored at {path}")


def _assert_catalog(tools: list[dict[str, object]], manifest: dict[str, Any]) -> None:
    expected = list(manifest["nativeBusinessTools"]) + list(manifest["protocolTools"])
    names = _names(tools)
    if set(names) != set(expected):
        raise AssertionError(f"default v2 tool names differ: {names!r}")
    if len(names) != len(set(names)) or len(names) != 22:
        raise AssertionError("default v2 catalog must contain 21 business tools plus protocol")
    if names[-1] != "submit_analysis":
        raise AssertionError("submit_analysis must remain the non-executable protocol tool")
    _assert_no_sql(tools)
    definitions = {definition.name: definition for definition in BUSINESS_TOOL_DEFINITIONS}
    if set(definitions) != set(manifest["nativeBusinessTools"]):
        raise AssertionError("native definitions differ from the v2 manifest")
    for item in tools[:-1]:
        function = item["function"]
        name = str(function["name"])
        if function.get("parameters") != definitions[name].json_schema():
            raise AssertionError(f"catalog schema differs from native definition: {name}")


def _assert_sql_restoration_is_rejected(manifest: dict[str, Any]) -> None:
    restored = [*TOOLS, {
        "type": "function",
        "function": {
            "name": "query_manufacturing_data",
            "description": "restoration negative control",
            "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}},
        },
    }]
    try:
        _assert_catalog(restored, manifest)
    except AssertionError:
        return
    raise AssertionError("SQL restoration negative control was accepted")


def check(manifest_path: Path = MANIFEST_PATH) -> None:
    manifest = _load_manifest(manifest_path)
    if manifest.get("schemaVersion") != "1.0":
        raise AssertionError("unsupported v2 capability manifest schema")
    if manifest.get("capabilityVersion") != DEFAULT_CAPABILITY_VERSION:
        raise AssertionError("capability version differs from native definitions")
    if manifest.get("planner") != {
        "executionPlanSchemaVersion": "1.2",
        "playbookSchemaVersion": "2.0",
        "plannerVersion": NAMED_QUERY_CAPABILITY_VERSION,
    }:
        raise AssertionError("planner version contract differs")
    if manifest.get("namedQueryMappings") != {
        evidence_id: list(tools) for evidence_id, tools in _TOOL_REPLACEMENTS.items()
    }:
        raise AssertionError("named-query replacement mappings differ")
    expected_named_tools = {
        tool: evidence_id
        for evidence_id, tools in _TOOL_REPLACEMENTS.items()
        for tool in tools
    }
    if manifest.get("namedToolMappings") != expected_named_tools:
        raise AssertionError("eight named-tool mappings differ")
    if manifest.get("retiredTools") != ["query_manufacturing_data"]:
        raise AssertionError("retired SQL capability declaration differs")
    _assert_catalog(TOOLS, manifest)
    if agent.TOOLS is not TOOLS or compatibility_catalog.TOOLS is not TOOLS:
        raise AssertionError("default catalog compatibility aliases lost container identity")
    if compatibility_registry.TOOL_HANDLERS is not DEFAULT_TOOL_REGISTRY.legacy_handlers:
        raise AssertionError("legacy handler compatibility alias lost container identity")
    if len(compatibility_registry.TOOL_HANDLERS) != 13:
        raise AssertionError("legacy compatibility bridge must retain exactly 13 handlers")
    if "query_manufacturing_data" in compatibility_registry.TOOL_HANDLERS:
        raise AssertionError("SQL handler must not remain in the default compatibility bridge")
    for name in ("query_manufacturing_data", "submit_analysis"):
        try:
            DEFAULT_TOOL_REGISTRY.resolve(name)
        except ValueError:
            continue
        raise AssertionError(f"{name} must not resolve as an executable default tool")
    if any(
        marker in agent.SYSTEM_PROMPT
        for marker in (
            "query_manufacturing_data",
            "数据库字段提示",
            "- lots:",
            "- process_runs:",
            "- wafer_maps:",
        )
    ):
        raise AssertionError("default system prompt exposes a SQL schema capability")
    dependencies = agent._coordinator_dependencies()
    if dependencies.tool_run_factory is None:
        raise AssertionError("default coordinator must assemble a per-run native tool bundle")
    if build_default_coordinator_dependencies.__module__ != "app.bootstrap.default_coordinator_assembly":
        raise AssertionError("default coordinator factory import is not stable")
    planning = dependencies.preparation.agent_preparation_dependencies().planning
    if planning.select_playbook is not select_named_playbook:
        raise AssertionError("default planning did not select named v2 playbooks")
    if planning.create_execution_plan is not create_named_execution_plan:
        raise AssertionError("default planning did not select the named v2 planner")
    route = route_question("分析 CMP 良率下降", current_date=date(2026, 10, 31))
    selection = planning.select_playbook(route)
    plan = planning.create_execution_plan("分析 CMP 良率下降", route, selection)
    if plan.schema_version != "1.2" or plan.planner_version != NAMED_PLAYBOOK_VERSION:
        raise AssertionError("default planning did not produce a v2 execution plan")
    if any(step.tool == "query_manufacturing_data" for step in plan.steps):
        raise AssertionError("default planning produced a retired SQL tool")
    _assert_sql_restoration_is_rejected(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    arguments = parser.parse_args()
    check(arguments.manifest)
    print("MOD-008 default v2 native capability migration passed (static, no I/O).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
