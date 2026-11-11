"""MOD-015 closeout acceptance for the converged runtime paths.

Three entry paths are exercised end to end with deterministic in-memory fakes:
the typed ``AgentApplication`` without a Skill, the typed application with the
opt-in lithography Skill (file-backed roots and a release store), and the
public legacy ``service.run_agent`` facade.  Each path runs cleanly, then
through cancellation, a model failure and a tool or Skill failure.  After
every failure the process-wide runtime state must be unchanged and a follow-up
run must equal the clean first run, ignoring wall-clock and run identifiers.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import dataclasses
import gc
import json
import shutil
import tempfile
import time
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime import service
from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.loop_response import classify_loop_response
from app.agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from app.agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
)
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionLimits
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import AssemblyError, assemble_agent
from app.bootstrap.litho_cpk_demo import _QUESTION, _TOOLS, _bindings, _Principal
from app.bootstrap.litho_cpk_workflow import LithoCpkWorkflow
from app.bootstrap.loop_assembly import bind_loop_run
from app.bootstrap.ready_assembly import bind_ready_run
from app.bootstrap.skill_assembly import (
    SkillAssemblyConfiguration,
    SkillExecutionRequest,
    _inventory,
)
from app.conversation import decision_arbiter
from app.core.identity import (
    Principal,
    current_principal,
    reset_principal,
    set_principal,
)
from app.core.storage_identity_ports import configured_storage_identity
from app.evidence import validator as evidence_validator
from app.evidence.validator import EvidenceObservation
from app.tools.named_queries.data_source import SQLiteNamedQueryAdapter
from app.intent_runtime.routing import route_question
from app.knowledge.decision import usable_result
from app.tools.operational_reports.binding import create_defect_pareto_binding
from app.memory_system.contracts import ContextResolution
from app.skills.catalog import SkillReference
from app.skills.frontmatter import parse_skill_document
from app.skills.releases import SkillReleaseStore
from app.telemetry import runtime_status
from tests import test_default_native_runtime as native_tests
from tests.test_model_gateway_port import ScriptedGateway

ROOT = Path(__file__).resolve().parents[1]
_AS_OF = date(2026, 10, 31)
_EXTRA_TOOL = "get_defect_pareto"
_ALL_TOOLS = (*_TOOLS, _EXTRA_TOOL)
_SKILL = SkillReference("litho-cpk-diagnostic", "2.0.0")
_SKILL_SOURCE = ROOT / "app" / "skills" / "litho-cpk-diagnostic"
_SKILL_MODES = ("off", "file", "release")
_VOLATILE = frozenset({"run_id", "started_at", "completed_at", "traceback"})
_HANG = "hang"

# A generic data-interface question keeps the legacy loop path: manufacturing
# playbooks (for example PB-DEFECT-001) now build deterministic ready plans.
_LOOP_QUESTION = "数据接口有哪些"
_READY_QUESTION = "查询 LOT-001 的批次信息"
_CONTEXT_QUESTION = "继续"
_CONTEXT_HISTORY = (
    {"role": "user", "content": _READY_QUESTION},
    {
        "role": "assistant",
        "content": "已查询",
        "metadata": {"turn_decision": {"active_flow": "task:lot_trace"}},
    },
)
_TOOL_CALL = (
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {
                    "name": "get_lot_identity",
                    "arguments": '{"lot_id":"LOT-001"}',
                },
            }
        ],
    },
    {"total_tokens": 1},
    "r1",
)
_ANSWER = (
    {"role": "assistant", "content": "已完成批次核验。"},
    {"total_tokens": 2},
    "r2",
)
_CONTEXT_REPLY = (
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "relation": "followup",
                "resolved_question": _READY_QUESTION,
                "topic_anchor": "LOT-001",
                "target_message_ids": [],
                "confidence": 0.95,
                "intent_hint": "manufacturing_analysis",
            },
            ensure_ascii=False,
        ),
    },
    {"total_tokens": 3},
    "ctx",
)
_LEGACY_PATHS = {
    "loop": (_LOOP_QUESTION, None, (_TOOL_CALL, _ANSWER)),
    "ready": (_READY_QUESTION, None, (_ANSWER,)),
    "context": (_CONTEXT_QUESTION, _CONTEXT_HISTORY, (_CONTEXT_REPLY, _ANSWER)),
}


def _stable(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _stable(item)
            for key, item in value.items()
            if key not in _VOLATILE and not str(key).endswith("_ms")
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _plain(value: object) -> object:
    """JSON-normalize and drop wall-clock and per-run identifiers."""
    return _stable(json.loads(json.dumps(value, ensure_ascii=False, default=str)))


def _process_state() -> dict[str, object]:
    handlers = service.TOOL_HANDLERS
    return {
        "tools": (
            id(service.TOOLS),
            json.dumps(service.TOOLS, ensure_ascii=False, sort_keys=True, default=str),
        ),
        "handlers": (
            id(handlers),
            tuple((name, id(handler)) for name, handler in sorted(handlers.items())),
        ),
        "storage_identity": id(configured_storage_identity()),
        # Only the HTTP chat services register runtime-status entries.
        "runtime_status": copy.deepcopy(runtime_status._users),
    }


def _pending_tasks() -> set[asyncio.Task[object]]:
    current = asyncio.current_task()
    return {task for task in asyncio.all_tasks() if task is not current}


class _TypedModel:
    """Scripted ModelResponsePort that records requests and live calls."""

    def __init__(self, plan_for_run: object) -> None:
        self._plan_for_run = plan_for_run
        self.script: list[object] = []
        self.requests: list[ModelRequest] = []
        self.active = 0
        self.entered: asyncio.Event | None = None

    async def complete(
        self, request: ModelRequest, _context: RuntimeContext
    ) -> ModelResponse:
        self.requests.append(request)
        self.active += 1
        try:
            step = self.script.pop(0)
            if isinstance(step, BaseException):
                raise step
            if step == _HANG:
                if self.entered is not None:
                    self.entered.set()
                await asyncio.Event().wait()
            if step == "tools":
                return ModelResponse(
                    tool_calls=tuple(
                        ModelToolCall(
                            str(index), item.tool, json.dumps(item.parameters)
                        )
                        for index, item in enumerate(self._plan_for_run().steps, 1)
                    )
                )
            return ModelResponse(content="typed acceptance complete")
        finally:
            self.active -= 1


class _EventSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _TypedFixture:
    app: object
    workflow: LithoCpkWorkflow
    selection: object
    model: _TypedModel
    sink: _EventSink
    adapters: tuple[object, ...]
    guards: list[ToolLoopGuard]
    store: SkillReleaseStore | None
    package_root: Path | None


class TypedApplicationAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _fixture(self, skill: str, mode: str = "loop") -> _TypedFixture:
        workflow = LithoCpkWorkflow()
        route = route_question(_QUESTION, _AS_OF)
        plan, selection = workflow.build(_QUESTION, route)
        native, adapters = _bindings(plan, _AS_OF, _Principal())
        # The unused extra binding makes Skill capability narrowing observable.
        bindings = (
            *native,
            create_defect_pareto_binding(adapters[1], today=lambda: _AS_OF),
        )
        store = None
        package_root = None
        configuration = None
        if skill == "file":
            package_root = self.root / f"file-{id(workflow)}" / _SKILL.skill_id
            shutil.copytree(_SKILL_SOURCE, package_root)
            configuration = SkillAssemblyConfiguration(
                (str(package_root),), (workflow,)
            )
        elif skill == "release":
            package_root = self.root / f"release-{id(workflow)}" / _SKILL.skill_id
            shutil.copytree(_SKILL_SOURCE, package_root)
            store = SkillReleaseStore()
            store.publish(package_root, _inventory(bindings, (workflow,)))
            store.activate(_SKILL)
            configuration = SkillAssemblyConfiguration((), (workflow,), store)
        definition = AgentDefinition(
            "mod015-acceptance",
            "1.0.0",
            "analyst",
            "Answer only from the fixed acceptance evidence.",
            tuple(ComponentReference(name, "1.0.0") for name in _ALL_TOOLS),
            ComponentReference("acceptance-model", "1.0.0"),
            ComponentReference("acceptance-policy", "1.0.0"),
            (
                (ComponentReference(_SKILL.skill_id, _SKILL.version),)
                if configuration is not None
                else ()
            ),
        )
        holder: dict[str, object] = {}
        guards: list[ToolLoopGuard] = []

        def plan_for_run() -> object:
            binding = holder["app"].skill_binding
            return plan if binding is None else binding.plan

        def budget_factory() -> LoopGuardToolBudget:
            guard = ToolLoopGuard(plan_for_run())
            guards.append(guard)
            return LoopGuardToolBudget(guard)

        model = _TypedModel(plan_for_run)
        sink = _EventSink()
        app = assemble_agent(
            definition,
            model=model,
            events=sink,
            bindings=bindings,
            policy=DemoToolPolicy(
                frozenset(_ALL_TOOLS), frozenset({"analyst"}), tenant_id="demo"
            ),
            budget_factory=budget_factory,
            server_capabilities=frozenset(_ALL_TOOLS),
            model_policy_ref=definition.model_policy,
            policy_ref=definition.default_policy,
            skill_configuration=configuration,
            skill_request=(
                SkillExecutionRequest(_QUESTION, route, mode)
                if configuration is not None
                else None
            ),
        )
        holder["app"] = app
        if app.skill_binding is not None:
            selection = app.skill_binding.selection
        return _TypedFixture(
            app, workflow, selection, model, sink, adapters, guards, store, package_root
        )

    async def _run(
        self,
        fx: _TypedFixture,
        mode: str,
        run_id: str,
        *,
        notify: object = None,
        capture: dict[str, object] | None = None,
    ) -> dict[str, object]:
        projector = ReadyResultPolicy(frozenset({"search_knowledge"}), usable_result)
        context = RuntimeContext(
            _Principal(), run_id, ToolExecutionLimits(20, 100, time.monotonic() + 30)
        )
        run = fx.app.new_run(context, result_policy=projector)
        guard = fx.guards[-1]
        plan = guard.plan
        dispatch_events: list[str] = []

        def emit_event(name: str, _run_id: str, **_fields: object) -> None:
            dispatch_events.append(name)

        async def quiet(_progress: object, _event: dict[str, object]) -> None:
            return None

        record: dict[str, object] = {
            "run": run,
            "guard": guard,
            "projector": projector,
            "dispatch_events": dispatch_events,
            "first_request": len(fx.model.requests),
        }
        if capture is not None:
            capture["record"] = record
        if mode == "ready":
            outcome = await execute_dispatched_ready_plan(
                plan,
                guard,
                run_id,
                None,
                binding=bind_ready_run(plan, guard, run, projector),
                notify=notify or quiet,
                emit_event=emit_event,
            )
        else:
            first = await run.model_stage(
                call_id=f"{run_id}-model-1",
                messages=(ModelMessage("user", _QUESTION),),
            )
            await run.publish(first.event)
            outcome = await execute_dispatched_loop_round(
                plan,
                guard,
                run_id,
                1,
                classify_loop_response(first.value),
                None,
                binding=bind_loop_run(plan, guard, run, projector),
                notify=notify or quiet,
                emit_event=emit_event,
            )
            second = await run.model_stage(
                call_id=f"{run_id}-model-2",
                messages=(
                    ModelMessage("user", _QUESTION),
                    ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                    *(
                        ModelMessage(
                            "tool", item["content"], tool_call_id=item["tool_call_id"]
                        )
                        for item in outcome.tool_messages
                    ),
                ),
            )
            await run.publish(second.event)
        record["outcome"] = outcome
        record["last_request"] = len(fx.model.requests)
        record["validation"] = fx.workflow.evidence_validator(
            plan,
            fx.selection.selected_playbook,
            [EvidenceObservation(**item) for item in outcome.observation_payloads],
        )
        return record

    def _execute(self, fx: _TypedFixture, mode: str, run_id: str) -> dict[str, object]:
        if mode == "loop":
            fx.model.script = ["tools", "answer"]

        async def drive() -> dict[str, object]:
            record = await self._run(fx, mode, run_id)
            self.assertEqual(_pending_tasks(), set())
            return record

        return asyncio.run(drive())

    @staticmethod
    def _summary(fx: _TypedFixture, record: dict[str, object]) -> object:
        run = record["run"]
        outcome = record["outcome"]
        return _plain(
            {
                "trace": outcome.trace,
                "observations": outcome.observation_payloads,
                "sources": outcome.sources,
                "guard": record["guard"].summary(),
                "dispatch_events": record["dispatch_events"],
                "runtime_events": [
                    (event.kind, str(event.status), event.tool_name)
                    for event in fx.sink.events
                    if event.run_id == run.context.run_id
                ],
                "coverage": record["validation"].coverage,
                "metadata": dict(run.skill_metadata),
                "tools_json": run.tools_json,
                "model_requests": [
                    [(message.role, message.content) for message in request.messages]
                    for request in fx.model.requests[
                        record["first_request"] : record["last_request"]
                    ]
                ],
            }
        )

    def _skill_state(self, fx: _TypedFixture) -> object:
        binding = fx.app.skill_binding
        if binding is None:
            return None
        return (
            binding.snapshot,
            binding.plan,
            fx.store.states() if fx.store is not None else None,
        )

    def _assert_unchanged(
        self,
        fx: _TypedFixture,
        process: dict[str, object],
        skill_state: object,
    ) -> None:
        self.assertEqual(_process_state(), process)
        self.assertEqual(fx.model.active, 0)
        current = self._skill_state(fx)
        if skill_state is not None:
            self.assertIs(current[0], skill_state[0])
            self.assertIs(current[1], skill_state[1])
            self.assertEqual(current[2], skill_state[2])

    def test_success_matrix_uses_fresh_budget_and_dispatcher_per_run(self) -> None:
        for skill in _SKILL_MODES:
            for mode in ("ready", "loop"):
                with self.subTest(skill=skill, mode=mode):
                    fx = self._fixture(skill, mode)
                    process = _process_state()
                    skill_state = self._skill_state(fx)
                    first = self._execute(fx, mode, f"{skill}-{mode}-1")
                    second = self._execute(fx, mode, f"{skill}-{mode}-2")
                    plan = first["guard"].plan
                    outcome = first["outcome"]
                    run = first["run"]

                    self.assertEqual(len(outcome.trace), len(plan.steps))
                    self.assertTrue(
                        all(item["status"] == "ok" for item in outcome.trace)
                    )
                    self.assertEqual(
                        first["validation"].coverage["required_covered"], 3
                    )
                    self.assertIn("KB-LITHO-001", outcome.sources)
                    self.assertEqual(
                        {item["tool"] for item in outcome.observation_payloads},
                        set(_TOOLS),
                    )
                    self.assertEqual(len(fx.guards), 2)
                    self.assertIsNot(first["guard"], second["guard"])
                    self.assertIsNot(run.dispatcher, second["run"].dispatcher)
                    self.assertIs(run.dispatcher.budget.guard, first["guard"])
                    self.assertEqual(first["guard"].total_calls, len(plan.steps))
                    self.assertEqual(second["guard"].total_calls, len(plan.steps))
                    self.assertEqual(first["guard"].summary()["blocked_calls"], 0)
                    self.assertEqual(fx.adapters[0].calls[:2], fx.adapters[0].calls[2:])
                    self.assertEqual(len(fx.adapters[1].calls), 2)
                    self.assertEqual(len(fx.adapters[2].calls), 2)

                    expected_tools = set(_TOOLS) if skill != "off" else set(_ALL_TOOLS)
                    self.assertEqual(
                        fx.app.effective_capabilities, frozenset(expected_tools)
                    )
                    self.assertEqual(
                        run.dispatcher.allowed_tools, frozenset(expected_tools)
                    )
                    self.assertEqual(
                        {
                            item["function"]["name"]
                            for item in json.loads(run.tools_json)
                        },
                        expected_tools,
                    )
                    if mode == "ready":
                        self.assertEqual(fx.model.requests, [])
                        self.assertEqual(
                            first["dispatch_events"][0], "ready_plan_execution_started"
                        )
                        self.assertEqual(
                            first["dispatch_events"][-1],
                            "ready_plan_execution_finished",
                        )
                        self.assertEqual(fx.sink.events, [])
                    else:
                        self.assertEqual(len(fx.model.requests), 4)
                        self.assertEqual(
                            [(event.kind, event.run_id) for event in fx.sink.events],
                            [
                                ("model_response", run.context.run_id),
                                ("model_response", run.context.run_id),
                                ("model_response", second["run"].context.run_id),
                                ("model_response", second["run"].context.run_id),
                            ],
                        )
                        self.assertEqual(
                            first["dispatch_events"].count("tool_call_finished"),
                            len(plan.steps),
                        )
                    if skill == "off":
                        self.assertIsNone(fx.app.skill_binding)
                        self.assertEqual(run.skill_context, ())
                        self.assertEqual(run.skill_metadata, ())
                    else:
                        binding = fx.app.skill_binding
                        self.assertEqual(binding.snapshot.reference, _SKILL)
                        self.assertEqual(run.skill_context, binding.model_context)
                        self.assertEqual(
                            run.skill_context[0].content,
                            parse_skill_document(
                                (fx.package_root / "SKILL.md").read_text(
                                    encoding="utf-8"
                                )
                            ).body,
                        )
                        metadata = dict(run.skill_metadata)
                        self.assertEqual(metadata["skill_id"], _SKILL.skill_id)
                        self.assertEqual(metadata["skill_version"], _SKILL.version)
                        self.assertEqual(
                            metadata["workflow_id"], fx.workflow.workflow_id
                        )
                        if mode == "loop":
                            request = fx.model.requests[0]
                            self.assertEqual(
                                request.messages[1 : 1 + len(run.skill_context)],
                                run.skill_context,
                            )
                    if skill == "release":
                        self.assertEqual(
                            [
                                (state.enabled, state.active)
                                for state in fx.store.states()
                            ],
                            [(True, True)],
                        )
                    self.assertEqual(
                        self._summary(fx, first), self._summary(fx, second)
                    )
                    self._assert_unchanged(fx, process, skill_state)

    def test_cancel_mid_model_call_and_mid_ready_plan_leaves_no_residue(self) -> None:
        for skill in _SKILL_MODES:
            for mode in ("ready", "loop"):
                with self.subTest(skill=skill, mode=mode):
                    fx = self._fixture(skill, mode)
                    process = _process_state()
                    skill_state = self._skill_state(fx)
                    clean = self._execute(fx, mode, f"{skill}-{mode}-clean")
                    source_calls = [len(adapter.calls) for adapter in fx.adapters]
                    captured: dict[str, object] = {}
                    cleared: list[ReadyResultPolicy] = []
                    original_clear = ReadyResultPolicy.clear

                    def tracking_clear(policy: ReadyResultPolicy) -> None:
                        cleared.append(policy)
                        original_clear(policy)

                    async def drive() -> None:
                        entered = asyncio.Event()

                        async def hang_after_first_tool(
                            _progress: object, event: dict[str, object]
                        ) -> None:
                            if event.get("event") != "tool_started":
                                entered.set()
                                await asyncio.Event().wait()

                        if mode == "loop":
                            fx.model.script = [_HANG]
                            fx.model.entered = entered
                        captured["guards"] = len(fx.guards)
                        task = asyncio.create_task(
                            self._run(
                                fx,
                                mode,
                                f"{skill}-{mode}-cancel",
                                notify=hang_after_first_tool
                                if mode == "ready"
                                else None,
                                capture=captured,
                            )
                        )
                        await asyncio.wait_for(entered.wait(), 5)
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        self.assertEqual(_pending_tasks(), set())
                        fx.model.entered = None

                    with patch.object(ReadyResultPolicy, "clear", tracking_clear):
                        asyncio.run(drive())
                    guard = fx.guards[-1]
                    projector = captured["record"]["projector"]
                    self.assertEqual(len(fx.guards), captured["guards"] + 1)
                    if mode == "loop":
                        self.assertEqual(guard.total_calls, 0)
                        self.assertEqual(
                            [len(adapter.calls) for adapter in fx.adapters],
                            source_calls,
                        )
                        self.assertEqual(cleared, [])
                    else:
                        self.assertEqual(guard.total_calls, 1)
                        # The dispatch finalizer still runs for a cancelled
                        # Ready round and clears that run's projector.
                        self.assertEqual(
                            [item for item in cleared if item is projector], [projector]
                        )
                        self.assertEqual(projector._raw_rows, {})
                    follow_up = self._execute(fx, mode, f"{skill}-{mode}-after-cancel")
                    self.assertEqual(
                        self._summary(fx, follow_up), self._summary(fx, clean)
                    )
                    self._assert_unchanged(fx, process, skill_state)

    def test_model_failure_propagates_without_dispatching_tools(self) -> None:
        for skill in _SKILL_MODES:
            with self.subTest(skill=skill, mode="loop"):
                fx = self._fixture(skill, "loop")
                process = _process_state()
                skill_state = self._skill_state(fx)
                clean = self._execute(fx, "loop", f"{skill}-loop-clean")
                source_calls = [len(adapter.calls) for adapter in fx.adapters]
                fx.model.script = [RuntimeError("model down")]
                events = len(fx.sink.events)
                with self.assertRaisesRegex(RuntimeError, "model down"):
                    asyncio.run(self._run(fx, "loop", f"{skill}-loop-model-error"))
                self.assertEqual(fx.guards[-1].total_calls, 0)
                self.assertEqual(len(fx.sink.events), events)
                self.assertEqual(
                    [len(adapter.calls) for adapter in fx.adapters], source_calls
                )
                follow_up = self._execute(fx, "loop", f"{skill}-loop-after-model-error")
                self.assertEqual(self._summary(fx, follow_up), self._summary(fx, clean))
                self._assert_unchanged(fx, process, skill_state)
            with self.subTest(skill=skill, mode="ready"):
                fx = self._fixture(skill, "ready")
                process = _process_state()
                fx.model.script = [RuntimeError("model down")]
                record = self._execute(fx, "ready", f"{skill}-ready-model-unused")
                self.assertEqual(fx.model.requests, [])
                self.assertEqual(len(fx.model.script), 1)
                self.assertTrue(
                    all(item["status"] == "ok" for item in record["outcome"].trace)
                )
                self._assert_unchanged(fx, process, None)

    def test_tool_failure_is_a_typed_result_and_does_not_poison_next_run(self) -> None:
        for skill in _SKILL_MODES:
            for mode in ("ready", "loop"):
                with self.subTest(skill=skill, mode=mode):
                    fx = self._fixture(skill, mode)
                    process = _process_state()
                    skill_state = self._skill_state(fx)
                    clean = self._execute(fx, mode, f"{skill}-{mode}-clean")
                    with patch.object(
                        fx.adapters[0],
                        "fetch",
                        side_effect=RuntimeError("adapter exploded"),
                    ):
                        failed = self._execute(fx, mode, f"{skill}-{mode}-tool-error")
                    statuses = {
                        item["tool"]: item["status"] for item in failed["outcome"].trace
                    }
                    expected = (
                        # Ready blocks every step that depends on the failed one.
                        {
                            "get_process_capability": "error",
                            "get_recent_excursions": "blocked",
                            "get_sensor_summary": "blocked",
                            "search_knowledge": "blocked",
                            "get_capability_trend": "blocked",
                        }
                        if mode == "ready"
                        else {
                            "get_process_capability": "error",
                            "get_recent_excursions": "ok",
                            "get_sensor_summary": "error",
                            "search_knowledge": "ok",
                            "get_capability_trend": "ok",
                        }
                    )
                    self.assertEqual(statuses, expected)
                    self.assertNotIn(
                        "adapter exploded",
                        json.dumps(
                            failed["outcome"].trace, ensure_ascii=False, default=str
                        ),
                    )
                    self.assertLess(
                        failed["validation"].coverage["required_covered"], 3
                    )
                    follow_up = self._execute(
                        fx, mode, f"{skill}-{mode}-after-tool-error"
                    )
                    self.assertEqual(
                        self._summary(fx, follow_up), self._summary(fx, clean)
                    )
                    self._assert_unchanged(fx, process, skill_state)

    def test_skill_revalidation_failure_blocks_new_run_before_budget(self) -> None:
        for skill in ("file", "release"):
            for mode in ("ready", "loop"):
                with self.subTest(skill=skill, mode=mode):
                    fx = self._fixture(skill, mode)
                    process = _process_state()
                    skill_state = self._skill_state(fx)
                    clean = self._execute(fx, mode, f"{skill}-{mode}-clean")
                    guards = len(fx.guards)
                    requests = len(fx.model.requests)
                    source_calls = [len(adapter.calls) for adapter in fx.adapters]
                    manifest_path = fx.package_root / "manifest.json"
                    original_manifest = manifest_path.read_bytes()
                    if skill == "release":
                        fx.store.disable(_SKILL)
                    else:
                        manifest = json.loads(original_manifest.decode("utf-8"))
                        manifest["description"] = "changed after assembly"
                        manifest_path.write_text(
                            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
                        )
                    with self.assertRaises(AssemblyError):
                        asyncio.run(self._run(fx, mode, f"{skill}-{mode}-revoked"))
                    self.assertEqual(len(fx.guards), guards)
                    self.assertEqual(len(fx.model.requests), requests)
                    self.assertEqual(
                        [len(adapter.calls) for adapter in fx.adapters], source_calls
                    )
                    if skill == "release":
                        self.assertEqual(
                            [
                                (state.enabled, state.active)
                                for state in fx.store.states()
                            ],
                            [(False, False)],
                        )
                        fx.store.enable(_SKILL)
                        fx.store.activate(_SKILL)
                    else:
                        manifest_path.write_bytes(original_manifest)
                    follow_up = self._execute(fx, mode, f"{skill}-{mode}-restored")
                    self.assertEqual(
                        self._summary(fx, follow_up), self._summary(fx, clean)
                    )
                    self._assert_unchanged(fx, process, skill_state)


class LegacyRunAgentAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.native = native_tests.DefaultNativeRuntimeTests(
            "test_default_prompt_omits_legacy_catalog_but_preserves_rules"
        )
        self.native.setUp()
        self.addCleanup(self._cleanup_fixture)
        self.settings = self.native._settings(api_key="fixture-key")

    def _cleanup_fixture(self) -> None:
        # Unreachable sqlite connection cycles must be collected before the
        # fixture deletes its database files on Windows.
        gc.collect()
        self.native.tearDown()

    def _legacy(
        self,
        path: str,
        script: tuple[object, ...] | None = None,
        *,
        cancel: bool = False,
    ) -> dict[str, object]:
        question, history, default_script = _LEGACY_PATHS[path]
        steps = list(default_script if script is None else script)
        events: list[tuple[str, dict[str, object]]] = []
        record: dict[str, object] = {"events": events, "result": None, "error": None}

        def emit(name: str, _run_id: str, **fields: object) -> None:
            events.append((name, fields))

        async def drive() -> None:
            entered = asyncio.Event()

            async def hang(
                _payload: object, _progress: object, _state: object
            ) -> object:
                entered.set()
                await asyncio.Event().wait()

            gateway = ScriptedGateway(
                [hang if step == _HANG else step for step in steps]
            )
            record["gateway"] = gateway
            principal = current_principal()
            with patch(
                "app.agent_runtime.service.HttpModelGateway", new=lambda **_kw: gateway
            ):
                if cancel:
                    task = asyncio.create_task(
                        service.run_agent(question, list(history or ()) or None)
                    )
                    await asyncio.wait_for(entered.wait(), 10)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError as error:
                        record["error"] = error
                else:
                    try:
                        record["result"] = await service.run_agent(
                            question, list(history or ()) or None
                        )
                    except Exception as error:  # noqa: BLE001 - asserted by callers
                        record["error"] = error
            self.assertEqual(current_principal(), principal)
            self.assertEqual(_pending_tasks(), set())

        token = set_principal(Principal("demo", "analyst"))
        try:
            with (
                patch(
                    "app.agent_runtime.service.get_settings", return_value=self.settings
                ),
                patch("app.agent_runtime.service.emit", new=emit),
                patch(
                    "app.agent_runtime.service.get_model_health",
                    return_value={"status": "healthy"},
                ),
                patch(
                    "app.agent_runtime.service.claim_model_call",
                    return_value=(True, {"status": "healthy"}, None),
                ),
                patch(
                    "app.agent_runtime.service.record_model_success",
                    return_value=({"status": "healthy"}, None),
                ),
                patch(
                    "app.agent_runtime.service.record_model_failure",
                    return_value=({"status": "open"}, "opened"),
                ),
                patch(
                    "app.tools.knowledge_search.runtime_search.create_runtime_knowledge_port",
                    new=self.native._knowledge_port,
                ),
            ):
                asyncio.run(drive())
        finally:
            reset_principal(token)
        gateway = record["gateway"]
        self.assertEqual(gateway.closed, len(gateway.opened))
        return record

    @staticmethod
    def _summary(record: dict[str, object]) -> object:
        return _plain({"result": record["result"], "events": record["events"]})

    def _clean(self, path: str) -> dict[str, object]:
        record = self._legacy(path)
        self.assertIsNone(record["error"])
        return record

    def test_success_paths_return_stable_results_and_events(self) -> None:
        process = _process_state()
        for path in ("loop", "ready", "context"):
            with self.subTest(path=path):
                first = self._clean(path)
                second = self._clean(path)
                result = first["result"]
                names = [name for name, _fields in first["events"]]
                self.assertEqual(result["status"], "success")
                self.assertTrue(
                    {
                        "answer",
                        "mode",
                        "tool_trace",
                        "sources",
                        "intent_route",
                        "execution_plan",
                        "loop_guard",
                        "evidence_validation",
                        "context_resolution",
                        "trace_semantics",
                        "run_id",
                    }
                    <= set(result)
                )
                self.assertEqual(names[0], "agent_run_started")
                self.assertEqual(names[-1], "agent_run_finished")
                self.assertEqual(first["events"][-1][1]["status"], "success")
                self.assertTrue(
                    all(item["status"] == "ok" for item in result["tool_trace"])
                )
                gateway = first["gateway"]
                if path == "loop":
                    self.assertEqual(result["mode"], "deepseek")
                    self.assertEqual(
                        [item["tool"] for item in result["tool_trace"]],
                        ["get_lot_identity"],
                    )
                    self.assertEqual(len(gateway.requests), 2)
                else:
                    self.assertEqual(
                        result["execution_mode"], "deterministic_ready_plan"
                    )
                    self.assertEqual(len(result["tool_trace"]), 6)
                    self.assertEqual(len(gateway.requests), 1 if path == "ready" else 2)
                if path == "context":
                    resolution = result["context_resolution"]
                    self.assertEqual(resolution["resolved_question"], _READY_QUESTION)
                    self.assertTrue(resolution["applied"])
                self.assertNotEqual(
                    first["result"]["run_id"], second["result"]["run_id"]
                )
                self.assertEqual(self._summary(first), self._summary(second))
        self.assertEqual(_process_state(), process)

    def test_cancel_mid_model_call_closes_session_and_leaves_no_residue(self) -> None:
        cancel_scripts = {
            "loop": (_HANG,),
            "ready": (_HANG,),
            "context": (_HANG,),
        }
        process = _process_state()
        for path, script in cancel_scripts.items():
            with self.subTest(path=path):
                clean = self._clean(path)
                cancelled = self._legacy(path, script, cancel=True)
                self.assertIsInstance(cancelled["error"], asyncio.CancelledError)
                self.assertIsNone(cancelled["result"])
                self.assertEqual(len(cancelled["gateway"].opened), 1)
                names = [name for name, _fields in cancelled["events"]]
                self.assertEqual(names[0], "agent_run_started")
                # Cancellation is not converted into a run outcome here; the
                # HTTP chat services own that terminal status.
                self.assertNotIn("agent_run_finished", names)
                follow_up = self._clean(path)
                self.assertEqual(self._summary(follow_up), self._summary(clean))
        self.assertEqual(_process_state(), process)

    def test_model_failure_surfaces_or_falls_back_without_residue(self) -> None:
        process = _process_state()
        for path in ("loop", "ready", "context"):
            with self.subTest(path=path):
                clean = self._clean(path)
                failed = self._legacy(
                    path, (RuntimeError("model down"), RuntimeError("model down"))
                )
                names = [name for name, _fields in failed["events"]]
                self.assertEqual(names[-1], "agent_run_finished")
                if path == "loop":
                    self.assertIsInstance(failed["error"], RuntimeError)
                    self.assertEqual(failed["events"][-1][1]["status"], "error")
                elif path == "ready":
                    self.assertIsNone(failed["error"])
                    self.assertEqual(failed["result"]["status"], "success")
                    self.assertIn("model_local_fallback_activated", names)
                else:
                    # A failed contextualizer degrades to the original turn.
                    self.assertIsNone(failed["error"])
                    self.assertEqual(
                        failed["result"]["context_resolution"]["resolution_state"],
                        "unavailable",
                    )
                    self.assertIn("question_context_degraded", names)
                    self.assertEqual(failed["events"][-1][1]["outcome"], "degraded")
                follow_up = self._clean(path)
                self.assertEqual(self._summary(follow_up), self._summary(clean))
        self.assertEqual(_process_state(), process)

    def test_tool_failure_is_reported_without_residue(self) -> None:
        def explode(_self: object, _query: object, _principal: object) -> object:
            raise RuntimeError("adapter exploded")

        process = _process_state()
        for path in ("loop", "ready", "context"):
            with self.subTest(path=path):
                clean = self._clean(path)
                with patch.object(SQLiteNamedQueryAdapter, "fetch", explode):
                    failed = self._legacy(path)
                self.assertIsNone(failed["error"])
                result = failed["result"]
                self.assertEqual(result["status"], "success")
                codes = {item.get("error_code") for item in result["tool_trace"]}
                self.assertIn("DATA_SOURCE_FAILED", codes)
                self.assertNotIn("adapter exploded", result["answer"])
                if path != "loop":
                    self.assertIn(
                        "blocked", {item["status"] for item in result["tool_trace"]}
                    )
                follow_up = self._clean(path)
                self.assertEqual(self._summary(follow_up), self._summary(clean))
        self.assertEqual(_process_state(), process)


class ConvergenceBoundaryGuardTests(unittest.TestCase):
    @staticmethod
    def _imported_modules(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.add("." * node.level + (node.module or ""))
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        return names

    @staticmethod
    def _members(protocol: type) -> set[str]:
        return {
            name
            for name, value in vars(protocol).items()
            if isinstance(value, property)
        }

    def test_orchestration_seams_no_longer_import_owner_modules(self) -> None:
        arbiter = self._imported_modules(
            ROOT / "app" / "conversation" / "decision_arbiter.py"
        )
        validator = self._imported_modules(ROOT / "app" / "evidence" / "validator.py")
        self.assertFalse(any("memory_system" in name for name in arbiter))
        self.assertFalse(
            any("planning_runtime" in name or "playbooks" in name for name in validator)
        )

    def test_owner_types_structurally_satisfy_the_read_only_views(self) -> None:
        workflow = LithoCpkWorkflow()
        plan, selection = workflow.build(_QUESTION, route_question(_QUESTION, _AS_OF))
        playbook = selection.selected_playbook
        cases = (
            (evidence_validator.ExecutionPlanView, plan),
            (evidence_validator.PlanStepView, plan.steps[0]),
            (evidence_validator.PlanScopeView, plan.scope_contract),
            (evidence_validator.EvidencePolicyView, playbook),
            (
                evidence_validator.EvidenceRequirementView,
                playbook.evidence_requirements[0],
            ),
        )
        for protocol, instance in cases:
            with self.subTest(protocol=protocol.__name__):
                members = self._members(protocol)
                self.assertTrue(members)
                self.assertEqual(
                    {name for name in members if not hasattr(instance, name)}, set()
                )
        fields = {item.name for item in dataclasses.fields(ContextResolution)}
        self.assertLessEqual(self._members(decision_arbiter.DecisionContext), fields)


if __name__ == "__main__":
    unittest.main()
