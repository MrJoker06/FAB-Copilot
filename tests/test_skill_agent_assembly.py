"""Skill composition remains opt-in at the Agent assembly boundary."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.runtime_contracts import ModelResponse, RuntimeContext
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionLimits
from app.agent_runtime.tools.definition import ToolBinding
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import AssemblyError, assemble_agent
from app.bootstrap.litho_cpk_demo import _QUESTION, _TOOLS, _bindings, _Principal
from app.bootstrap.litho_cpk_workflow import LithoCpkWorkflow
from app.bootstrap.skill_assembly import (
    SkillAssemblyConfiguration,
    SkillAssemblyError,
    SkillExecutionRequest,
)
from app.intent_runtime.routing import route_question


class _Model:
    async def complete(self, _request: object, _context: object) -> ModelResponse:
        return ModelResponse(content="unused")


class _Events:
    async def emit(self, _event: object) -> None:
        return None


class SkillAgentAssemblyTests(unittest.TestCase):
    def _enabled_inputs(self, *, server_capabilities: frozenset[str] | None = None):
        as_of = date(2026, 10, 31)
        route = route_question(_QUESTION, as_of)
        workflow = LithoCpkWorkflow()
        plan, _ = workflow.build(_QUESTION, route)
        definition = AgentDefinition(
            "skill-test",
            "1.0.0",
            "analyst",
            "controlled test",
            tuple(ComponentReference(name, "1.0.0") for name in _TOOLS),
            ComponentReference("model", "1.0.0"),
            ComponentReference("policy", "1.0.0"),
            (ComponentReference("litho-cpk-diagnostic", "1.0.0"),),
        )
        root = (
            Path(__file__).parents[1]
            / "app"
            / "skills"
            / "lithography"
            / "cpk_diagnostic"
        )
        return (
            definition,
            _bindings(plan, as_of, _Principal())[0],
            SkillAssemblyConfiguration((root,), (workflow,)),
            SkillExecutionRequest(_QUESTION, route, "ready"),
            server_capabilities or frozenset(_TOOLS),
        )

    @staticmethod
    def _policy() -> DemoToolPolicy:
        return DemoToolPolicy(
            frozenset(_TOOLS), frozenset({"analyst"}), tenant_id="demo"
        )

    @staticmethod
    def _copied_package(destination: Path) -> Path:
        source = (
            Path(__file__).parents[1]
            / "app"
            / "skills"
            / "lithography"
            / "cpk_diagnostic"
        )
        for relative in (
            "manifest.json",
            "SKILL.md",
            "references/cpk_context.md",
            "scenarios/acceptance.json",
        ):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        return destination

    def _assemble(self, definition, bindings, configuration, request, capabilities):
        return assemble_agent(
            definition,
            model=_Model(),
            events=_Events(),
            bindings=bindings,
            policy=self._policy(),
            budget_factory=lambda: object(),
            server_capabilities=capabilities,
            model_policy_ref=definition.model_policy,
            policy_ref=definition.default_policy,
            skill_configuration=configuration,
            skill_request=request,
        )

    def test_manifest_version_remains_authoritative_over_matching_definition(
        self,
    ) -> None:
        definition, bindings, configuration, request, capabilities = (
            self._enabled_inputs()
        )
        original = bindings[0]
        changed_definition = replace(original.definition, version="9.9.9")
        changed_bindings = (
            ToolBinding(
                changed_definition,
                original.handler,
                original.dependencies,
                original.prepare,
            ),
            *bindings[1:],
        )
        changed_tools = (
            ComponentReference(original.definition.name, "9.9.9"),
            *definition.tools[1:],
        )
        changed_agent = replace(definition, tools=changed_tools)
        with self.assertRaises(AssemblyError):
            self._assemble(
                changed_agent,
                changed_bindings,
                configuration,
                request,
                capabilities,
            )

    def test_copied_manifest_unavailable_or_unknown_refs_fail_before_fetch(
        self,
    ) -> None:
        definition, bindings, _, request, capabilities = self._enabled_inputs()
        plan, _ = LithoCpkWorkflow().build(_QUESTION, request.route)
        bindings, adapters = _bindings(plan, date(2026, 10, 31), _Principal())
        for field, value in (
            ("workflow", {"component_id": "unknown-workflow", "version": "2.0.0"}),
            ("evidence_policy", {"component_id": "unknown-policy", "version": "1.3.0"}),
            ("status", "disabled"),
            ("skill_ref", "9.9.9"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = self._copied_package(Path(directory))
                manifest_path = root / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if field != "skill_ref":
                    manifest[field] = value
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                candidate = definition
                if field == "skill_ref":
                    candidate = replace(
                        definition,
                        skill_refs=(ComponentReference("litho-cpk-diagnostic", value),),
                    )
                with self.assertRaises(AssemblyError):
                    self._assemble(
                        candidate,
                        bindings,
                        SkillAssemblyConfiguration((root,), (LithoCpkWorkflow(),)),
                        request,
                        capabilities,
                    )
                self.assertEqual(sum(len(item.calls) for item in adapters), 0)

    def test_new_run_revalidates_a_disabled_copied_manifest_before_budget(self) -> None:
        definition, bindings, _, request, capabilities = self._enabled_inputs()
        budget_calls = 0

        def budget_factory() -> object:
            nonlocal budget_calls
            budget_calls += 1
            return object()

        with tempfile.TemporaryDirectory() as directory:
            root = self._copied_package(Path(directory))
            app = assemble_agent(
                definition,
                model=_Model(),
                events=_Events(),
                bindings=bindings,
                policy=self._policy(),
                budget_factory=budget_factory,
                server_capabilities=capabilities,
                model_policy_ref=definition.model_policy,
                policy_ref=definition.default_policy,
                skill_configuration=SkillAssemblyConfiguration(
                    (root,), (LithoCpkWorkflow(),)
                ),
                skill_request=request,
            )
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "disabled"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(AssemblyError):
                app.new_run(
                    RuntimeContext(_Principal(), "revalidate", ToolExecutionLimits())
                )
        self.assertEqual(budget_calls, 0)

    def test_enabled_assembly_checks_real_manifest_and_server_capability(self) -> None:
        definition, bindings, configuration, request, capabilities = (
            self._enabled_inputs()
        )
        with self.assertRaises(AssemblyError):
            assemble_agent(
                definition,
                model=_Model(),
                events=_Events(),
                bindings=bindings,
                policy=DemoToolPolicy(
                    frozenset(_TOOLS), frozenset({"analyst"}), tenant_id="demo"
                ),
                budget_factory=lambda: object(),
                server_capabilities=capabilities - {"search_knowledge"},
                model_policy_ref=definition.model_policy,
                policy_ref=definition.default_policy,
                skill_configuration=configuration,
                skill_request=request,
            )

    def test_enabled_assembly_creates_independent_run_registries_and_budgets(
        self,
    ) -> None:
        definition, bindings, configuration, request, capabilities = (
            self._enabled_inputs()
        )
        app = assemble_agent(
            definition,
            model=_Model(),
            events=_Events(),
            bindings=bindings,
            policy=DemoToolPolicy(
                frozenset(_TOOLS), frozenset({"analyst"}), tenant_id="demo"
            ),
            budget_factory=lambda: LoopGuardToolBudget(
                ToolLoopGuard(LithoCpkWorkflow().build(_QUESTION, request.route)[0])
            ),
            server_capabilities=capabilities,
            model_policy_ref=definition.model_policy,
            policy_ref=definition.default_policy,
            skill_configuration=configuration,
            skill_request=request,
        )
        first = app.new_run(
            RuntimeContext(_Principal(), "skill-run-1", ToolExecutionLimits())
        )
        second = app.new_run(
            RuntimeContext(_Principal(), "skill-run-2", ToolExecutionLimits())
        )
        self.assertIsNot(first.dispatcher.registry, second.dispatcher.registry)
        self.assertIsNot(first.dispatcher.budget, second.dispatcher.budget)
        self.assertEqual(app.skill_binding.plan.playbook_id, "PB-CAPABILITY-001")

    def test_missing_confirmed_time_range_is_rejected_before_assembly(self) -> None:
        _, _, _, request, _ = self._enabled_inputs()
        with self.assertRaises(SkillAssemblyError):
            SkillExecutionRequest(
                request.question, replace(request.route, time_range=None), request.mode
            )

    def test_enabled_assembly_rejects_undeclared_resource_before_a_run(self) -> None:
        definition, bindings, configuration, request, capabilities = (
            self._enabled_inputs()
        )
        bad_request = SkillExecutionRequest(
            request.question, request.route, request.mode, ("not-declared.md",)
        )
        with self.assertRaises(AssemblyError):
            assemble_agent(
                definition,
                model=_Model(),
                events=_Events(),
                bindings=bindings,
                policy=DemoToolPolicy(
                    frozenset(_TOOLS), frozenset({"analyst"}), tenant_id="demo"
                ),
                budget_factory=lambda: object(),
                server_capabilities=capabilities,
                model_policy_ref=definition.model_policy,
                policy_ref=definition.default_policy,
                skill_configuration=configuration,
                skill_request=bad_request,
            )

    def test_skill_reference_requires_explicit_configuration_and_request(self) -> None:
        definition = AgentDefinition(
            "skill-test",
            "1.0.0",
            "analyst",
            "controlled test",
            (),
            ComponentReference("model", "1.0.0"),
            ComponentReference("policy", "1.0.0"),
            (ComponentReference("litho-cpk-diagnostic", "1.0.0"),),
        )
        with self.assertRaises(AssemblyError):
            assemble_agent(
                definition,
                model=_Model(),
                events=_Events(),
                bindings=(),
                policy=DemoToolPolicy(
                    frozenset(), frozenset({"analyst"}), tenant_id="demo"
                ),
                budget_factory=lambda: object(),
                server_capabilities=frozenset(),
                model_policy_ref=definition.model_policy,
                policy_ref=definition.default_policy,
            )

    def test_no_skill_definition_rejects_skill_only_arguments(self) -> None:
        definition = AgentDefinition(
            "plain-test",
            "1.0.0",
            "analyst",
            "plain test",
            (),
            ComponentReference("model", "1.0.0"),
            ComponentReference("policy", "1.0.0"),
        )
        with self.assertRaises(AssemblyError):
            assemble_agent(
                definition,
                model=_Model(),
                events=_Events(),
                bindings=(),
                policy=DemoToolPolicy(
                    frozenset(), frozenset({"analyst"}), tenant_id="demo"
                ),
                budget_factory=lambda: object(),
                server_capabilities=frozenset(),
                model_policy_ref=definition.model_policy,
                policy_ref=definition.default_policy,
                skill_configuration=object(),
                skill_request=object(),
            )


if __name__ == "__main__":
    unittest.main()
