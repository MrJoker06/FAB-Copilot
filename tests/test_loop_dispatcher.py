from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import dataclass, fields, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.execution.agent_loop import AgentLoopContext, run_agent_loop
from app.agent_runtime.execution.loop_dispatch import (
    LoopDispatchBinding,
    execute_dispatched_loop_round,
)
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.loop_response import classify_loop_response
from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from app.agent_runtime.execution.runtime_contracts import (
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeContractError,
)
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)
from app.agent_runtime.tools.definition import ToolBinding, ToolDefinition
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.bootstrap import loop_demo, ready_demo
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "loop-test"
    roles: tuple[str, ...] = ("analyst",)


@dataclass(frozen=True)
class Input:
    value: str

    @classmethod
    def from_arguments(cls, arguments: dict[str, object]) -> Input:
        value = arguments.get("value")
        if not isinstance(value, str):
            raise TypeError
        return cls(value)

    @classmethod
    def json_schema(cls) -> dict[str, str]:
        return {"type": "object"}


def _step(*, parameters: dict[str, object] | None = None) -> PlanStep:
    return PlanStep(
        "S01",
        "native",
        "native",
        parameters or {"value": "expected"},
        {},
        (),
        (),
        True,
        (),
        1,
        "primary",
    )


def _plan(
    *, maximum: int = 2, parameters: dict[str, object] | None = None
) -> ExecutionPlan:
    step = _step(parameters=parameters)
    return ExecutionPlan(
        "loop-dispatch",
        "1",
        "test",
        "ready",
        "",
        "test",
        None,
        None,
        AnalysisScopeContract("fab", (), (), ()),
        (),
        (step,),
        PlanBudget(maximum, maximum, 3, 2, {"native": maximum}, 2, 2),
        (),
        (),
    )


def _binding(
    plan: ExecutionPlan, dispatcher: ToolDispatcher, projector: ReadyResultPolicy
):
    guard = dispatcher.budget.guard
    context = RuntimeContext(
        Principal(), "run", ToolExecutionLimits(remaining_calls=2, max_result_rows=1)
    )
    return guard, LoopDispatchBinding(
        plan,
        guard,
        context,
        dispatcher,
        projector.take_raw_rows,
        projector.extract_sources,
        projector.clear,
        json.dumps(dispatcher.registry.model_tools),
        guard.total_calls,
    )


def _dispatcher(
    plan: ExecutionPlan, rows: list[dict[str, object]], projector: ReadyResultPolicy
):
    registry = ToolRegistry()
    definition = ToolDefinition("native", "v1", "native", Input, lambda value: value)

    def handler(_input: Input, context):
        return ToolResult(
            context.call_id,
            "native",
            "v1",
            ToolStatus.SUCCEEDED,
            ToolExecutionState.COMPLETED,
            list(rows),
            sources=(
                ToolSource(
                    "fake:native", "fake", ToolSourceKind.FAKE, ToolScope("demo")
                ),
            ),
        )

    registry.register_native(ToolBinding(definition, handler, object()))
    return ToolDispatcher(
        run_id="run",
        registry=registry,
        policy=DemoToolPolicy(frozenset({"native"}), tenant_id="demo"),
        budget=LoopGuardToolBudget(ToolLoopGuard(plan)),
        allowed_tools=frozenset({"native"}),
        result_policy=projector,
    )


class LoopResponseTests(unittest.TestCase):
    def test_classifier_preserves_raw_arguments_and_separates_submission(self):
        tools = classify_loop_response(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "model-1",
                        "function": {"name": "native", "arguments": '{"value":"x"}'},
                    }
                ],
            }
        )
        submission = classify_loop_response(
            ModelResponse(
                tool_calls=(ModelToolCall("model-2", "submit_analysis", "{}"),)
            )
        )
        mixed = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "model-3",
                        "function": {"name": "native", "arguments": "{}"},
                    },
                    {
                        "id": "model-4",
                        "function": {"name": "submit_analysis", "arguments": "{}"},
                    },
                ]
            }
        )
        self.assertEqual(
            (tools.kind, tools.tool_calls[0].arguments), ("tools", '{"value":"x"}')
        )
        self.assertEqual(submission.kind, "submission")
        self.assertEqual(mixed.kind, "mixed")
        self.assertEqual(classify_loop_response({"content": None}).kind, "text")
        self.assertEqual(classify_loop_response({"tool_calls": []}).kind, "text")
        for invalid in (None, {"content": 1}, {"tool_calls": [{}]}):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(
                    RuntimeContractError, "loop response is invalid"
                ),
            ):
                classify_loop_response(invalid)

    def test_classifier_rejects_duplicate_ids_and_multiple_submissions(self):
        for calls in (
            [
                {"id": "same", "function": {"name": "native", "arguments": "{}"}},
                {"id": "same", "function": {"name": "native", "arguments": "{}"}},
            ],
            [
                {
                    "id": "one",
                    "function": {"name": "submit_analysis", "arguments": "{}"},
                },
                {
                    "id": "two",
                    "function": {"name": "submit_analysis", "arguments": "{}"},
                },
            ],
        ):
            with (
                self.subTest(calls=calls),
                self.assertRaisesRegex(
                    RuntimeContractError, "loop response is invalid"
                ),
            ):
                classify_loop_response({"tool_calls": calls})


class LoopDispatcherTests(unittest.TestCase):
    def test_loop_and_ready_sqlite_health_have_matching_scope_and_tool_reference(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manufacturing, equipment = root / "m.db", root / "e.db"
            with sqlite3.connect(manufacturing) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
                )
                connection.execute(
                    "INSERT INTO process_runs VALUES ('CMP-01','CMP','2026-10-02',NULL,0.2,1)"
                )
            with sqlite3.connect(equipment) as connection:
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
                )
            common = [
                "--adapter",
                "sqlite",
                "--manufacturing-db",
                str(manufacturing),
                "--equipment-db",
                str(equipment),
                "--as-of",
                "2026-10-24",
                "--arguments",
                '{"equipment_id":"CMP-01"}',
            ]
            ready_stream, loop_stream = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(ready_stream):
                self.assertEqual(ready_demo.main(common), 0)
            with contextlib.redirect_stdout(loop_stream):
                self.assertEqual(loop_demo.main(common), 0)
        ready, loop = (
            json.loads(ready_stream.getvalue()),
            json.loads(loop_stream.getvalue()),
        )
        self.assertEqual(loop["model_tool_selection_calls"], 1)
        self.assertEqual(loop["typed_results"][0]["call_id"], "loop-1-1")
        for field in ("status", "row_count", "data", "error"):
            self.assertEqual(
                loop["typed_results"][0][field],
                ready["typed_results"][0][field],
            )
        self.assertEqual(
            loop["observations"][0]["arguments"], ready["observations"][0]["arguments"]
        )
        self.assertEqual(loop["observations"][0]["source_ref"], "TOOL:health")
        self.assertEqual(loop["trace"][0]["sources"], ready["trace"][0]["sources"])

    def test_cross_round_remaining_limit_does_not_reset(self):
        plan = _plan(maximum=3)
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        binding = replace(
            binding,
            context=RuntimeContext(
                Principal(),
                "run",
                ToolExecutionLimits(remaining_calls=1, max_result_rows=1),
            ),
        )

        async def notify(*_args):
            return None

        def response(identifier, value):
            return classify_loop_response(
                {
                    "tool_calls": [
                        {
                            "id": identifier,
                            "function": {
                                "name": "native",
                                "arguments": json.dumps({"value": value}),
                            },
                        }
                    ]
                }
            )

        asyncio.run(
            execute_dispatched_loop_round(
                plan,
                guard,
                "run",
                1,
                response("one", "expected"),
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        outcome = asyncio.run(
            execute_dispatched_loop_round(
                plan,
                guard,
                "run",
                2,
                response("two", "other"),
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(outcome.trace[0]["execution_state"], "not_started")

    def test_empty_result_stops_no_progress_and_wrong_binding_has_no_events(self):
        plan = replace(
            _plan(), budget=replace(_plan().budget, max_no_progress_rounds=1)
        )
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        response = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "one",
                        "function": {
                            "name": "native",
                            "arguments": '{"value":"expected"}',
                        },
                    }
                ]
            }
        )

        async def notify(*_args):
            return None

        asyncio.run(
            execute_dispatched_loop_round(
                plan,
                guard,
                "run",
                1,
                response,
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual(guard.stop_reason, "no_progress")
        events = []
        with self.assertRaisesRegex(RuntimeContractError, "Loop dispatch contract"):
            asyncio.run(
                execute_dispatched_loop_round(
                    plan,
                    guard,
                    "run",
                    2,
                    response,
                    None,
                    binding=replace(
                        binding, context=RuntimeContext(Principal(), "wrong")
                    ),
                    notify=lambda *_args: (_ for _ in ()).throw(AssertionError()),
                    emit_event=lambda *_args, **_kwargs: events.append(True),
                )
            )
        self.assertEqual(events, [])

    def test_deadline_and_cancellation_before_dispatch_have_zero_claims(self):
        plan = _plan()
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        response = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "one",
                        "function": {
                            "name": "native",
                            "arguments": '{"value":"expected"}',
                        },
                    }
                ]
            }
        )

        async def notify(*_args):
            return None

        expired = replace(
            binding,
            context=RuntimeContext(
                Principal(), "run", ToolExecutionLimits(deadline_monotonic=0.0)
            ),
        )
        with patch.object(guard, "check_call", wraps=guard.check_call) as claim:
            outcome = asyncio.run(
                execute_dispatched_loop_round(
                    plan,
                    guard,
                    "run",
                    1,
                    response,
                    None,
                    binding=expired,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(
            (outcome.trace[0]["execution_state"], guard.total_calls, claim.call_count),
            ("not_started", 0, 0),
        )

        class Cancelled:
            def is_cancelled(self):
                return True

        fresh_dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        fresh_guard, fresh_binding = _binding(plan, fresh_dispatcher, projector)
        cancelled = replace(
            fresh_binding,
            context=RuntimeContext(
                Principal(), "run", ToolExecutionLimits(remaining_calls=2), Cancelled()
            ),
        )
        with patch.object(
            fresh_guard, "check_call", wraps=fresh_guard.check_call
        ) as claim:
            outcome = asyncio.run(
                execute_dispatched_loop_round(
                    plan,
                    fresh_guard,
                    "run",
                    1,
                    response,
                    None,
                    binding=cancelled,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(
            (
                outcome.trace[0]["execution_state"],
                fresh_guard.total_calls,
                claim.call_count,
            ),
            ("not_started", 0, 0),
        )

    def test_notify_failure_and_outer_cancel_do_not_repeat_or_advance_late_result(self):
        plan = _plan()
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        response = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "one",
                        "function": {
                            "name": "native",
                            "arguments": '{"value":"expected"}',
                        },
                    }
                ]
            }
        )

        async def failed_notify(_progress, event):
            if event["event"] == "tool_finished":
                raise RuntimeError("observer down")

        with (
            patch.object(dispatcher, "dispatch", wraps=dispatcher.dispatch) as dispatch,
            patch.object(guard, "record_result", wraps=guard.record_result) as record,
            self.assertRaisesRegex(RuntimeError, "observer down"),
        ):
            asyncio.run(
                execute_dispatched_loop_round(
                    plan,
                    guard,
                    "run",
                    1,
                    response,
                    None,
                    binding=binding,
                    notify=failed_notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(
            (guard.total_calls, dispatch.call_count, record.call_count), (1, 1, 1)
        )

        event_dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        event_guard, event_binding = _binding(plan, event_dispatcher, projector)

        def failed_emit(name, *_args, **_kwargs):
            if name == "tool_call_finished":
                raise RuntimeError("audit down")

        with (
            patch.object(
                event_dispatcher, "dispatch", wraps=event_dispatcher.dispatch
            ) as dispatch,
            patch.object(
                event_guard, "record_result", wraps=event_guard.record_result
            ) as record,
            self.assertRaisesRegex(RuntimeError, "audit down"),
        ):
            asyncio.run(
                execute_dispatched_loop_round(
                    plan,
                    event_guard,
                    "run",
                    1,
                    response,
                    None,
                    binding=event_binding,
                    notify=lambda *_args: asyncio.sleep(0),
                    emit_event=failed_emit,
                )
            )
        self.assertEqual(
            (event_guard.total_calls, dispatch.call_count, record.call_count),
            (1, 1, 1),
        )

        entered, release, completed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        registry = ToolRegistry()
        definition = ToolDefinition(
            "native", "v1", "native", Input, lambda value: value
        )

        def block(_input, context):
            entered.set()
            release.wait()
            try:
                return ToolResult(
                    context.call_id,
                    "native",
                    "v1",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    [{"late": True}],
                )
            finally:
                completed.set()

        registry.register_native(ToolBinding(definition, block, object()))
        cancelled_dispatcher = ToolDispatcher(
            run_id="run",
            registry=registry,
            policy=DemoToolPolicy(frozenset({"native"}), tenant_id="demo"),
            budget=LoopGuardToolBudget(ToolLoopGuard(plan)),
            allowed_tools=frozenset({"native"}),
        )
        cancelled_guard, cancelled_binding = _binding(
            plan, cancelled_dispatcher, projector
        )

        async def cancel_round():
            task = asyncio.create_task(
                execute_dispatched_loop_round(
                    plan,
                    cancelled_guard,
                    "run",
                    1,
                    response,
                    None,
                    binding=cancelled_binding,
                    notify=lambda *_args: asyncio.sleep(0),
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
                with patch.object(
                    cancelled_guard,
                    "record_result",
                    wraps=cancelled_guard.record_result,
                ) as record:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertEqual(record.call_count, 1)
            finally:
                release.set()
                await asyncio.wait_for(asyncio.to_thread(completed.wait), timeout=1)

        asyncio.run(cancel_round())
        self.assertEqual(
            (cancelled_guard.total_calls, len(cancelled_guard.evidence_fingerprints)),
            (1, 0),
        )

    def test_actual_loop_injection_reaches_synthesis_and_updates_context(self):
        plan = _plan()
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        requests: list[dict] = []
        emitted: list[dict] = []
        turns = 0

        async def stream(_client, _endpoint, _headers, request, _progress, _state):
            nonlocal turns
            turns += 1
            requests.append(request)
            if turns == 1:
                return (
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "model-call",
                                "function": {
                                    "name": "native",
                                    "arguments": '{"value":"expected"}',
                                },
                            },
                            {
                                "id": "mixed-submit",
                                "function": {
                                    "name": "submit_analysis",
                                    "arguments": "{}",
                                },
                            },
                        ],
                    },
                    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    "model-1",
                )
            return (
                {"role": "assistant", "content": "Loop complete."},
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "model-2",
            )

        class Validation:
            def __init__(self):
                self.coverage = {"required_total": 1, "required_covered": 1}
                self.allowed_conclusion_strength = "supported"

            def to_dict(self):
                return {"coverage": self.coverage}

        context: AgentLoopContext

        def build_result(answer, _report):
            return {
                "answer": answer,
                "tool_trace": context.trace,
                "sources": context.sources,
                "thinking_policy": {},
            }

        async def no_op(*_args):
            return None

        def emit(name, _run_id, **details):
            emitted.append({"event": name, **details})

        context = AgentLoopContext(
            settings=SimpleNamespace(
                api_timeout_seconds=1,
                model_max_retries=0,
                model_retry_base_seconds=0.0,
                model_circuit_failure_threshold=1,
                model_circuit_cooldown_seconds=1,
            ),
            connection=SimpleNamespace(
                base_url="https://offline.invalid",
                api_key="x",
                model="fake",
                provider="fake",
            ),
            intent_route=SimpleNamespace(intent="analysis"),
            execution_plan=plan,
            selected_playbook=object(),
            loop_guard=guard,
            run_id="run",
            progress=None,
            thinking=False,
            main_recovery_trial=False,
            health_enabled=False,
            selected_model_id="fake",
            question="question",
            analysis_question="question",
            playbook_selection=None,
            context_resolution=SimpleNamespace(to_dict=dict),
            messages=[],
            trace=[],
            sources={},
            evidence_observations=[],
            evidence_validation=Validation(),
            answer_contract=SimpleNamespace(status="optional"),
            total_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            knowledge_fallback={"used": False, "disclosure": None},
            fallback_announced=False,
            applied_synthesis_reason=None,
            health={},
            build_result=build_result,
            notify=no_op,
            stream_answer=no_op,
            emit_event=emit,
            stream_completion=stream,
            retryable_model_error=lambda _error: False,
            model_error_category=lambda _error: "",
            model_failure_reason=lambda _error: "",
            model_retry_delay=lambda *_args: 0.0,
            record_model_success=lambda _model: ({}, None),
            record_model_failure=lambda *_args, **_kwargs: ({}, None),
            audit_assistant=lambda value: value,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "query_manufacturing_data",
                        "description": "global SQL sentinel must stay hidden",
                        "parameters": {
                            "type": "object",
                            "properties": {"sql": {"type": "string"}},
                        },
                    },
                }
            ],
            submit_analysis_tool={"name": "submit_analysis"},
            parse_tool_arguments=lambda *_args: ({}, None),
            execute_tool=lambda *_args: (_ for _ in ()).throw(
                AssertionError("legacy executor must not run")
            ),
            usable_knowledge_result=lambda *_args: False,
            normalize_general_knowledge_answer=lambda answer: answer,
            has_knowledge_fallback_disclosure=lambda *_args: False,
            knowledge_fallback_state=lambda *_args: {"used": False, "disclosure": None},
            validate_evidence=lambda *_args: Validation(),
            create_answer_contract=lambda *_args, **_kwargs: SimpleNamespace(
                status="optional"
            ),
            validator_system_message=lambda *_args: "validator-message",
            synthesizer_system_message=lambda *_args: "synthesizer-message",
            synthesize_legacy_answer=lambda answer, *_args, **_kwargs: SimpleNamespace(
                answer=answer, report={}
            ),
            synthesize_submission=lambda *_args, **_kwargs: None,
            emit_answer_synthesis=lambda *_args: None,
            emit_evidence_validation=lambda *_args: None,
            offline_answer=lambda *_args, **_kwargs: {},
            evidence_observation_type=__import__(
                "app.evidence.validator", fromlist=["EvidenceObservation"]
            ).EvidenceObservation,
            provider_request_options=lambda *_args: {},
            request_synthesis_correction=None,
            dispatch_binding=binding,
        )
        result = asyncio.run(run_agent_loop(context))
        self.assertEqual(result["answer"], "Loop complete.")
        self.assertEqual(result["tool_trace"][0]["call_id"], "loop-1-1")
        self.assertEqual(context.evidence_observations[0].source_ref, "TOOL:S01")
        self.assertEqual((guard.total_calls, len(guard.evidence_fingerprints)), (1, 1))
        self.assertEqual(requests[0]["tools"][0]["function"]["name"], "native")
        self.assertEqual(requests[0]["tools"][1], {"name": "submit_analysis"})
        for request in requests:
            self.assertEqual(
                [tool.get("function", tool).get("name") for tool in request["tools"]],
                ["native", "submit_analysis"],
            )
        self.assertTrue(guard.force_synthesis)
        self.assertEqual(requests[1]["tool_choice"], "none")
        self.assertNotIn(
            "sql",
            json.dumps(requests[1]["tools"], ensure_ascii=False).lower(),
        )
        self.assertIn(
            "submit_analysis 必须单独调用",
            next(
                item["content"]
                for item in context.messages
                if item.get("tool_call_id") == "mixed-submit"
            ),
        )
        self.assertIn(
            "validator-message", [item["content"] for item in context.messages]
        )
        self.assertIn(
            "synthesizer-message", [item["content"] for item in context.messages]
        )
        self.assertEqual(
            [item["event"] for item in emitted].count("tool_call_started"), 1
        )
        self.assertIn("loop_guard_round_finished", [item["event"] for item in emitted])

        submit_plan = _plan()
        submit_projector = ReadyResultPolicy()
        submit_dispatcher = _dispatcher(submit_plan, [{"row": 1}], submit_projector)
        submit_guard, submit_binding = _binding(
            submit_plan, submit_dispatcher, submit_projector
        )
        submit_requests: list[dict] = []

        async def submit_stream(
            _client, _endpoint, _headers, request, _progress, _state
        ):
            submit_requests.append(request)
            return (
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "submit-only",
                            "function": {
                                "name": "submit_analysis",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "submit-model",
            )

        submit_context = replace(
            context,
            execution_plan=submit_plan,
            loop_guard=submit_guard,
            messages=[],
            trace=[],
            sources={},
            evidence_observations=[],
            evidence_validation=Validation(),
            answer_contract=SimpleNamespace(status="optional"),
            total_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            knowledge_fallback={"used": False, "disclosure": None},
            health={},
            stream_completion=submit_stream,
            synthesize_submission=lambda *_args, **_kwargs: SimpleNamespace(
                answer="Submitted.", report={}
            ),
            build_result=lambda answer, _report: {
                "answer": answer,
                "tool_trace": submit_context.trace,
                "sources": submit_context.sources,
                "thinking_policy": {},
            },
            dispatch_binding=submit_binding,
        )
        with patch.object(
            submit_dispatcher, "dispatch", wraps=submit_dispatcher.dispatch
        ) as dispatch:
            submit_result = asyncio.run(run_agent_loop(submit_context))
        self.assertEqual(submit_result["answer"], "Submitted.")
        self.assertEqual((submit_guard.total_calls, dispatch.call_count), (0, 0))
        self.assertEqual(
            [
                tool.get("function", tool).get("name")
                for tool in submit_requests[0]["tools"]
            ],
            ["native", "submit_analysis"],
        )

    def test_injected_model_failure_never_enters_legacy_offline_fallback(self):
        plan = _plan()
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        offline_calls: list[object] = []

        async def notify(*_args):
            return None

        async def unavailable_stream(*_args):
            raise ConnectionError("model unavailable")

        def offline_sentinel(*_args, **_kwargs):
            offline_calls.append(True)
            raise AssertionError("injected loop must not run legacy offline fallback")

        values = {field.name: None for field in fields(AgentLoopContext)}
        values.update(
            settings=SimpleNamespace(
                api_timeout_seconds=1,
                model_max_retries=0,
                model_retry_base_seconds=0.0,
                model_circuit_failure_threshold=1,
                model_circuit_cooldown_seconds=1,
            ),
            connection=SimpleNamespace(
                base_url="https://offline.invalid",
                api_key="x",
                model="fake",
                provider="fake",
            ),
            intent_route=SimpleNamespace(intent="analysis"),
            execution_plan=plan,
            selected_playbook=object(),
            loop_guard=guard,
            run_id="run",
            progress=None,
            thinking=False,
            main_recovery_trial=False,
            health_enabled=False,
            selected_model_id="fake",
            question="question",
            analysis_question="question",
            messages=[],
            trace=[],
            sources={},
            evidence_observations=[],
            evidence_validation=SimpleNamespace(),
            answer_contract=SimpleNamespace(status="optional"),
            total_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            knowledge_fallback={"used": False, "disclosure": None},
            health={},
            notify=notify,
            emit_event=lambda *_args, **_kwargs: None,
            stream_completion=unavailable_stream,
            retryable_model_error=lambda _error: True,
            model_failure_reason=lambda _error: "unavailable",
            provider_request_options=lambda *_args: {},
            execute_tool=lambda *_args: (_ for _ in ()).throw(
                AssertionError("legacy executor must not run")
            ),
            offline_answer=offline_sentinel,
            dispatch_binding=binding,
        )
        context = AgentLoopContext(**values)
        with (
            patch.object(dispatcher, "dispatch", wraps=dispatcher.dispatch) as dispatch,
            self.assertRaisesRegex(ConnectionError, "model unavailable"),
        ):
            asyncio.run(run_agent_loop(context))
        self.assertEqual(
            (offline_calls, dispatch.call_count, guard.total_calls), ([], 0, 0)
        )

    def test_round_uses_server_call_identity_scope_and_single_guard_accounting(self):
        plan = _plan()
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}, {"row": 2}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        events: list[dict] = []

        async def notify(_progress, event):
            events.append(event)

        response = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "untrusted-model-id",
                        "function": {
                            "name": "native",
                            "arguments": '{"value":"expected"}',
                        },
                    }
                ]
            }
        )
        with (
            patch.object(guard, "begin_round", wraps=guard.begin_round) as begin,
            patch.object(guard, "finish_round", wraps=guard.finish_round) as finish,
            patch.object(guard, "check_call", wraps=guard.check_call) as check,
            patch.object(guard, "record_result", wraps=guard.record_result) as record,
        ):
            outcome = asyncio.run(
                execute_dispatched_loop_round(
                    plan,
                    guard,
                    "run",
                    2,
                    response,
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            )
        self.assertEqual(
            (begin.call_count, finish.call_count, check.call_count, record.call_count),
            (1, 1, 1, 1),
        )
        self.assertEqual(outcome.tool_results[0].call_id, "loop-2-1")
        self.assertEqual(outcome.trace[0]["arguments"], {"value": "expected"})
        self.assertEqual(outcome.observation_payloads[0]["source_ref"], "TOOL:S01")
        self.assertEqual(
            outcome.observation_payloads[0]["arguments"], {"value": "expected"}
        )
        self.assertEqual(outcome.tool_results[0].data, [{"row": 1}])
        self.assertEqual(
            [item["event"] for item in events], ["tool_started", "tool_finished"]
        )
        self.assertEqual(json.loads(outcome.tool_messages[0]["content"])["ok"], True)

    def test_nonmatching_plan_parameters_do_not_gain_step_reference(self):
        plan = _plan(parameters={"value": "expected"})
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [{"row": 1}], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        response = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "model",
                        "function": {
                            "name": "native",
                            "arguments": '{"value":"other"}',
                        },
                    }
                ]
            }
        )
        outcome = asyncio.run(
            execute_dispatched_loop_round(
                plan,
                guard,
                "run",
                1,
                response,
                None,
                binding=binding,
                notify=lambda *_args: asyncio.sleep(0),
                emit_event=lambda *_args, **_kwargs: None,
            )
        )
        self.assertEqual(outcome.observation_payloads[0]["source_ref"], "TOOL:loop-1-1")

    def test_dispatcher_denial_never_leaks_sql_or_claims(self):
        plan = _plan()
        projector = ReadyResultPolicy()
        dispatcher = _dispatcher(plan, [], projector)
        guard, binding = _binding(plan, dispatcher, projector)
        response = classify_loop_response(
            {
                "tool_calls": [
                    {
                        "id": "model",
                        "function": {
                            "name": "sql",
                            "arguments": '{"sql":"SELECT secret_marker"}',
                        },
                    }
                ]
            }
        )
        events: list[dict] = []

        async def notify(_progress, event):
            events.append(event)

        outcome = asyncio.run(
            execute_dispatched_loop_round(
                plan,
                guard,
                "run",
                1,
                response,
                None,
                binding=binding,
                notify=notify,
                emit_event=lambda name, _run, **details: events.append(
                    {"event": name, **details}
                ),
            )
        )
        rendered = repr(
            (outcome.trace, outcome.observation_payloads, events, outcome.tool_messages)
        )
        self.assertEqual(guard.total_calls, 0)
        self.assertEqual(outcome.trace[0]["execution_state"], "not_started")
        self.assertNotIn("secret_marker", rendered)


if __name__ == "__main__":
    unittest.main()
