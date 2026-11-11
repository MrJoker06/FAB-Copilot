"""Focused F2b cutover invariants for the default coordinator assembly."""

from __future__ import annotations

import asyncio
import sqlite3
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime import service
from app.core.identity import Principal, reset_principal, set_principal
from app.agent_runtime.tools.contracts import ToolSource, ToolSourceKind
from app.tools.knowledge_search.contracts import KnowledgeSearchSnapshot, knowledge_scope
from app.bootstrap import knowledge_search_demo
from app.core.settings import get_settings
from tests import test_named_queries_adapters as adapter_tests


class DefaultNativeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = adapter_tests.NamedQueryAdapterTests()
        self.fixture.setUp()
        # The router deliberately recognizes LOT-001.  Keep the adapter fixture
        # otherwise identical, so this test has no dependency on project data.
        for path in (
            self.fixture.manufacturing,
            self.fixture.equipment,
            self.fixture.quality,
        ):
            with sqlite3.connect(path) as connection:
                for table in ("lots", "process_runs", "defect_records", "wafer_maps"):
                    try:
                        connection.execute(
                            f"UPDATE {table} SET lot_id='LOT-001' WHERE lot_id='L1'"
                        )
                    except sqlite3.OperationalError:
                        pass

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _settings(self, *, api_key: str = ""):
        settings = get_settings()
        # A duck-typed settings snapshot is deliberately not ``Settings``:
        # ``effective_agent_settings`` then does not read the project model
        # catalog.  The default coordinator/builder remain unchanged.
        values = vars(settings).copy()
        values.update(
            manufacturing_database_path=self.fixture.manufacturing,
            equipment_database_path=self.fixture.equipment,
            quality_database_path=self.fixture.quality,
            enterprise_default_tenant_id="demo",
            enterprise_default_user_id="analyst",
            model_connection=replace(
                settings.model_connection,
                base_url="https://offline.invalid",
                api_key=api_key,
            ),
        )
        return SimpleNamespace(**values)

    @staticmethod
    def _knowledge_port(*, settings, principal):
        class Port:
            def fetch(self, query, requested_principal):
                return KnowledgeSearchSnapshot(
                    query=query,
                    tenant_id=requested_principal.tenant_id,
                    user_id=requested_principal.user_id,
                    owner_user_id=(
                        requested_principal.user_id
                        if "personal" in query.source_types
                        else None
                    ),
                    aliases={},
                    candidates=(),
                    sources=(
                        ToolSource(
                            "fake:knowledge",
                            "test-knowledge",
                            ToolSourceKind.FAKE,
                            knowledge_scope(requested_principal),
                        ),
                    ),
                )

        return Port()

    def test_default_coordinator_uses_per_run_tool_factory_and_named_planner(
        self,
    ) -> None:
        dependencies = service._coordinator_dependencies()

        self.assertIsNotNone(dependencies.tool_run_factory)
        group = dependencies.agent_preparation_dependencies()
        self.assertEqual(
            group.planning.select_playbook.__name__, "select_named_playbook"
        )
        self.assertEqual(
            group.planning.create_execution_plan.__name__, "create_named_execution_plan"
        )
        self.assertIs(dependencies.loop.tools, service.TOOLS)

    def test_default_prompt_omits_legacy_catalog_but_preserves_rules(self) -> None:
        self.assertNotIn("数据库字段提示", service.SYSTEM_PROMPT)
        self.assertNotIn("lots: lot_id", service.SYSTEM_PROMPT)
        self.assertIn("aggregation.exact=false", service.SYSTEM_PROMPT)
        self.assertIn("数据库字段提示", service.LEGACY_SYSTEM_PROMPT)

    def test_actual_default_ready_run_uses_named_native_tools_without_model(
        self,
    ) -> None:
        offline = self._settings()
        token = set_principal(Principal("demo", "analyst"))
        try:
            with (
                patch("app.agent_runtime.service.get_settings", return_value=offline),
                patch(
                    "app.tools.knowledge_search.runtime_search.create_runtime_knowledge_port",
                    new=self._knowledge_port,
                ),
            ):
                result = asyncio.run(
                    service._run_agent_impl(
                        "查询 LOT-001 的批次信息",
                        [],
                        "default-native-ready",
                    )
                )
        finally:
            reset_principal(token)

        self.assertEqual(result["execution_plan"]["planner_version"], "2.0.0")
        self.assertEqual(result["execution_mode"], "deterministic_ready_plan")
        trace = result["tool_trace"]
        self.assertEqual(len(trace), 6)
        succeeded = [row for row in trace if row.get("status") == "ok"]
        self.assertEqual(len(trace), 6)
        self.assertEqual(len(succeeded), 6, trace)
        self.assertEqual({row.get("tool_version") for row in trace}, {"1.0.0"})
        self.assertEqual(result["loop_guard"]["total_calls"], 6)
        self.assertNotIn("query_manufacturing_data", {row["tool"] for row in trace})
        self.assertTrue(result["evidence_validation"]["coverage"]["required_covered"])

    def test_actual_missing_model_general_knowledge_does_no_business_read(self) -> None:
        offline = self._settings()
        with patch("app.agent_runtime.service.get_settings", return_value=offline):
            result = asyncio.run(
                service._run_agent_impl(
                    "什么是光刻胶",
                    [],
                    "default-native-general-knowledge",
                )
            )

        self.assertEqual(result["tool_trace"], [])
        self.assertEqual(result["mode"], "offline")

    def test_model_loop_denies_sql_even_when_global_handler_is_patched(self) -> None:
        settings = self._settings(api_key="fixture-key")
        calls: list[object] = []
        sql_calls: list[object] = []

        async def stream(_client, _endpoint, _headers, _payload, _progress, _state):
            calls.append(None)
            if len(calls) == 1:
                return (
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "sql-call",
                                "type": "function",
                                "function": {
                                    "name": "query_manufacturing_data",
                                    "arguments": '{"sql":"SELECT * FROM lots"}',
                                },
                            }
                        ],
                    },
                    {"total_tokens": 1},
                    "fixture-1",
                )
            return (
                {"role": "assistant", "content": "已完成。"},
                {"total_tokens": 1},
                "fixture-2",
            )

        def sql_spy(**kwargs):
            sql_calls.append(kwargs)
            return []

        token = set_principal(Principal("demo", "analyst"))
        try:
            with (
                patch("app.agent_runtime.service.get_settings", return_value=settings),
                patch("app.agent_runtime.service._stream_completion", new=stream),
                patch(
                    "app.agent_runtime.service.get_model_health",
                    return_value={"status": "healthy"},
                ),
                patch.dict(
                    service.TOOL_HANDLERS, {"query_manufacturing_data": sql_spy}
                ),
                patch.dict(
                    "app.planning_runtime.named_playbooks.NAMED_DOMAIN_PLAYBOOKS", {}, clear=True
                ),
            ):
                result = asyncio.run(
                    service._run_agent_impl(
                        "分析 CMP 划伤缺陷 Pareto",
                        [],
                        "default-native-sql-denial",
                    )
                )
        finally:
            reset_principal(token)

        self.assertEqual(len(calls), 2, result)
        self.assertEqual(sql_calls, [])
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertEqual(result["tool_trace"][0]["tool"], "query_manufacturing_data")
        self.assertEqual(result["tool_trace"][0]["status"], "blocked")
        self.assertEqual(result["tool_trace"][0]["execution_mode"], "model_loop")

    def test_model_loop_executes_native_named_tool(self) -> None:
        settings = self._settings(api_key="fixture-key")
        calls: list[object] = []

        async def stream(_client, _endpoint, _headers, _payload, _progress, _state):
            calls.append(None)
            if len(calls) == 1:
                return (
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "native-call",
                                "type": "function",
                                "function": {
                                    "name": "get_lot_identity",
                                    "arguments": '{"lot_id":"LOT-001"}',
                                },
                            }
                        ],
                    },
                    {"total_tokens": 1},
                    "fixture-1",
                )
            return (
                {"role": "assistant", "content": "已完成批次核验。"},
                {"total_tokens": 1},
                "fixture-2",
            )

        token = set_principal(Principal("demo", "analyst"))
        try:
            with (
                patch("app.agent_runtime.service.get_settings", return_value=settings),
                patch("app.agent_runtime.service._stream_completion", new=stream),
                patch(
                    "app.agent_runtime.service.get_model_health",
                    return_value={"status": "healthy"},
                ),
                patch.dict(
                    "app.planning_runtime.named_playbooks.NAMED_DOMAIN_PLAYBOOKS", {}, clear=True
                ),
            ):
                result = asyncio.run(
                    service._run_agent_impl(
                        "分析 CMP 划伤缺陷 Pareto",
                        [],
                        "default-native-loop-success",
                    )
                )
        finally:
            reset_principal(token)

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["loop_guard"]["total_calls"], 1)
        self.assertEqual(len(result["tool_trace"]), 1)
        trace = result["tool_trace"][0]
        self.assertEqual(trace["tool"], "get_lot_identity")
        self.assertEqual(trace["tool_version"], "1.0.0")
        self.assertEqual(trace["status"], "ok")
        self.assertEqual(trace["arguments"], {"lot_id": "LOT-001"})
        self.assertEqual(trace["sources"][0]["scope"]["lot_ids"], ["LOT-001"])
        self.assertEqual(trace["rows"], 1)

    def test_native_prefetch_evaluates_usable_result_once(self) -> None:
        settings = self._settings(api_key="fixture-key")
        usable_calls: list[object] = []
        model_calls: list[object] = []

        def knowledge_port(*, settings, principal):
            class Port:
                def fetch(self, query, requested_principal):
                    row = knowledge_search_demo._candidates("unused")[0]
                    row["process_steps"] = "CMP"
                    row["title"] = "CMP chemical mechanical polishing guide"
                    return KnowledgeSearchSnapshot(
                        query,
                        requested_principal.tenant_id,
                        requested_principal.user_id,
                        None,
                        {},
                        (row,),
                        (
                            ToolSource(
                                "fake:knowledge",
                                "test-knowledge",
                                ToolSourceKind.FAKE,
                                knowledge_scope(requested_principal),
                            ),
                        ),
                    )

            return Port()

        def usable(_query, _result):
            usable_calls.append(None)
            return len(usable_calls) == 1

        async def stream(_client, _endpoint, _headers, _payload, _progress, _state):
            model_calls.append(None)
            return (
                {"role": "assistant", "content": "CMP 是化学机械抛光。"},
                {"total_tokens": 1},
                "fixture",
            )

        token = set_principal(Principal("demo", "analyst"))
        try:
            with (
                patch("app.agent_runtime.service.get_settings", return_value=settings),
                patch("app.agent_runtime.service._stream_completion", new=stream),
                patch(
                    "app.agent_runtime.service.get_model_health",
                    return_value={"status": "healthy"},
                ),
                patch(
                    "app.agent_runtime.service.required_scopes",
                    return_value=("knowledge",),
                ),
                patch("app.agent_runtime.service._usable_knowledge_result", new=usable),
                patch(
                    "app.tools.knowledge_search.runtime_search.create_runtime_knowledge_port",
                    new=knowledge_port,
                ),
            ):
                result = asyncio.run(
                    service._run_agent_impl(
                        "解释一下化学机械抛光的基本原理",
                        [],
                        "default-native-prefetch",
                    )
                )
        finally:
            reset_principal(token)

        self.assertEqual(model_calls, [None])
        self.assertEqual(len(usable_calls), 1, result)
        self.assertEqual(result["loop_guard"]["total_calls"], 1)
        trace = result["tool_trace"]
        self.assertEqual(trace[0]["raw_rows"], 1)
        self.assertEqual(trace[0]["rows"], 1)
        self.assertTrue(result["sources"])
