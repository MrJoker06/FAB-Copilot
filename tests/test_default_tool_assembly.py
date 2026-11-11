from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSourceKind,
    ToolStatus,
)
from app.agent_runtime.tools.definition import ToolBinding
from app.bootstrap.agent_assembly import AssemblyError
from app.bootstrap.default_tool_assembly import _RunRegistry, build_default_run_tools
from app.bootstrap.loop_assembly import bind_loop_dispatcher
from app.bootstrap.tool_catalog import TOOLS
from app.bootstrap.tool_definitions import BUSINESS_TOOL_DEFINITIONS
from app.demo_data.synthetic_fab import SyntheticFabProvider
from app.tools.enterprise_data.contracts import EnterpriseDataError
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)


def _plan(tool: str = "get_equipment_health") -> ExecutionPlan:
    return ExecutionPlan(
        "default-tools",
        "1",
        "test",
        "ready",
        "",
        "",
        None,
        None,
        AnalysisScopeContract("equipment", (), (), ()),
        (),
        (),
        PlanBudget(1, 1, 1, 10, {tool: 1}, 1, 1),
        (),
        (),
    )


class DefaultToolAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = SimpleNamespace(
            tenant_id="demo", user_id="analyst", roles=("analyst",)
        )
        self.settings = SimpleNamespace(
            enterprise_default_tenant_id="demo",
            manufacturing_database_path=None,
            equipment_database_path=None,
            quality_database_path=None,
            knowledge_database_path=None,
            enterprise_data_provider="synthetic",
            factory_search_backend="sqlite",
            enterprise_mock_seed="test-seed",
            enterprise_mock_virtual_lots=10,
            enterprise_mock_cursor_secret="test-secret",
        )

    def _build(self, **kwargs):
        plan = _plan(kwargs.pop("tool", "get_equipment_health"))
        return build_default_run_tools(
            settings=self.settings,
            principal=self.principal,
            plan=plan,
            guard=ToolLoopGuard(plan),
            run_id="default-tools",
            usable_knowledge_result=lambda _q, _r: True,
            **kwargs,
        )

    def test_catalog_is_21_native_tools_plus_protocol_without_sql(self) -> None:
        self.assertEqual(len(BUSINESS_TOOL_DEFINITIONS), 21)
        self.assertEqual(len(TOOLS), 22)
        self.assertEqual(TOOLS[-1]["function"]["name"], "submit_analysis")
        self.assertNotIn(
            "query_manufacturing_data", {item["function"]["name"] for item in TOOLS}
        )

    def test_unpatched_default_resolves_native_bindings(self) -> None:
        run = self._build()
        for definition in BUSINESS_TOOL_DEFINITIONS:
            with self.subTest(definition=definition.name):
                self.assertIsInstance(
                    run.dispatcher.registry.resolve(definition.name), ToolBinding
                )

    def test_runs_isolate_catalog_mutations_and_binding_dependencies(self) -> None:
        first, second = self._build(), self._build()
        first_registry, second_registry = (
            first.dispatcher.registry,
            second.dispatcher.registry,
        )
        first_registry.model_tools[0]["function"]["parameters"]["properties"].clear()
        self.assertEqual(
            second_registry.model_tools, self._build().dispatcher.registry.model_tools
        )
        for definition in BUSINESS_TOOL_DEFINITIONS:
            with self.subTest(tool=definition.name):
                self.assertIsNot(
                    first_registry.resolve(definition.name),
                    second_registry.resolve(definition.name),
                )
                self.assertIsNot(
                    first_registry.resolve(definition.name).dependencies,
                    second_registry.resolve(definition.name).dependencies,
                )

    def test_immutable_catalog_snapshot_matches_lazy_public_view(self) -> None:
        run = self._build()
        registry = run.dispatcher.registry

        snapshot = registry.try_model_tools_json(
            run.dispatcher.allowed_tools, run.dispatcher.legacy_tools
        )

        self.assertIsNotNone(snapshot)
        catalog = registry.model_tools
        self.assertEqual(json.loads(snapshot), catalog)
        self.assertIs(catalog, registry.model_tools)

    def test_knowledge_snapshot_matches_its_lazy_public_view(self) -> None:
        plan = replace(
            _plan("search_knowledge"),
            route_intent="general_knowledge",
            status="unsupported",
        )
        run = build_default_run_tools(
            settings=self.settings,
            principal=self.principal,
            plan=plan,
            guard=ToolLoopGuard(plan),
            run_id="knowledge-snapshot",
            usable_knowledge_result=lambda _q, _r: True,
        )
        registry = run.dispatcher.registry

        snapshot = registry.try_model_tools_json(
            run.dispatcher.allowed_tools, run.dispatcher.legacy_tools
        )

        self.assertEqual(json.loads(snapshot), registry.model_tools)
        self.assertEqual(len(registry.model_tools), 1)

    def test_preinstall_public_catalog_identity_disables_snapshot(self) -> None:
        source = self._build().dispatcher.registry
        bindings = [
            source.resolve(definition.name) for definition in BUSINESS_TOOL_DEFINITIONS
        ]
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                registry = _RunRegistry({}, {})
                public_catalog = registry.model_tools
                if replacement:
                    public_catalog = []
                    registry.model_tools = public_catalog

                registry.install_declared_bindings(bindings)

                self.assertIs(registry.model_tools, public_catalog)
                self.assertEqual(len(public_catalog), 21)
                self.assertIsNone(
                    registry.try_model_tools_json(
                        frozenset(definition.name for definition in BUSINESS_TOOL_DEFINITIONS),
                        frozenset(),
                    )
                )

    def test_public_catalog_edits_disable_snapshot_for_later_bindings(self) -> None:
        run = self._build()
        registry = run.dispatcher.registry
        registry.model_tools[0]["function"]["description"] = "public mutation"

        rebound = bind_loop_dispatcher(
            run.loop.plan,
            run.loop.guard,
            run.context,
            run.dispatcher,
            run.dispatcher.result_policy,
        )

        self.assertEqual(
            json.loads(rebound.tools_json)[0]["function"]["description"],
            "public mutation",
        )

    def test_public_catalog_replacement_and_live_patches_use_current_bindings(self) -> None:
        run = self._build()
        registry = run.dispatcher.registry
        replacement = registry.model_tools[:1]
        registry.model_tools = replacement

        rebound = bind_loop_dispatcher(
            run.loop.plan,
            run.loop.guard,
            run.context,
            run.dispatcher,
            run.dispatcher.result_policy,
        )
        self.assertEqual(json.loads(rebound.tools_json), replacement)

        patched_run = self._build()
        patched_registry = patched_run.dispatcher.registry
        handlers = patched_registry._handlers
        original = handlers["get_equipment_health"]
        try:
            handlers["get_equipment_health"] = lambda **_kwargs: []
            self.assertIsNotNone(
                patched_registry.try_model_tools_json(
                    patched_run.dispatcher.allowed_tools,
                    patched_run.dispatcher.legacy_tools,
                )
            )
            rebound_patch = bind_loop_dispatcher(
                patched_run.loop.plan,
                patched_run.loop.guard,
                patched_run.context,
                patched_run.dispatcher,
                patched_run.dispatcher.result_policy,
            )
            self.assertEqual(len(json.loads(rebound_patch.tools_json)), 21)
            self.assertIsNone(
                patched_registry.try_model_tools_json(
                    patched_run.dispatcher.allowed_tools, frozenset()
                )
            )
            patched_run.dispatcher.legacy_tools = frozenset()
            unauthorized = bind_loop_dispatcher(
                patched_run.loop.plan,
                patched_run.loop.guard,
                patched_run.context,
                patched_run.dispatcher,
                patched_run.dispatcher.result_policy,
            )
            self.assertNotIn(
                "get_equipment_health",
                [item["function"]["name"] for item in json.loads(unauthorized.tools_json)],
            )
            handlers["get_equipment_health"] = None
            with self.assertRaises(AssemblyError):
                bind_loop_dispatcher(
                    patched_run.loop.plan,
                    patched_run.loop.guard,
                    patched_run.context,
                    patched_run.dispatcher,
                    patched_run.dispatcher.result_policy,
                )
        finally:
            handlers["get_equipment_health"] = original

    def test_allowed_subset_uses_the_generic_catalog_filter(self) -> None:
        run = self._build()
        run.dispatcher.allowed_tools = frozenset({"get_equipment_health"})
        run.dispatcher.legacy_tools = frozenset({"get_equipment_health"})

        rebound = bind_loop_dispatcher(
            run.loop.plan,
            run.loop.guard,
            run.context,
            run.dispatcher,
            run.dispatcher.result_policy,
        )

        self.assertEqual(
            [item["function"]["name"] for item in json.loads(rebound.tools_json)],
            ["get_equipment_health"],
        )

    def test_canonical_binding_install_rejects_invalid_sets_atomically(self) -> None:
        source = self._build().dispatcher.registry
        bindings = [
            source.resolve(definition.name) for definition in BUSINESS_TOOL_DEFINITIONS
        ]
        changed = replace(
            bindings[0], definition=replace(bindings[0].definition, version="9.9.9")
        )
        for invalid in (
            bindings[:-1],
            [*bindings, bindings[0]],
            [changed, *bindings[1:]],
        ):
            with self.subTest(size=len(invalid)):
                registry = _RunRegistry({}, {})
                with self.assertRaises(ValueError):
                    registry.install_declared_bindings(invalid)
                self.assertEqual(registry.model_tools, [])
                registry.install_declared_bindings(bindings)
                self.assertEqual(len(registry.model_tools), 21)
                with self.assertRaises(RuntimeError):
                    registry.install_declared_bindings(bindings)

    def test_assembly_does_not_open_sources(self) -> None:
        with (
            patch("sqlite3.connect", side_effect=AssertionError("db opened")),
            patch(
                "app.bootstrap.default_tool_assembly.get_enterprise_provider",
                side_effect=AssertionError("provider resolved"),
            ),
        ):
            self._build()

    def test_general_knowledge_authorizes_only_knowledge_and_never_opens_business_source(
        self,
    ) -> None:
        plan = replace(
            _plan("search_knowledge"),
            route_intent="general_knowledge",
            status="unsupported",
        )
        guard = ToolLoopGuard(plan)
        with (
            patch("sqlite3.connect", side_effect=AssertionError("unrelated database")),
            patch(
                "app.bootstrap.default_tool_assembly.get_enterprise_provider",
                side_effect=AssertionError("unrelated provider"),
            ),
        ):
            run = build_default_run_tools(
                settings=self.settings,
                principal=self.principal,
                plan=plan,
                guard=guard,
                run_id="knowledge-only",
                usable_knowledge_result=lambda _q, _r: True,
            )
            self.assertEqual(
                run.dispatcher.allowed_tools, frozenset({"search_knowledge"})
            )
            self.assertIsInstance(
                run.dispatcher.registry.resolve("search_knowledge"), ToolBinding
            )
            result = asyncio.run(
                run.dispatcher.dispatch(
                    "get_fab_overview",
                    "{}",
                    run.context.for_tool_call("forged"),
                )
            )
        self.assertEqual(result.status, ToolStatus.DENIED)
        self.assertEqual(guard.total_calls, 0)

    def test_sql_is_not_resolvable_even_if_legacy_budget_mentions_it(self) -> None:
        run = self._build(tool="query_manufacturing_data")
        with self.assertRaises(ValueError):
            run.dispatcher.registry.resolve("query_manufacturing_data")

    def test_policy_denies_other_tenant_manufacturing_scope(self) -> None:
        run = self._build()
        decision = run.dispatcher.policy.authorize(
            self.principal, "get_equipment_health", ToolScope("other")
        )
        self.assertFalse(decision.allowed)

    def test_policy_requires_original_analyst_principal(self) -> None:
        run = self._build()
        copied = SimpleNamespace(
            tenant_id="demo", user_id="analyst", roles=("analyst",)
        )
        wrong_role = SimpleNamespace(
            tenant_id="demo", user_id="analyst", roles=("viewer",)
        )
        self.assertFalse(
            run.dispatcher.policy.authorize(
                copied, "get_equipment_health", ToolScope("demo")
            ).allowed
        )
        self.assertFalse(
            run.dispatcher.policy.authorize(
                wrong_role, "get_equipment_health", ToolScope("demo")
            ).allowed
        )

    def test_late_safe_patch_is_compatibility_only_and_cannot_restore_sql(self) -> None:
        run = self._build()
        handlers = run.dispatcher.registry._handlers
        original = handlers["get_equipment_health"]
        calls: list[dict[str, object]] = []
        sql_calls: list[dict[str, object]] = []

        def patched(**kwargs):
            calls.append(kwargs)
            return []

        try:
            handlers["get_equipment_health"] = patched
            handlers["query_manufacturing_data"] = lambda **kwargs: sql_calls.append(
                kwargs
            )
            result = asyncio.run(
                run.dispatcher.dispatch(
                    "get_equipment_health",
                    {},
                    ToolExecutionContext(
                        self.principal, "default-tools", "patched", None
                    ),
                )
            )
            sql = asyncio.run(
                run.dispatcher.dispatch(
                    "query_manufacturing_data",
                    {"sql": "SELECT 1"},
                    ToolExecutionContext(self.principal, "default-tools", "sql", None),
                )
            )
        finally:
            handlers["get_equipment_health"] = original
            handlers.pop("query_manufacturing_data", None)
        self.assertEqual(calls, [{}])
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        self.assertEqual(result.tool_version, "legacy-v1")
        self.assertEqual(sql.status, ToolStatus.DENIED)
        self.assertEqual(sql_calls, [])

    def test_named_binding_reads_only_its_selected_sqlite_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manufacturing = Path(directory) / "manufacturing.db"
            connection = sqlite3.connect(manufacturing)
            connection.execute(
                "CREATE TABLE lots (lot_id TEXT, product TEXT, technology_nm INTEGER, route TEXT, "
                "priority TEXT, start_time TEXT, complete_time TEXT, status TEXT, wafer_count INTEGER, "
                "good_wafers INTEGER, yield_rate REAL, cycle_time_hours REAL, hold_hours REAL)"
            )
            connection.execute(
                "INSERT INTO lots VALUES ('LOT-001', 'P1', 28, 'R', 'normal', '2026-01-01', "
                "'2026-01-02', 'complete', 25, 24, 0.96, 1.0, 0.0)"
            )
            connection.commit()
            connection.close()
            settings = SimpleNamespace(**vars(self.settings))
            settings.manufacturing_database_path = manufacturing
            plan = _plan("get_lot_identity")
            run = build_default_run_tools(
                settings=settings,
                principal=self.principal,
                plan=plan,
                guard=ToolLoopGuard(plan),
                run_id="native-named",
                usable_knowledge_result=lambda _q, _r: True,
            )
            binding = run.dispatcher.registry.resolve("get_lot_identity")
            self.assertIsInstance(binding, ToolBinding)
            value = binding.definition.parse({"lot_id": "LOT-001"})
            result = binding.handler(
                value,
                ToolExecutionContext(
                    self.principal, "native-named", "call", binding.dependencies
                ),
            )
        self.assertEqual(result.data[0]["lot_id"], "LOT-001")
        self.assertEqual(result.sources[0].source_kind.value, "sqlite")

    def test_viewer_principal_is_denied_before_any_source_is_opened(self) -> None:
        viewer = SimpleNamespace(tenant_id="demo", user_id="viewer", roles=("viewer",))
        plan = _plan()
        with (
            patch("sqlite3.connect", side_effect=AssertionError("source opened")),
            patch(
                "app.bootstrap.default_tool_assembly.get_enterprise_provider",
                side_effect=AssertionError("provider resolved"),
            ),
        ):
            run = build_default_run_tools(
                settings=self.settings,
                principal=viewer,
                plan=plan,
                guard=ToolLoopGuard(plan),
                run_id="viewer",
                usable_knowledge_result=lambda _q, _r: True,
            )
            result = asyncio.run(
                run.dispatcher.dispatch(
                    "get_equipment_health",
                    {},
                    ToolExecutionContext(viewer, "viewer", "viewer-call", None),
                )
            )
        self.assertEqual(result.status, ToolStatus.DENIED)
        self.assertEqual(result.error.code, "POLICY_DENIED")

    def test_enterprise_uses_one_injected_snapshot_and_synthetic_metadata(self) -> None:
        captured: dict[str, object] = {}

        def provider_factory(*, settings, today):
            captured.update(settings=settings, today=today)
            return SyntheticFabProvider(settings=settings, today=today)

        with patch(
            "app.bootstrap.default_tool_assembly.get_enterprise_provider",
            side_effect=provider_factory,
        ):
            run = self._build()
            binding = run.dispatcher.registry.resolve("get_enterprise_data_manifest")
            self.assertIsInstance(binding, ToolBinding)
            result = binding.handler(
                binding.definition.parse({}),
                ToolExecutionContext(
                    self.principal, "default-tools", "enterprise", binding.dependencies
                ),
            )
        self.assertIs(captured["settings"], self.settings)
        self.assertEqual(captured["today"], binding.dependencies.window.as_of)
        self.assertEqual(result.sources[0].source_kind, ToolSourceKind.FAKE)
        self.assertTrue(result.data["simulated"])

    def test_untyped_enterprise_provider_fails_before_fetch_without_fallback(
        self,
    ) -> None:
        calls: list[str] = []

        class UntypedProvider:
            provider_id = "company"

            def manifest(self, principal):
                calls.append("manifest")
                return {}

        settings = SimpleNamespace(**vars(self.settings))
        settings.enterprise_data_provider = "company"
        with patch(
            "app.bootstrap.default_tool_assembly.get_enterprise_provider",
            return_value=UntypedProvider(),
        ):
            plan = _plan()
            run = build_default_run_tools(
                settings=settings,
                principal=self.principal,
                plan=plan,
                guard=ToolLoopGuard(plan),
                run_id="untyped-enterprise",
                usable_knowledge_result=lambda _q, _r: True,
            )
            binding = run.dispatcher.registry.resolve("get_enterprise_data_manifest")
            with self.assertRaises(EnterpriseDataError):
                binding.handler(
                    binding.definition.parse({}),
                    ToolExecutionContext(
                        self.principal,
                        "untyped-enterprise",
                        "untyped",
                        binding.dependencies,
                    ),
                )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
