from __future__ import annotations

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.loop_tool_round import _execute_legacy_call
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.execution.tool_result_bridge import project_tool_result
from app.agent_runtime.tools.contracts import (
    ToolError,
    ToolErrorKind,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
    tool_error_details,
)
from app.agent_runtime.tools.dispatch_contracts import (
    PolicyDecision,
    ToolDataSourceError,
    ToolSourceTimeout,
)
from app.evidence.validator import EvidenceObservation
from tests import test_tool_dispatcher as dispatcher_fixture
from tests.test_ready_plan_execution import _plan


class ToolErrorBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = dispatcher_fixture.DispatcherTests()
        self.calls = []

    def handler(self, value, context):
        self.calls.append(value)
        return ToolResult(context.call_id, "native", "v1", ToolStatus.SUCCEEDED,
                          ToolExecutionState.COMPLETED, data=[])

    async def test_policy_reason_is_preserved_and_untrusted_description_is_not_exposed(self):
        for code in ("ROLE_DENIED", "SCOPE_DENIED", "CAPABILITY_DENIED"):
            with self.subTest(code=code):
                dispatcher = self.fixture.dispatcher(self.fixture.binding(self.handler),
                    policy=dispatcher_fixture.Policy(PolicyDecision(False, code, "private-host password=secret")))
                result = await dispatcher.dispatch("native", {"value":"x"}, self.fixture.context())
                self.assertEqual(result.error.code, code)
                details = project_tool_result(result).event
                self.assertEqual(details["recovery_action"], "request_access")
                self.assertFalse(details["retryable"])
                self.assertNotIn("secret", json.dumps(details))
        self.assertEqual(self.calls, [])

    async def test_unknown_policy_code_uses_safe_fallback(self):
        dispatcher = self.fixture.dispatcher(self.fixture.binding(self.handler),
            policy=dispatcher_fixture.Policy(PolicyDecision(False, "private-connection", "secret")))
        result = await dispatcher.dispatch("native", {"value":"x"}, self.fixture.context())
        self.assertEqual(result.error.code, "POLICY_DENIED")
        self.assertNotIn("private", json.dumps(project_tool_result(result).trace))
        self.assertEqual(self.calls, [])

    async def test_parsing_and_validation_share_code_but_retain_distinct_categories(self):
        class ValidatingInput(dispatcher_fixture.Input):
            @classmethod
            def from_arguments(cls, arguments):
                if not isinstance(arguments.get("value"), str):
                    raise ValueError("private input")  # noqa: TRY004 - input protocol reports validation with ValueError
                return cls(arguments["value"])
        binding = self.fixture.binding(self.handler)
        binding = replace(binding, definition=replace(binding.definition, input_model=ValidatingInput))
        dispatcher = self.fixture.dispatcher(binding)
        results = [await dispatcher.dispatch("native", raw, self.fixture.context()) for raw in ("[", {})]
        self.assertEqual([r.error.code for r in results], ["INVALID_ARGUMENTS"]*2)
        self.assertEqual([r.error.kind.value for r in results], ["parsing", "validation"])
        self.assertEqual(results[0].error.public_message, results[1].error.public_message)
        self.assertEqual(self.calls, [])

    async def test_real_guard_blocks_duplicate_without_reexecuting_handler(self):
        guard = ToolLoopGuard(_plan())
        dispatcher = self.fixture.dispatcher(self.fixture.binding(self.handler), budget=LoopGuardToolBudget(guard))
        # Exercise the real guard rather than a stub denial.
        guard.plan = replace(guard.plan, budget=replace(guard.plan.budget, per_tool_limits={"native":3}))
        first = await dispatcher.dispatch("native", {"value":"x"}, self.fixture.context())
        second = await dispatcher.dispatch("native", {"value":"x"}, self.fixture.context())
        self.assertEqual(first.status, ToolStatus.SUCCEEDED)
        self.assertEqual(second.error.code, "DUPLICATE_ARGUMENTS")
        self.assertEqual(project_tool_result(second).trace["recovery_action"], "use_existing_results")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(guard.total_calls, 1)

    async def test_source_failure_is_not_a_successful_empty_result(self):
        def broken(value, context):
            self.calls.append(value)
            raise ToolDataSourceError("password=secret")
        result = await self.fixture.dispatcher(self.fixture.binding(broken)).dispatch(
            "native", {"value":"x"}, self.fixture.context())
        projection = project_tool_result(result)
        self.assertEqual(result.error.code, "DATA_SOURCE_FAILED")
        self.assertEqual(projection.observation["status"], "error")
        self.assertIsNone(projection.observation["result"])
        self.assertEqual(projection.event["recovery_action"], "report_source_failure")
        self.assertNotIn("secret", json.dumps(projection.event))
        self.assertEqual(len(self.calls), 1)

    async def test_timeout_retains_unknown_state_and_prevents_retry_guidance(self):
        def timeout(value, context):
            raise ToolSourceTimeout("private endpoint")
        result = await self.fixture.dispatcher(self.fixture.binding(timeout)).dispatch(
            "native", {"value":"x"}, self.fixture.context())
        details = project_tool_result(result).event
        self.assertEqual(details["error_code"], "SOURCE_TIMEOUT")
        self.assertEqual(details["execution_state"], "unknown")
        self.assertEqual(details["recovery_action"], "check_execution_state")
        self.assertFalse(details["retryable"])
        error = ToolError("SOURCE_TIMEOUT", "safe", ToolErrorKind.TIMEOUT, True)
        self.assertFalse(tool_error_details(error, ToolExecutionState.UNKNOWN)["retryable"])

    async def test_legacy_loop_returns_same_safe_error_to_model_trace_and_progress(self):
        events = []
        async def notify(_progress, event):
            events.append(event)
        from app.agent_runtime.tools.dispatch_contracts import ToolInputError
        for exception, code, action in (
            (ToolDataSourceError, "DATA_SOURCE_FAILED", "report_source_failure"),
            (PermissionError, "TOOL_DENIED", "request_access"),
            (ToolInputError, "INVALID_ARGUMENTS", "correct_arguments"),
        ):
            with self.subTest(code=code):
                calls = []
                def execute(_name, _arguments, _calls=calls, _exception=exception):
                    _calls.append(_name)
                    raise _exception("password=secret localhost/internal")
                guard = ToolLoopGuard(_plan())
                context = SimpleNamespace(run_id="errors-test", progress=None, messages=[], trace=[], sources={},
                    evidence_observations=[], loop_guard=guard, emit_event=lambda *_a, **_k:None, notify=notify,
                    evidence_observation_type=EvidenceObservation, parse_tool_arguments=lambda raw:(json.loads(raw),None),
                    execute_tool=execute)
                await _execute_legacy_call(context, {"id":"one","function":{"name":"get_process_capability","arguments":"{}"}})
                payload = json.loads(context.messages[0]["content"])
                self.assertEqual(payload["error_code"], code)
                self.assertEqual(payload["execution_state"], "completed")
                self.assertEqual(calls, ["get_process_capability"])
                self.assertEqual(context.trace[0]["error_code"], payload["error_code"])
                self.assertEqual(events[-1]["recovery_action"], action)
                self.assertNotIn("secret", json.dumps([payload, context.trace, events]))
                self.assertEqual(context.evidence_observations[0].status, "error")

    async def test_dispatched_loop_preserves_failure_in_model_message_and_progress(self):
        from app.agent_runtime.execution.loop_dispatch import (
            execute_dispatched_loop_round,
        )
        from app.agent_runtime.execution.loop_response import classify_loop_response
        from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
        from tests import test_loop_dispatcher as loop_fixture

        plan = loop_fixture._plan()
        projector = ReadyResultPolicy()
        dispatcher = loop_fixture._dispatcher(plan, [], projector)
        dispatcher.policy = dispatcher_fixture.Policy(PolicyDecision(False, "SCOPE_DENIED", "private scope"))
        guard, binding = loop_fixture._binding(plan, dispatcher, projector)
        events = []
        async def notify(_progress, event):
            events.append(event)
        response = classify_loop_response({"tool_calls":[{"id":"model-1","function":{
            "name":"native","arguments":'{"value":"x"}'}}]})
        outcome = await execute_dispatched_loop_round(plan, guard, "run", 1, response,
            None, binding=binding, notify=notify, emit_event=lambda *_a, **_k:None)
        payload = json.loads(outcome.tool_messages[0]["content"])
        self.assertEqual(payload["error_code"], "SCOPE_DENIED")
        self.assertEqual(payload["recovery_action"], "request_access")
        self.assertEqual(outcome.trace[0]["error_code"], events[-1]["error_code"])
        self.assertFalse(payload["retryable"])
