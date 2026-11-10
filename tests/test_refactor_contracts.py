from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.bootstrap import tool_catalog
from scripts.refactor_contracts import (
    LEGACY_TOOL_CATALOG,
    collect_agent_contract,
    collect_api_contract,
    collect_frontend_contract,
    collect_tool_contract,
    contract_diff,
    load_contract,
    load_legacy_tools,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TOOL_NAMES = [
    "get_equipment_health",
    "get_process_capability",
    "get_sensor_summary",
    "get_fab_overview",
    "get_yield_trend",
    "get_process_pass_rate",
    "get_equipment_productivity",
    "get_defect_pareto",
    "get_recent_excursions",
    "get_enterprise_data_manifest",
    "get_enterprise_fab_summary",
    "query_enterprise_data",
    "search_knowledge",
    "get_product_yield_breakdown",
    "get_equipment_event_timeline",
    "get_equipment_excursion_history",
    "get_lot_identity",
    "get_lot_process_history",
    "get_lot_excursion_history",
    "get_lot_defect_history",
    "get_lot_wafer_map_patterns",
    "submit_analysis",
]


class RefactorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = load_contract()

    def assert_contract_section(self, section: str, actual: dict) -> None:
        expected = self.expected[section]
        self.assertEqual(actual, expected, contract_diff({section: expected}, {section: actual}))

    def test_contract_is_versioned_redacted_and_offline(self):
        self.assertEqual(self.expected["contract_version"], "1.0")
        self.assertEqual(self.expected["data_classification"], "synthetic_redacted")
        self.assertEqual(
            self.expected["execution_policy"],
            {"network_calls": 0, "real_model_calls": 0},
        )
        serialized = json.dumps(self.expected, ensure_ascii=False).lower()
        for forbidden in ("authorization", "api_key", "password", "reasoning_content"):
            self.assertNotIn(forbidden, serialized)

    def test_historical_tool_names_and_schemas_match_legacy_v1_baseline(self):
        self.assert_contract_section("tools", collect_tool_contract("legacy-v1"))

    def test_openapi_routes_statuses_and_schema_match_baseline(self):
        self.assert_contract_section("api", collect_api_contract())

    def test_dom_identifiers_and_script_order_match_baseline(self):
        self.assert_contract_section("frontend", collect_frontend_contract())

    def test_agent_result_trace_and_event_order_match_offline_baseline(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            actual = collect_agent_contract()
        self.assert_contract_section("agent", actual)


class FrozenLegacyToolCatalogTests(unittest.TestCase):
    def test_application_never_references_frozen_legacy_catalog(self):
        offenders = [
            path.relative_to(PROJECT_DIR).as_posix()
            for path in (PROJECT_DIR / "app").rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".json", ".toml", ".yaml", ".yml", ".txt"}
            and any(
                marker in path.read_text(encoding="utf-8", errors="replace")
                for marker in ("legacy_tool_catalog", "LEGACY_TOOLS")
            )
        ]
        self.assertEqual(offenders, [])
        self.assertFalse(hasattr(tool_catalog, "LEGACY_TOOLS"))
        self.assertNotIn("LEGACY_TOOLS", tool_catalog.__all__)

    def test_frozen_sample_keeps_sql_tool_only_as_history(self):
        legacy_names = [item["function"]["name"] for item in load_legacy_tools()]
        default_names = [item["function"]["name"] for item in tool_catalog.TOOLS]
        self.assertIn("query_manufacturing_data", legacy_names)
        self.assertNotIn("query_manufacturing_data", default_names)
        self.assertEqual(default_names, DEFAULT_TOOL_NAMES)

    def test_loader_returns_independent_copies_and_rejects_invalid_sample(self):
        first = load_legacy_tools()
        first[0]["function"]["name"] = "mutated"
        self.assertNotEqual(load_legacy_tools()[0]["function"]["name"], "mutated")
        self.assertEqual(LEGACY_TOOL_CATALOG.name, "legacy_tool_catalog_v1.json")
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "catalog.json"
            for document in ({"tools": []}, {"tools": [{"type": "x"}]}, []):
                invalid.write_text(json.dumps(document), encoding="utf-8")
                with self.subTest(document=document), self.assertRaises(ValueError):
                    load_legacy_tools(invalid)


if __name__ == "__main__":
    unittest.main()
