"""Analysis references of one chat turn come from the attached field and the tool trace only."""

from __future__ import annotations

import unittest

from app.api.services.analysis_attachment import analysis_references

A = "lca_" + "a" * 32
B = "lca_" + "b" * 32
C = "lca_" + "c" * 32


def _created(reference, status="succeeded", adapter="lot_commonality"):
    return {
        "tool": "create_lot_commonality_analysis",
        "tool_status": status,
        "sources": [{"source_ref": reference, "adapter_id": adapter}],
    }


def _read(reference, tool="read_lot_commonality_members", status="succeeded"):
    return {"tool": tool, "tool_status": status, "arguments": {"analysis_ref": reference}}


class AnalysisReferencesTests(unittest.TestCase):
    def test_attached_first_then_created_and_read_without_duplicates(self):
        result = {
            "answer": f"模型提到了 {C}",
            "tool_trace": [
                _read(A),
                _created(B),
                _read(B, "read_lot_commonality_records"),
                _created(C, status="failed"),
                _read(C, status="denied"),
            ],
        }
        self.assertEqual(
            analysis_references(result, A),
            [{"analysis_ref": A, "origin": "attached"}, {"analysis_ref": B, "origin": "created"}],
        )

    def test_other_tools_foreign_sources_and_malformed_values_are_ignored(self):
        result = {
            "tool_trace": [
                {"tool": "get_fab_overview", "tool_status": "succeeded", "arguments": {"analysis_ref": A}},
                _created(B, adapter="named_queries"),
                _read("lca_not-a-ref"),
                {"tool": "read_lot_commonality_members", "tool_status": "succeeded", "arguments": "x"},
                "not-a-mapping",
            ]
        }
        self.assertEqual(analysis_references(result), [])
        self.assertEqual(analysis_references({"tool_trace": None}), [])


if __name__ == "__main__":
    unittest.main()
