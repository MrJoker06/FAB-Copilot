from __future__ import annotations

import json
import socket
import unittest
from unittest.mock import patch

from scripts.refactor_contracts import (
    collect_agent_contract,
    collect_api_contract,
    collect_frontend_contract,
    collect_tool_contract,
    contract_diff,
    load_contract,
)


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

    def test_tool_names_and_complete_schemas_match_baseline(self):
        self.assert_contract_section("tools", collect_tool_contract())

    def test_openapi_routes_statuses_and_schema_match_baseline(self):
        self.assert_contract_section("api", collect_api_contract())

    def test_dom_identifiers_and_script_order_match_baseline(self):
        self.assert_contract_section("frontend", collect_frontend_contract())

    def test_agent_result_trace_and_event_order_match_offline_baseline(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            actual = collect_agent_contract()
        self.assert_contract_section("agent", actual)


if __name__ == "__main__":
    unittest.main()
