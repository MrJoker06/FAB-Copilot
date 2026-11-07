"""MOD-015c: the model/tool loop split keeps behavior identical to the pre-split loop."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import inspect
import json
import unittest
from pathlib import Path

from app.agent_runtime.execution import agent_loop
from app.agent_runtime.execution.loop_state import LoopRunState
from tests import agent_loop_split_scenarios as scenarios

ROOT = Path(__file__).resolve().parents[1]
EXECUTION = ROOT / "app/agent_runtime/execution"
LOOP_MODULES = {
    "loop_state.py": 120,
    "loop_request.py": 300,
    "loop_model_call.py": 300,
    "loop_answer.py": 300,
    "loop_tool_round.py": 300,
    "loop_round_validation.py": 300,
}
SYNC_FIELDS = set(scenarios.SYNC_FIELDS)


def _source(name: str) -> str:
    return (EXECUTION / name).read_text(encoding="utf-8")


class AgentLoopStructureTests(unittest.TestCase):
    def test_agent_loop_is_a_short_orchestrator_within_line_budget(self):
        self.assertLessEqual(len(_source("agent_loop.py").splitlines()), 250)
        for name, budget in LOOP_MODULES.items():
            with self.subTest(module=name):
                self.assertLessEqual(len(_source(name).splitlines()), budget)
        body = inspect.getsource(agent_loop.run_agent_loop)
        self.assertLessEqual(len(body.splitlines()), 60)
        for delegate in (
            "LoopRunState.from_context",
            "prepare_round_request",
            "call_model",
            "finish_text_answer",
            "finish_submission",
            "execute_tool_round",
            "validate_round",
            "finish_iteration_limit",
        ):
            self.assertIn(delegate, body)

    def test_public_names_stay_owned_by_agent_loop(self):
        from app.agent_runtime import execution

        self.assertIs(execution.run_agent_loop, agent_loop.run_agent_loop)
        self.assertIs(execution.AgentLoopContext, agent_loop.AgentLoopContext)
        self.assertEqual(agent_loop.run_agent_loop.__module__, agent_loop.__name__)
        self.assertEqual(agent_loop.LOOP_SYNTHESIS_MAX_TOKENS, 8192)
        self.assertEqual(
            list(inspect.signature(agent_loop.run_agent_loop).parameters),
            ["context", "dispatch_binding"],
        )

    def test_loop_run_state_is_the_single_holder_of_mutable_run_facts(self):
        self.assertTrue(hasattr(LoopRunState, "__slots__"))
        fields = {field.name for field in dataclasses.fields(LoopRunState)}
        self.assertEqual(fields, SYNC_FIELDS | {"thinking_answer_effective"})
        for name in ("agent_loop.py", *LOOP_MODULES):
            tree = ast.parse(_source(name))
            with self.subTest(module=name):
                for node in tree.body:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        value = node.value
                        self.assertNotIsInstance(
                            value,
                            (
                                ast.List,
                                ast.Dict,
                                ast.Set,
                                ast.ListComp,
                                ast.DictComp,
                                ast.Call,
                            ),
                        )
                accesses = [
                    (type(node.ctx).__name__, node.attr)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)
                    and node.attr in SYNC_FIELDS
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "context"
                ]
                if name == "loop_state.py":
                    # One snapshot read and one write-back per field, nothing else.
                    self.assertEqual(
                        sorted(accesses),
                        sorted(
                            [("Load", field) for field in SYNC_FIELDS]
                            + [("Store", field) for field in SYNC_FIELDS]
                        ),
                    )
                else:
                    self.assertEqual(accesses, [])

    def test_split_modules_keep_model_access_behind_the_gateway_port(self):
        for name in ("agent_loop.py", *LOOP_MODULES):
            source = _source(name)
            with self.subTest(module=name):
                for forbidden in (
                    "import httpx",
                    "AsyncClient",
                    "/chat/completions",
                    "Bearer",
                ):
                    self.assertNotIn(forbidden, source)

    def test_timing_sleep_and_traceback_patch_points_stay_module_attributes(self):
        model_call = _source("loop_model_call.py")
        tool_round = _source("loop_tool_round.py")
        self.assertIn("await asyncio.sleep(delay_seconds)", model_call)
        self.assertIn("time.perf_counter()", model_call)
        self.assertIn("traceback.format_exc()", model_call)
        self.assertIn("traceback.format_exc()", tool_round)
        self.assertIn("time.perf_counter()", _source("loop_answer.py"))


class AgentLoopGoldenEquivalenceTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(scenarios.GOLDEN_PATH.read_text(encoding="utf-8"))

    def test_golden_covers_every_scenario(self):
        self.assertEqual(sorted(self.golden), sorted(scenarios.SCENARIO_NAMES))
        self.assertGreaterEqual(len(self.golden), 30)

    def test_every_scenario_matches_the_pre_split_golden(self):
        for name in scenarios.SCENARIO_NAMES:
            with self.subTest(scenario=name):
                actual = json.loads(
                    json.dumps(scenarios.run_scenario(name), ensure_ascii=False)
                )
                expected = self.golden[name]
                self.assertEqual(actual["outcome"], expected["outcome"])
                self.assertEqual(actual["log"], expected["log"])
                self.assertEqual(actual["final"], expected["final"])


class AgentLoopCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_cancellation_mid_stream_propagates_without_extra_sync(self):
        recorder = scenarios.Recorder()
        plan, guard, binding = scenarios._dispatch_fixture()
        started = asyncio.Event()

        async def hang(_payload, _progress, _state):
            started.set()
            await asyncio.Event().wait()

        round_one = scenarios.calls(
            ("model-call", "native", '{"value":"expected"}'), response_id="r-1"
        )
        context, gateway = scenarios.build_context(
            recorder,
            [round_one, hang],
            plan=plan,
            guard=guard,
            dispatch_binding=binding,
            knowledge_state={"used": True, "reason": "none", "disclosure": "补充"},
        )
        task = asyncio.create_task(agent_loop.run_agent_loop(context))
        await asyncio.wait_for(started.wait(), timeout=2)
        synced_after_round_one = {name: getattr(context, name) for name in SYNC_FIELDS}
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((gateway.opened, gateway.closed), (1, 1))
        kinds = [entry["kind"] for entry in recorder.log]
        self.assertNotIn("record_model_failure", kinds)
        self.assertNotIn("build_result", kinds)
        self.assertEqual(
            [entry["name"] for entry in recorder.log if entry["kind"] == "emit"][-1],
            "model_call_started",
        )
        self.assertEqual(
            {name: getattr(context, name) for name in SYNC_FIELDS},
            synced_after_round_one,
        )
        self.assertTrue(context.fallback_announced)
        self.assertEqual(context.health, {"status": "healthy", "model": "model-a"})

    async def test_legacy_cancellation_never_syncs_context(self):
        recorder = scenarios.Recorder()
        started = asyncio.Event()

        async def hang(_payload, _progress, _state):
            started.set()
            await asyncio.Event().wait()

        context, gateway = scenarios.build_context(
            recorder,
            [scenarios.calls(("x1", "alpha", '{"q": 1}')), hang],
            required_total=0,
            knowledge_state={"used": True, "reason": "none", "disclosure": "补充"},
        )
        initial = {name: getattr(context, name) for name in SYNC_FIELDS}
        task = asyncio.create_task(agent_loop.run_agent_loop(context))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((gateway.opened, gateway.closed), (1, 1))
        self.assertEqual(
            {name: getattr(context, name) for name in SYNC_FIELDS}, initial
        )
        self.assertNotIn(
            "record_model_failure", [entry["kind"] for entry in recorder.log]
        )


if __name__ == "__main__":
    unittest.main()
