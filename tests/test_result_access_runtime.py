"""Result storage is exercised through real runtime, SQLite and HTTP boundaries."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.result_access_run import (
    ResultAccessRun,
    ResultRequestLimit,
    stream_result_model,
)
from app.agent_runtime.result_review import review_saved_result
from app.agent_runtime.synthesis.ready import request_ready_synthesis
from app.bootstrap.result_access_assembly import make_result_access_run
from app.conversation import sessions
from app.intent_runtime.routing import route_question
from app.persistence.tool_result_store import ToolResultStore
from app.planning_runtime.playbooks import select_playbook
from app.planning_runtime.service import create_execution_plan
from tests import test_session_result_lifecycle as lifecycle_tests


def guard():
    route = route_question("分析 CVD 制程能力", date(2026, 11, 15))
    plan = create_execution_plan("分析 CVD 制程能力", route, select_playbook(route))
    return ToolLoopGuard(replace(plan, budget=replace(plan.budget, max_tool_calls=10)))


class ResultAccessRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ToolResultStore(Path(temp.name) / "results.db")
        self.store.initialize()
        self.principal = SimpleNamespace(tenant_id="t", user_id="u", roles=("analyst",))
        self.scope = {"tenant_id": "t", "owner_id": "u", "session_id": "s"}
        self.access = self.run_access()

    def run_access(self, **changes):
        options = {
            "session_id": "s",
            "run_id": "r",
            "principal": self.principal,
            "store": self.store,
            "enabled": True,
            "authorize": lambda: True,
            "unavailable_reason": "",
        }
        options.update(changes)
        run = ResultAccessRun(**options)
        run.bind(guard())
        return run

    def render(self, tool="unknown", data=None, **changes):
        return self.access.render(
            tool,
            data
            if data is not None
            else [{"row": i, "text": "中文" * 400} for i in range(30)],
            call_id="c",
            source_ref="TOOL:S1",
            scope={"equipment_id": "CVD-01"},
            **changes,
        )

    def test_full_adopted_result_survives_preview_and_cross_run_restart(self):
        data = [{"row": i, "text": "中文" * 400} for i in range(30)]
        view = self.render(data=data)
        self.assertLessEqual(
            len(json.dumps(view, ensure_ascii=False, separators=(",", ":")).encode()),
            8192,
        )
        self.assertEqual(view["result_access"]["status"], "saved")
        ref = view["result_access"]["result_ref"]
        self.access.close()
        other = self.run_access(run_id="later", store=ToolResultStore(self.store.path))
        other.begin_synthesis(60)
        page = asyncio.run(other.read({"result_ref": ref, "limit": 1}))
        self.assertEqual(page["format"], "units")
        self.assertEqual(page["units"], [data[0]])
        self.assertEqual(page["scope"], {"equipment_id": "CVD-01"})
        self.assertIn("queried_at", page)
        self.assertEqual(other.guard.total_calls, 1)
        self.assertFalse(other.guard.tool_calls)

    def test_small_results_no_snapshot_and_disabled_vs_failed_notices_differ(self):
        self.assertNotIn("result_access", self.render(data=[{"value": 1}]))
        self.access = self.run_access(enabled=False)
        disabled = self.render()["result_access"]
        self.assertEqual(
            (disabled["status"], disabled["reason"]),
            ("truncated", "OFFLOADING_DISABLED"),
        )
        self.assertNotIn("result_ref", disabled)
        self.access = self.run_access()
        with patch.object(
            self.store, "save", side_effect=OSError("private connection")
        ):
            failed = self.render()["result_access"]
        self.assertEqual(failed["status"], "unavailable")
        self.assertNotIn("private", json.dumps(failed))
        self.assertNotIn("result_ref", failed)

    def test_final_transport_bounds_include_template_and_read_parts(self):
        huge = {"messages": [{"role": "tool", "content": "中" * 3000}]}
        with self.assertRaises(ResultRequestLimit):
            self.access.prepare_request(huge, None)
        messages = [
            {"role": "system", "content": "x" * 13000, "_fab_tool_result": True}
        ] * 2
        with self.assertRaises(ResultRequestLimit):
            self.access.prepare_request({"messages": messages}, None)

        class Endpoint:
            def prepare_payload(self, payload):
                return {
                    "messages": [
                        {
                            "role": "user",
                            "content": payload["messages"][0]["content"]
                            + "padding" * 2000,
                        }
                    ]
                }

        with self.assertRaises(ResultRequestLimit):
            self.access.prepare_request(
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": "x" * 16000,
                            "_fab_tool_result": True,
                        }
                    ]
                },
                SimpleNamespace(endpoint=Endpoint()),
            )
        clean, _ = self.access.prepare_request(
            {
                "messages": [
                    {"role": "tool", "content": "page", "_fab_result_read": True}
                ]
            },
            None,
        )
        self.assertEqual(clean["messages"], [{"role": "tool", "content": "page"}])

    def test_request_failure_charges_output_and_deadline_cannot_reset(self):
        self.access.begin_synthesis(60, 100)
        deadline = self.access.deadline

        class Broken:
            async def stream(self, *_args):
                raise OSError("lost usage")

        with self.access.activate(), self.assertRaises(OSError):
            asyncio.run(
                stream_result_model(Broken(), {"messages": [], "max_tokens": 100}, None)
            )
        self.assertEqual(
            (self.access.request_count, self.access.output_remaining), (1, 2048)
        )
        self.access.begin_synthesis(600, 8192)
        self.assertEqual(
            (self.access.deadline, self.access.output_remaining), (deadline, 2048)
        )
        for _ in range(5):
            self.access.prepare_request({"messages": [], "max_tokens": 1}, None)
        with self.assertRaises(ResultRequestLimit):
            self.access.prepare_request({"messages": []}, None)

    def test_rejected_read_arguments_consume_the_shared_attempt_budget(self):
        self.access.begin_synthesis(60)
        for _ in range(4):
            result = asyncio.run(self.access.read("{"))
            self.assertFalse(result["ok"])
        self.assertEqual(
            (self.access.guard.total_calls, self.access.reader.reads), (4, 4)
        )
        self.assertFalse(self.access.guard.tool_calls)
        result = asyncio.run(self.access.read("{"))
        self.assertEqual(result["error_code"], "RESULT_READ_BUDGET")

    def test_ready_protocol_reads_then_submits_without_business_query_or_evidence(self):
        view = self.render()
        self.access.begin_synthesis(60)
        ref = view["result_access"]["result_ref"]
        requests = []

        class Model:
            async def stream(self, payload, *_args):
                requests.append(payload)
                names = {tool["function"]["name"] for tool in payload["tools"]}
                assert names == {"read_tool_result", "submit_analysis"}
                if len(requests) == 1:
                    assistant = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "read-1",
                                "type": "function",
                                "function": {
                                    "name": "read_tool_result",
                                    "arguments": json.dumps(
                                        {"result_ref": ref, "limit": 1}
                                    ),
                                },
                            }
                        ],
                    }
                else:
                    page = json.loads(payload["messages"][-1]["content"])
                    assert page["units"][0]["row"] == 0
                    assistant = {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "final",
                                "type": "function",
                                "function": {
                                    "name": "submit_analysis",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                return (
                    assistant,
                    {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
                    "id",
                )

        from app.agent_runtime import service

        with self.access.activate():
            result = asyncio.run(
                request_ready_synthesis(
                    Model(),
                    SimpleNamespace(model="fake", provider="other"),
                    SimpleNamespace(model_retry_base_seconds=0),
                    [{"role": "user", "content": "saved reference"}],
                    "r",
                    False,
                    0,
                    deps=service._ready_synthesis_dependencies(),
                )
            )
        self.assertEqual(result[1]["completion_tokens"], 10)
        self.assertEqual(
            (len(requests), self.access.reader.reads, self.access.guard.total_calls),
            (2, 1, 1),
        )
        self.assertFalse(self.access.guard.tool_calls)

    def test_old_selection_is_bounded_and_never_counts_as_new_business_evidence(self):
        view = self.render()
        new = ResultAccessRun(
            session_id="s",
            run_id="later",
            principal=self.principal,
            store=self.store,
            enabled=True,
            authorize=lambda: True,
            unavailable_reason="",
        )
        result = asyncio.run(
            review_saved_result(new, view["result_access"]["result_ref"], None, None)
        )
        self.assertEqual(result["mode"], "snapshot_review")
        self.assertEqual((result["sources"], result["tool_trace"]), ([], []))
        self.assertIn("未重新查询", result["answer"])
        self.assertIsNotNone(result["tool_result_page"])
        self.assertLessEqual(
            len(
                json.dumps(
                    result["tool_result_page"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ),
            4096,
        )


class ResultAccessHostTests(unittest.TestCase):
    setUp = lifecycle_tests.SessionResultLifecycleTests.setUp

    def test_permanent_deletion_cancels_inflight_run_and_prevents_late_publish(self):
        async def scenario():
            access = make_result_access_run(self.session, "active")
            entered = asyncio.Event()

            async def active():
                with access.activate():
                    entered.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(active())
            await entered.wait()
            sessions.delete_session_permanently(self.session)
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(access.closed)
            access.bind(guard())
            notice = access.render(
                "unknown", "x" * 20000, call_id="late", source_ref="TOOL:late"
            )["result_access"]
            self.assertNotIn("result_ref", notice)

        asyncio.run(scenario())

    def test_loop_read_uses_existing_snapshot_without_new_business_trace(self):
        from app.agent_runtime import service

        requests = []
        events = []
        calls = []
        data = [
            {"equipment_id": "CMP-03", "cpk": 0.91, "samples": 120, "text": "x" * 500}
            for _ in range(30)
        ]

        def source(**arguments):
            calls.append(arguments)
            return data

        async def stream(_client, _endpoint, _headers, payload, _progress, _state):
            requests.append(payload)
            number = len(requests)
            if number <= 3:
                name = "get_process_capability"
                arguments = {
                    "start": "2026-11-01",
                    "end": "2026-11-15",
                    "process_step": "CMP",
                }
            elif number == 4:
                name = "read_tool_result"
                views = [
                    json.loads(m["content"])
                    for m in payload["messages"]
                    if m["role"] == "tool"
                ]
                arguments = {
                    "result_ref": views[0]["result_access"]["result_ref"],
                    "limit": 1,
                }
                self.assertIn(name, {t["function"]["name"] for t in payload["tools"]})
                self.assertEqual(payload["tool_choice"], "auto")
            else:
                return (
                    {"role": "assistant", "content": "已查看原快照，停止重复查询。"},
                    {"completion_tokens": 1},
                    "final",
                )
            return (
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{number}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                {"completion_tokens": 1},
                "id",
            )

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(
                provider="test",
                api_key="fake",
                base_url="https://example.test",
                model="fake",
            ),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0,
        )
        with (
            patch.object(service, "get_settings", return_value=settings),
            patch.object(service, "_stream_completion", new=stream),
            patch.dict(service.TOOL_HANDLERS, {"get_process_capability": source}),
            patch.dict(
                "app.planning_runtime.named_playbooks.NAMED_DOMAIN_PLAYBOOKS",
                {},
                clear=True,
            ),
        ):
            result = asyncio.run(
                service._run_agent_impl(
                    "分析 CMP 划伤缺陷 Pareto",
                    [],
                    "loop-result-read",
                    lambda event: events.append(event),
                    session_id=self.session,
                )
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(requests), 5)
        self.assertEqual(len(result["tool_trace"]), 3)
        self.assertEqual(result["loop_guard"]["total_calls"], 2)
        self.assertTrue(
            any(
                e.get("event") == "tool_result_read" and e.get("status") == "ok"
                for e in events
            )
        )

    def test_actual_default_run_emits_saved_or_disabled_and_persists_reference(self):
        from app.agent_runtime import service

        data = [
            {"equipment_id": f"CVD-{i:02}", "health": "warning", "excursions": i}
            for i in range(30)
        ]
        events = []
        settings = SimpleNamespace(
            model_connection=SimpleNamespace(
                provider="test", api_key="", base_url="http://unused", model="fake"
            ),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0,
        )
        handlers = {
            "get_equipment_health": lambda **_kw: data,
            "get_fab_overview": lambda **_kw: {
                "lots": 10,
                "yield_pct": 90,
                "avg_cycle_hours": 4,
            },
        }

        async def scenario():
            with (
                patch.object(service, "get_settings", return_value=settings),
                patch.dict(service.TOOL_HANDLERS, handlers),
            ):
                saved = await service.run_agent(
                    "最近哪些设备风险最高",
                    [],
                    lambda event: events.append(event),
                    session_id=self.session,
                )
                notice = saved["tool_result_access"][0]
                self.assertEqual(len(saved["tool_result_access"]), 1)
                self.assertEqual(notice["status"], "saved")
                self.assertTrue(
                    any(e.get("event") == "tool_result_access" for e in events)
                )
                message = sessions.append_message(
                    self.session, "assistant", saved["answer"], saved
                )
                self.assertTrue(message["message_id"])
                stored = sessions.get_session(self.session)["messages"][-1]
                self.assertEqual(
                    stored["metadata"]["tool_result_access"][0]["result_ref"],
                    notice["result_ref"],
                )
                self.store.set_enabled(False)
                disabled = await service.run_agent(
                    "最近哪些设备风险最高", [], session_id=self.session
                )
                self.assertEqual(
                    disabled["tool_result_access"][0]["status"], "truncated"
                )

        asyncio.run(scenario())

    def test_http_stream_saved_review_persists_exact_result_and_rejects_cross_session(
        self,
    ):
        import httpx
        from fastapi import FastAPI

        from app import main
        from app.api.routers.chat import create_router

        app = FastAPI()
        app.include_router(create_router(lambda: vars(main)).router)
        principal = self.bindings.current_principal()

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                with patch.object(
                    main,
                    "_validate_chat_model_capabilities",
                    return_value=(principal, "fake"),
                ):
                    response = await client.post(
                        "/api/chat/stream",
                        json={
                            "message": "查看已保存结果",
                            "session_id": self.session,
                            "tool_result_ref": self.ref,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    lines = [json.loads(line) for line in response.text.splitlines()]
                    final = next(
                        line["result"] for line in lines if line["type"] == "result"
                    )
                    self.assertEqual(final["tool_result_page"]["units"], [{"value": 7}])
                    self.assertTrue(
                        any(line.get("event") == "answer_delta" for line in lines)
                    )
                    other = sessions.create_session()["session_id"]
                    denied = await client.post(
                        "/api/chat",
                        json={
                            "message": "查看已保存结果",
                            "session_id": other,
                            "tool_result_ref": self.ref,
                        },
                    )
                    self.assertIsNone(denied.json()["tool_result_page"])
                    self.assertNotIn('"value": 7', denied.text)
                self.assertEqual(
                    sessions.get_session(self.session)["messages"][-1]["metadata"][
                        "tool_result_page"
                    ],
                    final["tool_result_page"],
                )

        asyncio.run(scenario())

    def test_switch_is_snapshotted_for_new_runs_and_restores_saved_reads(self):
        first = make_result_access_run(self.session, "first")
        self.assertTrue(first.enabled)
        self.store.set_enabled(False)
        second = make_result_access_run(self.session, "second")
        self.assertFalse(second.enabled)
        self.assertTrue(first.enabled)
        result = asyncio.run(review_saved_result(second, self.ref, None, None))
        self.assertIsNone(result["tool_result_page"])
        self.store.set_enabled(True)
        third = make_result_access_run(self.session, "third")
        result = asyncio.run(review_saved_result(third, self.ref, None, None))
        self.assertEqual(result["tool_result_page"]["units"], [{"value": 7}])
        sessions.delete_session_permanently(self.session)
        self.assertFalse(third.authorize())
        self.assertFalse(third.can_read())

    def test_http_admin_toggle_authorization_and_strict_schema(self):
        import httpx
        from fastapi import FastAPI, HTTPException

        from app.api.errors import http_problem
        from app.api.routers.admin import create_router

        admin = {"allowed": True}

        async def current_admin():
            if not admin["allowed"]:
                raise HTTPException(403, "denied")
            return "admin"

        bundle = create_router(
            lambda: {
                "configured_result_store": lambda: self.store,
                "http_problem": http_problem,
            },
            current_admin,
        )
        app = FastAPI()
        app.include_router(bundle.router)

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = "/api/admin/tool-result-storage"
                self.assertTrue((await client.get(path)).json()["enabled"])
                self.assertEqual(
                    (await client.put(path, json={"enabled": "false"})).status_code, 422
                )
                self.assertFalse(
                    (await client.put(path, json={"enabled": False})).json()["enabled"]
                )
                admin["allowed"] = False
                self.assertEqual(
                    (await client.put(path, json={"enabled": True})).status_code, 403
                )
                self.assertFalse(ToolResultStore(self.store.path).enabled())

        asyncio.run(scenario())


class ResultAccessTypedTests(unittest.TestCase):
    setUp = ResultAccessRuntimeTests.setUp
    run_access = ResultAccessRuntimeTests.run_access

    def test_ready_binding_carries_result_access_and_reads_after_real_completion(self):
        from app.agent_runtime.definition import ComponentReference
        from app.agent_runtime.execution.ready_dispatch import (
            execute_dispatched_ready_plan,
        )
        from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
        from app.agent_runtime.execution.runtime_contracts import (
            ModelToolCall,
            RuntimeContext,
        )
        from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
        from app.agent_runtime.tools.contracts import ToolExecutionLimits
        from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
        from app.bootstrap.agent_assembly import assemble_agent
        from app.bootstrap.ready_assembly import bind_ready_run
        from tests import test_agent_assembly as agent_fixture
        from tests import test_ready_dispatcher as fixture

        plan = fixture._plan(fixture._step("S1", "native", limit=1), maximum=4)
        shared = ToolLoopGuard(plan)
        definition = agent_fixture._definition(
            tools=(ComponentReference("native", "1.0.0"),)
        )
        original = fixture._native_binding("native", [{"text": "中文" * 4000}])
        binding = replace(
            original,
            definition=replace(original.definition, version="1.0.0"),
            handler=lambda value, context: replace(
                original.handler(value, context), tool_version="1.0.0"
            ),
        )
        application = assemble_agent(
            definition,
            model=agent_fixture.FakeModel(),
            events=agent_fixture.FakeSink(),
            bindings=(binding,),
            policy=DemoToolPolicy(frozenset({"native"})),
            budget_factory=lambda: LoopGuardToolBudget(shared),
            server_capabilities=frozenset({"native"}),
            model_policy_ref=definition.model_policy,
            policy_ref=definition.default_policy,
        )
        context = RuntimeContext(
            self.principal,
            "ready-run",
            ToolExecutionLimits(remaining_calls=4, max_result_rows=1),
        )
        access = ResultAccessRun(
            session_id="s",
            run_id=context.run_id,
            principal=self.principal,
            store=self.store,
            enabled=True,
            authorize=lambda: True,
        )
        projector = ReadyResultPolicy()
        run = application.new_run(context, result_access=access, result_policy=projector)

        async def notify(*_args):
            pass

        async def scenario():
            outcome = await execute_dispatched_ready_plan(
                plan,
                shared,
                context.run_id,
                None,
                binding=bind_ready_run(plan, shared, run, projector),
                notify=notify,
                emit_event=lambda *_a, **_k: None,
            )
            self.assertEqual(shared.stop_reason, "deterministic_plan_completed")
            self.assertEqual(outcome.tool_results[0].data, [{"text": "中文" * 4000}])
            self.assertEqual(len(outcome.observation_payloads), 1)
            reference = access.notices[0]["result_ref"]
            run.begin_synthesis()
            read = await run.tool_stage(
                ModelToolCall(
                    "read", "read_tool_result", json.dumps({"result_ref": reference})
                ),
                call_id="read-server",
            )
            self.assertEqual(read.value.data["format"], "unit_fragment")
            self.assertEqual(
                (shared.total_calls, dict(shared.tool_calls)), (2, {"native": 1})
            )

        asyncio.run(scenario())

    def test_default_typed_run_has_no_session_io_and_preserves_failed_tool_message(
        self,
    ):
        from app.agent_runtime.execution.runtime_contracts import (
            ModelMessage,
            ModelToolCall,
        )
        from tests import test_agent_assembly as fixture

        helper = fixture.AgentAssemblyTests()
        application, _ = helper.assemble(calls=4)
        run = application.new_run(fixture._context())
        self.assertIsNone(run.result_access.store)

        async def scenario():
            failed = await run.tool_stage(
                ModelToolCall("bad", "get_equipment_health", "{"), call_id="bad-server"
            )
            self.assertIsNotNone(failed.value.error)
            await run.model_stage(
                call_id="after-error",
                messages=(
                    ModelMessage("tool", "untrusted raw" * 10000, tool_call_id="bad"),
                ),
            )
            view = json.loads(application.model.request.messages[-1].content)
            self.assertFalse(view["ok"])
            self.assertEqual(view["error_code"], "INVALID_ARGUMENTS")

        asyncio.run(scenario())

    def test_typed_shared_budget_and_real_result_replaces_caller_raw_message(self):
        from app.agent_runtime.execution.runtime_contracts import (
            ModelMessage,
            ModelToolCall,
        )
        from tests import test_agent_assembly as fixture

        helper = fixture.AgentAssemblyTests()
        application, budgets = helper.assemble(calls=4)
        context = fixture._context()
        access = ResultAccessRun(
            session_id="s",
            run_id=context.run_id,
            principal=context.principal,
            store=self.store,
            enabled=True,
            authorize=lambda: True,
            unavailable_reason="",
        )
        run = application.new_run(context, result_access=access)

        async def scenario():
            tool = await run.tool_stage(
                ModelToolCall("provider", "get_equipment_health", "{}"),
                call_id="server",
            )
            self.assertIsNotNone(tool.value.data)
            run.begin_synthesis()
            response = await run.model_stage(
                call_id="model",
                messages=(
                    ModelMessage(
                        "tool", "untrusted raw" * 10000, tool_call_id="provider"
                    ),
                ),
            )
            self.assertIsNotNone(response.value)
            self.assertNotIn(
                "untrusted raw", application.model.request.messages[-1].content
            )
            self.assertIsNotNone(application.model.request.max_output_tokens)
            self.assertIs(access.guard, budgets[0].guard)
            run.close()
            with self.assertRaises(ResultRequestLimit):
                await run.model_stage(call_id="late", messages=())

        asyncio.run(scenario())

    def test_skill_assembly_accepts_explicit_result_scope_without_global_storage(self):
        from app.agent_runtime.execution.runtime_contracts import RuntimeContext
        from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
        from app.bootstrap.agent_assembly import assemble_agent
        from app.bootstrap.litho_cpk_demo import _Principal
        from tests import test_skill_agent_assembly as fixture

        helper = fixture.SkillAgentAssemblyTests()
        definition, bindings, configuration, request, capabilities = (
            helper._enabled_inputs()
        )
        application = assemble_agent(
            definition,
            model=fixture._Model(),
            events=fixture._Events(),
            bindings=bindings,
            policy=helper._policy(),
            budget_factory=lambda: LoopGuardToolBudget(guard()),
            server_capabilities=capabilities,
            model_policy_ref=definition.model_policy,
            policy_ref=definition.default_policy,
            skill_configuration=configuration,
            skill_request=request,
        )
        context = RuntimeContext(_Principal(), "skill-run")
        access = ResultAccessRun(
            session_id="s",
            run_id=context.run_id,
            principal=context.principal,
            store=self.store,
            enabled=True,
            authorize=lambda: True,
        )
        run = application.new_run(context, result_access=access)
        run.begin_synthesis()
        self.assertTrue(run.skill_context)
        response = asyncio.run(run.model_stage(call_id="synthesis", messages=()))
        self.assertEqual(response.value.content, "unused")
        run.close()


if __name__ == "__main__":
    unittest.main()
