from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.agent_runtime.service as agent
from app.agent_runtime.dependencies import CoordinatorDependencies
from app.bootstrap.legacy_agent_assembly import build_legacy_coordinator_dependencies


class LegacyAgentAssemblyTests(unittest.TestCase):
    def test_service_snapshot_preserves_dependency_group_bindings(self):
        deps = agent._coordinator_dependencies()

        self.assertIsInstance(deps, CoordinatorDependencies)
        self.assertIs(deps.preparation.prepare_agent_run, agent.prepare_agent_run)
        self.assertIs(deps.availability.execute_ready_plan, agent._execute_ready_plan)
        self.assertIs(deps.model.context_system_message, agent.context_system_message)
        self.assertIs(deps.ready.async_client, agent.httpx.AsyncClient)
        self.assertIs(deps.loop.tools, agent.TOOLS)
        self.assertIs(deps.loop.execute_registered_tool, agent._execute_registered_tool)
        self.assertIs(deps.loop.stream_completion, agent._stream_completion)

    def test_service_uses_live_patches_without_mutating_prior_snapshot(self):
        previous = agent._coordinator_dependencies()
        tools = agent.TOOLS
        patched_tools = [*tools]

        def execute(*_args, **_kwargs):
            return {"patched": "execute"}

        async def stream(*_args, **_kwargs):
            yield {"patched": "stream"}

        class AsyncClient:
            pass

        class Clock:
            @staticmethod
            def perf_counter():
                return 123.0

        with (
            patch.object(agent, "_execute_registered_tool", new=execute),
            patch.object(agent, "_stream_completion", new=stream),
            patch.object(agent, "TOOLS", new=patched_tools),
            patch.object(agent, "time", new=Clock),
            patch.object(agent.httpx, "AsyncClient", new=AsyncClient),
        ):
            current = agent._coordinator_dependencies()

        self.assertIs(current.loop.execute_registered_tool, execute)
        self.assertIs(current.loop.stream_completion, stream)
        self.assertIs(current.preparation.perf_counter, Clock.perf_counter)
        self.assertIs(current.ready.async_client, AsyncClient)
        self.assertIs(current.loop.tools, patched_tools)
        self.assertIs(
            previous.loop.execute_registered_tool, agent._execute_registered_tool
        )
        self.assertIs(previous.loop.stream_completion, agent._stream_completion)
        self.assertIs(previous.loop.tools, tools)

    def test_helper_constructs_from_the_given_namespace_aliases(self):
        captured: dict[str, dict] = {}

        def factory(name):
            def build(**kwargs):
                captured[name] = kwargs
                return SimpleNamespace(factory=name, **kwargs)

            return build

        namespace = dict(agent.__dict__)
        namespace.update(
            {
                "CoordinatorDependencies": factory("coordinator"),
                "CoordinatorPreparationDependencies": factory("preparation"),
                "CoordinatorAvailabilityDependencies": factory("availability"),
                "CoordinatorModelDependencies": factory("model"),
                "CoordinatorReadyDependencies": factory("ready"),
                "CoordinatorLoopDependencies": factory("loop"),
            }
        )
        assembled = build_legacy_coordinator_dependencies(namespace)

        self.assertEqual(assembled.factory, "coordinator")
        self.assertEqual(assembled.preparation.factory, "preparation")
        self.assertIs(captured["coordinator"]["loop"], assembled.loop)
        self.assertIs(captured["loop"]["tools"], namespace["TOOLS"])
        self.assertIs(captured["ready"]["async_client"], namespace["httpx"].AsyncClient)
        self.assertIs(
            captured["preparation"]["agent_preparation_dependencies"],
            namespace["_agent_preparation_dependencies"],
        )

    def test_bootstrap_source_has_no_concrete_runtime_or_settings_imports(self):
        source = inspect.getsource(build_legacy_coordinator_dependencies)
        module_source = inspect.getsource(
            __import__(build_legacy_coordinator_dependencies.__module__, fromlist=["*"])
        )

        self.assertNotIn("app.core.settings", module_source)
        self.assertNotIn("app.agent_runtime.service", module_source)
        self.assertNotIn("import httpx", module_source)
        self.assertIn('namespace["httpx"].AsyncClient', source)
