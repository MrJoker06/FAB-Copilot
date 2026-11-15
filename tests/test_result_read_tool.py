from __future__ import annotations

import asyncio
import concurrent.futures
import json
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolStatus
from app.agent_runtime.tools.projection import model_function_view
from app.agent_runtime.tools.result_access import (
    RESULT_READ_DEFINITION,
    ResultReadAccess,
    ResultReadInput,
    install_result_reader,
    result_read_content,
)
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry
from app.persistence.tool_result_store import ToolResultStore
from app.intent_runtime.routing import route_question
from app.planning_runtime.playbooks import select_playbook
from app.planning_runtime.service import create_execution_plan


class ResultReadToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ToolResultStore(Path(self.temp.name) / "results.db")
        self.store.initialize()
        self.principal = SimpleNamespace(
            tenant_id="tenant", user_id="owner", roles=("analyst",)
        )
        route = route_question("分析 CVD 制程能力", date(2026, 11, 15))
        playbook = select_playbook(route)
        self.guard = ToolLoopGuard(
            create_execution_plan("分析 CVD 制程能力", route, playbook)
        )
        self.access = ResultReadAccess(
            self.store,
            self.principal,
            "session",
            "new-run",
            self.guard,
            lambda: True,
            phase="synthesis",
            deadline=time.monotonic() + 60,
        )
        self.registry = ToolRegistry()
        self.dispatcher = install_result_reader(self.registry, self.access)
        self.ref = self.store.save(
            tenant_id="tenant",
            owner_id="owner",
            session_id="session",
            run_id="old-run",
            call_id="original",
            metadata={
                "queried_at": "2026-11-14",
                "scope": {"equipment": "A"},
                "source_ref": "TOOL:S1",
            },
            content=[{"value": 1}, {"value": 2}],
            permit=lambda: True,
        )

    def dispatch(self, arguments=None, *, principal=None, name="read_tool_result"):
        context = ToolExecutionContext(
            principal or self.principal, "new-run", "read-call", None
        )
        return asyncio.run(
            self.dispatcher.dispatch(
                name, arguments or {"result_ref": self.ref}, context
            )
        )

    def test_real_dispatcher_reads_old_run_without_business_evidence_or_progress(self):
        before = self.guard.summary()
        result = self.dispatch({"result_ref": self.ref, "limit": 1})
        self.assertIs(result.status, ToolStatus.SUCCEEDED)
        self.assertEqual(result.data["units"], [{"value": 1}])
        self.assertEqual(result.data["queried_at"], "2026-11-14")
        self.assertEqual(self.guard.total_calls, 1)
        for name in (
            "per_tool_calls",
            "unique_evidence_results",
            "consecutive_no_progress_rounds",
            "stop_reason",
        ):
            self.assertEqual(self.guard.summary()[name], before[name])
        self.assertEqual(
            self.access.response_bytes, len(result_read_content(result).encode("utf-8"))
        )

    def test_input_validation_and_single_description_source(self):
        schema = model_function_view(RESULT_READ_DEFINITION)["function"]["parameters"]
        self.assertEqual(schema, ResultReadInput.json_schema())
        self.assertFalse(schema["additionalProperties"])
        for args in (
            {"result_ref": self.ref, "limit": True},
            {"result_ref": self.ref, "sql": "SELECT 1"},
            {"result_ref": self.ref, "cursor": ""},
        ):
            self.assertIs(self.dispatch(args).status, ToolStatus.INVALID_ARGUMENTS)
        self.assertEqual(self.guard.total_calls, 0)
        with self.assertRaisesRegex(ValueError, "per-run registry"):
            install_result_reader(DEFAULT_TOOL_REGISTRY, self.access)

    def test_permission_denial_does_not_read_body(self):
        def forbidden(**kwargs):
            self.fail("reader was reached after denial")

        self.access.reader = SimpleNamespace(read=forbidden)
        viewer = SimpleNamespace(tenant_id="tenant", user_id="owner", roles=("viewer",))
        self.assertIs(self.dispatch(principal=viewer).status, ToolStatus.DENIED)
        self.access.authorize = lambda: False
        self.assertIs(self.dispatch().status, ToolStatus.DENIED)
        self.assertEqual(self.guard.total_calls, 0)

    def test_phase_switch_cancel_deadline_and_final_round_are_enforced(self):
        self.access.phase = "collection"
        self.assertIs(self.dispatch().status, ToolStatus.DENIED)
        self.access.phase = "synthesis"
        self.access.enabled = False
        self.assertIs(self.dispatch().status, ToolStatus.DENIED)
        self.access.enabled = True
        self.access.cancelled = lambda: True
        self.assertIs(self.dispatch().status, ToolStatus.DENIED)
        self.access.cancelled = lambda: False
        self.access.deadline = time.monotonic() - 1
        self.assertIs(self.dispatch().status, ToolStatus.DENIED)
        self.access.deadline = time.monotonic() + 60
        self.guard.reserve_final_iteration()
        self.assertIsNot(self.dispatch().status, ToolStatus.SUCCEEDED)
        self.assertEqual(self.guard.total_calls, 0)

    def test_failures_count_and_shared_budget_is_not_reset_by_reads(self):
        self.guard.total_calls = self.guard.plan.budget.max_tool_calls - 1
        self.guard.enter_synthesis("no_progress", "no more business reads")
        result = self.dispatch({"result_ref": "unknown"})
        self.assertIs(result.status, ToolStatus.DENIED)
        self.assertEqual(self.access.reads, 1)
        self.assertEqual(self.guard.total_calls, self.guard.plan.budget.max_tool_calls)
        self.assertIsNot(self.dispatch().status, ToolStatus.SUCCEEDED)
        self.assertEqual(self.access.reads, 1)
        self.assertEqual(self.guard.stop_reason, "no_progress")

    def test_auxiliary_limit_and_direct_handler_cannot_bypass_claims(self):
        context = ToolExecutionContext(self.principal, "new-run", "direct", None)
        value = ResultReadInput(self.ref)
        self.assertIs(self.access.read(value, context).status, ToolStatus.DENIED)
        for _ in range(4):
            self.assertIs(self.dispatch().status, ToolStatus.SUCCEEDED)
        self.assertIsNot(self.dispatch().status, ToolStatus.SUCCEEDED)
        self.assertIs(self.access.read(value, context).status, ToolStatus.DENIED)
        self.assertEqual(self.guard.total_calls, 4)
        self.assertLessEqual(self.access.response_bytes, 16384)

    def test_output_schema_checks_actual_page(self):
        import jsonschema

        result = self.dispatch()
        jsonschema.validate(result.data, dict(RESULT_READ_DEFINITION.output_schema))
        denied = self.dispatch({"result_ref": "unknown"})
        self.assertIsNot(denied.status, ToolStatus.SUCCEEDED)
        self.assertFalse(json.loads(result_read_content(denied))["ok"])

    def test_parallel_dispatches_share_auxiliary_and_total_budget(self):
        async def run():
            return await asyncio.gather(
                *(
                    self.dispatcher.dispatch(
                        "read_tool_result",
                        {"result_ref": self.ref},
                        ToolExecutionContext(
                            self.principal, "new-run", f"parallel-{index}", None
                        ),
                    )
                    for index in range(8)
                )
            )

        results = asyncio.run(run())
        self.assertEqual(
            sum(item.status is ToolStatus.SUCCEEDED for item in results), 4
        )
        self.assertEqual(self.guard.total_calls, 4)
        self.assertEqual(self.access.reads, 4)
        self.assertEqual(self.access._pending, 0)
        self.assertLessEqual(self.access.response_bytes, 16384)
        self.assertFalse(self.guard.tool_calls)

    def test_business_and_auxiliary_claims_cannot_oversell_same_total(self):
        self.guard.total_calls = self.guard.plan.budget.max_tool_calls - 1

        def claim(index):
            if index % 2:
                return self.guard.claim_auxiliary_read()
            return self.guard.check_call(
                "get_process_capability", {"process_step": "CVD", "limit": index}
            ).allowed

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            decisions = list(pool.map(claim, range(8)))
        self.assertEqual(sum(decisions), 1)
        self.assertEqual(self.guard.total_calls, self.guard.plan.budget.max_tool_calls)


if __name__ == "__main__":
    unittest.main()
