from __future__ import annotations

import contextlib
import io
import json
import unittest

from app.bootstrap.dispatcher_demo import main


class DispatcherDemoTests(unittest.TestCase):
    def run_demo(self, *arguments: str):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(arguments))
        return code, json.loads(output.getvalue())

    def test_default_and_equipment_filter_are_successful_and_structured(self):
        for arguments in ((), ("--arguments", '{"equipment_id":"demo-02"}')):
            with self.subTest(arguments=arguments):
                code, payload = self.run_demo(*arguments)
                self.assertEqual(code, 0)
                self.assertEqual(payload["result"]["status"], "succeeded")
                self.assertEqual(payload["result"]["execution_state"], "completed")
                self.assertIn("call_id", payload["result"])

    def test_tenant_role_sql_malformed_and_budget_are_sanitized(self):
        cases = (
            ("--tenant-id", "other"),
            ("--role", "viewer"),
            ("--tool", "sql_query"),
            ("--arguments", "{"),
            ("--max-tool-calls", "0"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, payload = self.run_demo(*arguments)
                self.assertEqual(code, 2)
                self.assertIn(
                    payload["result"]["status"],
                    {"denied", "invalid_arguments", "blocked", "failed"},
                )
                error = payload["result"]["error"]
                self.assertIsInstance(error, dict)
                self.assertNotIn("sql_query", error["public_message"])

    def test_operator_errors_have_no_traceback_or_paths(self):
        code, payload = self.run_demo("--timeout-ms", "-1")
        self.assertEqual(code, 2)
        self.assertEqual(payload, {"error": "Invalid operator arguments."})


if __name__ == "__main__":
    unittest.main()
