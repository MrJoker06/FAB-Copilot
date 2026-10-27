from __future__ import annotations

import unittest
from datetime import date

from app.agent_runtime.execution.tool_result_bridge import project_tool_result
from app.agent_runtime.tools.contracts import (
    ToolError,
    ToolErrorKind,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)
from app.evidence.validator import EvidenceObservation


def make(status, sources=(), data=None):
    kinds = {
        ToolStatus.INVALID_ARGUMENTS: ToolErrorKind.VALIDATION,
        ToolStatus.DENIED: ToolErrorKind.AUTHORIZATION,
        ToolStatus.BLOCKED: ToolErrorKind.BUDGET,
        ToolStatus.FAILED: ToolErrorKind.DATA_SOURCE,
        ToolStatus.TIMED_OUT: ToolErrorKind.TIMEOUT,
        ToolStatus.CANCELLED: ToolErrorKind.CANCELLATION,
    }
    ok = status is ToolStatus.SUCCEEDED
    return ToolResult(
        "c",
        "tool",
        "1",
        status,
        ToolExecutionState.COMPLETED if ok else ToolExecutionState.NOT_STARTED,
        data=data if ok else None,
        error=None if ok else ToolError("SAFE", "safe failure", kinds[status]),
        sources=sources,
        row_count=1 if ok else None,
        elapsed_ms=1.0,
    )


class ToolResultBridgeTests(unittest.TestCase):
    def test_success_is_evidence_compatible_and_source_scope_replaces_filters(self):
        source = ToolSource(
            "source",
            "adapter",
            ToolSourceKind.FAKE,
            ToolScope("tenant", date(2026, 1, 1), date(2026, 1, 2), ("EQ",), ("ETCH",)),
        )
        projection = project_tool_result(
            make(ToolStatus.SUCCEEDED, (source,), [{"ok": 1}]),
            arguments={"sql": "secret", "process_step": "BAD"},
            step_id="s",
        )
        observation = EvidenceObservation(**projection.observation)
        self.assertEqual(observation.source_ref, "TOOL:s")
        self.assertEqual(
            observation.arguments,
            {
                "sql": "secret",
                "start": "2026-01-01",
                "end": "2026-01-02",
                "equipment_id": "EQ",
                "process_step": "ETCH",
            },
        )
        self.assertIs(observation.result, projection.observation["result"])
        self.assertEqual(projection.trace["duration_ms"], 1.0)

    def test_equipment_only_scope_drops_untrusted_submitted_process(self):
        source = ToolSource(
            "source",
            "adapter",
            ToolSourceKind.FAKE,
            ToolScope("tenant", equipment_ids=("EQ",)),
        )
        projection = project_tool_result(
            make(ToolStatus.SUCCEEDED, (source,), []),
            arguments={"equipment_id": "BAD", "process_step": "BAD"},
        )
        self.assertEqual(projection.observation["arguments"], {"equipment_id": "EQ"})

    def test_multiple_scopes_and_all_failure_statuses(self):
        sources = tuple(
            ToolSource(
                str(index),
                "a",
                ToolSourceKind.FAKE,
                ToolScope("tenant", equipment_ids=(equipment,)),
            )
            for index, equipment in enumerate(("A", "B"))
        )
        self.assertEqual(
            project_tool_result(make(ToolStatus.SUCCEEDED, sources, [])).observation[
                "arguments"
            ],
            {"equipment_id": ["A", "B"]},
        )
        for status in ToolStatus:
            if status is ToolStatus.SUCCEEDED:
                continue
            with self.subTest(status=status):
                projection = project_tool_result(
                    make(status), arguments={"sql": "select secret"}
                )
                self.assertEqual(projection.observation["arguments"], {})
                self.assertEqual(projection.sources, ())
                self.assertEqual(projection.trace["tool_status"], status.value)
                self.assertEqual(projection.trace["error_code"], "SAFE")

    def test_legacy_success_without_sources_does_not_fake_provenance(self):
        projection = project_tool_result(
            make(ToolStatus.SUCCEEDED, data={"ok": True}), arguments={"lot": "L1"}
        )
        self.assertEqual(projection.observation["arguments"], {"lot": "L1"})
        self.assertEqual(projection.sources, ())


if __name__ == "__main__":
    unittest.main()
