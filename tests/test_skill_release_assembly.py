"""Released Skill content is pinned while Dispatcher authority stays live."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
from app.agent_runtime.tools.dispatch_contracts import PolicyDecision
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import AssemblyError, assemble_agent
from app.bootstrap.litho_cpk_demo import _QUESTION, _TOOLS, _bindings, _Principal
from app.bootstrap.litho_cpk_workflow import LithoCpkWorkflow
from app.bootstrap.loop_assembly import bind_loop_run
from app.bootstrap.ready_assembly import bind_ready_run
from app.bootstrap.skill_assembly import (
    SkillAssemblyConfiguration,
    SkillAssemblyError,
    SkillExecutionRequest,
    _inventory,
)
from app.evidence.validator import EvidenceObservation
from app.intent_runtime.routing import route_question
from app.knowledge.decision import usable_result
from app.skills.catalog import SkillReference
from app.skills.contracts import DependencyInventory, SkillPackageError
from app.skills.releases import SkillReleaseStore


@dataclass
class _Model:
    plan: object
    requests: list[ModelRequest]

    async def complete(
        self, request: ModelRequest, _context: RuntimeContext
    ) -> ModelResponse:
        self.requests.append(request)
        if request.call_id == "released-first":
            return ModelResponse(
                tool_calls=tuple(
                    ModelToolCall(str(index), step.tool, json.dumps(step.parameters))
                    for index, step in enumerate(self.plan.steps, 1)
                )
            )
        return ModelResponse(content="released fixture complete")


class _Events:
    async def emit(self, _event: object) -> None:
        return None


class _LivePolicy:
    """A mutable test switch proves every existing dispatcher checks policy."""

    def __init__(self) -> None:
        self.enabled = True
        self._base = DemoToolPolicy(
            frozenset(_TOOLS), frozenset({"analyst"}), tenant_id="demo"
        )

    def authorize(self, principal: object, name: str, scope: object) -> PolicyDecision:
        if not self.enabled:
            return PolicyDecision(False, "REVOKED", "This tool is not authorized.")
        return self._base.authorize(principal, name, scope)  # type: ignore[arg-type]


@dataclass
class _Fixture:
    app: object
    plan: object
    model: _Model
    holder: dict[str, ToolLoopGuard]
    adapters: tuple[object, ...]
    policy: _LivePolicy


class SkillReleaseAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = date(2026, 10, 31)
        self.route = route_question(_QUESTION, self.as_of)
        self.workflow = LithoCpkWorkflow()
        self.plan, _ = self.workflow.build(_QUESTION, self.route)
        self.source = (
            Path(__file__).parents[1]
            / "app"
            / "skills"
            / "lithography"
            / "cpk_diagnostic"
        )

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    def _package(self, parent: Path, version: str, marker: str) -> Path:
        target = parent / version
        shutil.copytree(self.source, target)
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = version
        self._write_text(manifest_path, json.dumps(manifest))
        self._write_text(
            target / "SKILL.md",
            f"# Released Cpk {marker}\n\n{marker} instructions only.\n",
        )
        self._write_text(
            target / "references" / "cpk_context.md", f"released {marker} reference\n"
        )
        return target

    def _definition(self, version: str) -> AgentDefinition:
        return AgentDefinition(
            "released-litho",
            "1.0.0",
            "analyst",
            "Run a released Cpk skill.",
            tuple(ComponentReference(name, "1.0.0") for name in _TOOLS),
            ComponentReference("model", "1.0.0"),
            ComponentReference("policy", "1.0.0"),
            (ComponentReference("litho-cpk-diagnostic", version),),
        )

    def _assemble(self, store: SkillReleaseStore, version: str) -> _Fixture:
        bindings, adapters = _bindings(self.plan, self.as_of, _Principal())
        definition = self._definition(version)
        model = _Model(self.plan, [])
        holder: dict[str, ToolLoopGuard] = {}

        def budget_factory() -> LoopGuardToolBudget:
            guard = ToolLoopGuard(app.skill_binding.plan)
            holder["guard"] = guard
            return LoopGuardToolBudget(guard)

        policy = _LivePolicy()
        app = assemble_agent(
            definition,
            model=model,
            events=_Events(),
            bindings=bindings,
            policy=policy,
            budget_factory=budget_factory,
            server_capabilities=frozenset(_TOOLS),
            model_policy_ref=definition.model_policy,
            policy_ref=definition.default_policy,
            skill_configuration=SkillAssemblyConfiguration((), (self.workflow,), store),
            skill_request=SkillExecutionRequest(_QUESTION, self.route, "loop"),
        )
        return _Fixture(app, self.plan, model, holder, adapters, policy)

    def _run(
        self, fixture: _Fixture, mode: str, existing_run: object | None = None
    ) -> tuple[object, tuple[object, ...]]:
        if existing_run is None:
            projector = ReadyResultPolicy(
                knowledge_tools=frozenset({"search_knowledge"}),
                usable_knowledge_result=usable_result,
            )
            context = RuntimeContext(
                _Principal(),
                f"released-{mode}-{id(fixture)}",
                ToolExecutionLimits(20, 100, time.monotonic() + 5),
            )
            run = fixture.app.new_run(context, result_policy=projector)
            guard = fixture.holder["guard"]
        else:
            run = existing_run
            context = run.context
            guard = fixture.holder["guard"]
            projector = run.dispatcher.result_policy
        binding = (
            bind_ready_run(fixture.app.skill_binding.plan, guard, run, projector)
            if mode == "ready"
            else bind_loop_run(fixture.app.skill_binding.plan, guard, run, projector)
        )

        async def execute() -> tuple[object, tuple[object, ...]]:
            async def notify(_progress: object, _event: dict[str, object]) -> None:
                return None

            if mode == "ready":
                outcome = await execute_dispatched_ready_plan(
                    fixture.app.skill_binding.plan,
                    guard,
                    context.run_id,
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
            else:
                first = await run.model_stage(
                    call_id="released-first",
                    messages=(ModelMessage("user", _QUESTION),),
                )
                outcome = await execute_dispatched_loop_round(
                    fixture.app.skill_binding.plan,
                    guard,
                    context.run_id,
                    1,
                    classify_loop_response(first.value),
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )
                await run.model_stage(
                    call_id="released-second",
                    messages=(
                        ModelMessage("user", _QUESTION),
                        ModelMessage(
                            "assistant", "", tool_calls=first.value.tool_calls
                        ),
                        *(
                            ModelMessage(
                                "tool",
                                item["content"],
                                tool_call_id=item["tool_call_id"],
                            )
                            for item in outcome.tool_messages
                        ),
                    ),
                )
            observations = tuple(
                EvidenceObservation(**item) for item in outcome.observation_payloads
            )
            return outcome, observations

        return asyncio.run(execute())

    def test_versions_pin_real_context_and_execute_after_author_files_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            v1 = self._package(root, "1.0.0", "one")
            v2 = self._package(root, "2.0.0", "two")
            store = SkillReleaseStore()
            bindings, _ = _bindings(self.plan, self.as_of, _Principal())
            inventory = _inventory(bindings, (self.workflow,))
            store.publish(v1, inventory)
            store.activate(SkillReference("litho-cpk-diagnostic", "1.0.0"))
            old = self._assemble(store, "1.0.0")
            old_run = old.app.new_run(
                RuntimeContext(_Principal(), "old-context", ToolExecutionLimits()),
                result_policy=ReadyResultPolicy(
                    frozenset({"search_knowledge"}), usable_result
                ),
            )
            asyncio.run(
                old_run.model_stage(
                    call_id="old-model", messages=(ModelMessage("user", _QUESTION),)
                )
            )
            self.assertIn("one instructions", old.model.requests[0].messages[1].content)
            self.assertEqual(dict(old_run.skill_metadata)["skill_version"], "1.0.0")

            store.publish(v2, inventory)
            store.activate(SkillReference("litho-cpk-diagnostic", "2.0.0"))
            shutil.rmtree(v1)
            self._write_text(v2 / "SKILL.md", "author changed\n")
            frozen = old.app.skill_binding.loader.expand(
                old.app.skill_binding.snapshot, ("references/cpk_context.md",)
            )
            self.assertEqual(
                frozen.loaded_resources[-1].text, "released one reference\n"
            )
            asyncio.run(
                old_run.model_stage(
                    call_id="old-model-after-release",
                    messages=(ModelMessage("user", _QUESTION),),
                )
            )
            self.assertIn(
                "one instructions", old.model.requests[-1].messages[1].content
            )

            new = self._assemble(store, "2.0.0")
            new_run = new.app.new_run(
                RuntimeContext(_Principal(), "new-context", ToolExecutionLimits()),
                result_policy=ReadyResultPolicy(
                    frozenset({"search_knowledge"}), usable_result
                ),
            )
            asyncio.run(
                new_run.model_stage(
                    call_id="new-model", messages=(ModelMessage("user", _QUESTION),)
                )
            )
            self.assertIn("two instructions", new.model.requests[0].messages[1].content)
            self.assertIn("one instructions", old.model.requests[0].messages[1].content)

            old_outcome, old_observations = self._run(old, "ready", old_run)
            new_outcome, new_observations = self._run(new, "loop", new_run)
            self.assertTrue(all(item["status"] == "ok" for item in old_outcome.trace))
            self.assertTrue(all(item["status"] == "ok" for item in new_outcome.trace))
            self.assertEqual(
                old.app.skill_binding.workflow.evidence_validator(
                    self.plan,
                    old.app.skill_binding.selection.selected_playbook,
                    list(old_observations),
                ).coverage["required_covered"],
                3,
            )
            self.assertEqual(
                new.app.skill_binding.workflow.evidence_validator(
                    self.plan,
                    new.app.skill_binding.selection.selected_playbook,
                    list(new_observations),
                ).coverage["required_covered"],
                3,
            )
            store.rollback(SkillReference("litho-cpk-diagnostic", "1.0.0"))
            rolled = self._assemble(
                store,
                store.active_reference("litho-cpk-diagnostic").version,
            )
            rolled_run = rolled.app.new_run(
                RuntimeContext(_Principal(), "rolled-context", ToolExecutionLimits())
            )
            asyncio.run(
                rolled_run.model_stage(
                    call_id="rolled-model", messages=(ModelMessage("user", _QUESTION),)
                )
            )
            asyncio.run(
                new_run.model_stage(
                    call_id="v2-after-rollback",
                    messages=(ModelMessage("user", _QUESTION),),
                )
            )
            self.assertIn(
                "one instructions", rolled.model.requests[-1].messages[1].content
            )
            self.assertIn(
                "two instructions", new.model.requests[-1].messages[1].content
            )

    def test_disable_blocks_new_runs_but_live_policy_still_controls_old_runs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            v1 = self._package(Path(raw), "1.0.0", "one")
            store = SkillReleaseStore()
            bindings, _ = _bindings(self.plan, self.as_of, _Principal())
            inventory = _inventory(bindings, (self.workflow,))
            reference = SkillReference("litho-cpk-diagnostic", "1.0.0")
            store.publish(v1, inventory)
            store.activate(reference)
            fixture = self._assemble(store, "1.0.0")
            projector = ReadyResultPolicy(
                frozenset({"search_knowledge"}), usable_result
            )
            pinned_run = fixture.app.new_run(
                RuntimeContext(
                    _Principal(), "pinned-before-disable", ToolExecutionLimits()
                ),
                result_policy=projector,
            )
            pinned_guard = fixture.holder["guard"]
            live_run = fixture.app.new_run(
                RuntimeContext(_Principal(), "live-policy", ToolExecutionLimits()),
                result_policy=projector,
            )
            fixture.policy.enabled = False
            guard = fixture.holder["guard"]
            binding = bind_ready_run(
                fixture.app.skill_binding.plan, guard, live_run, projector
            )

            async def blocked() -> object:
                async def notify(_progress: object, _event: dict[str, object]) -> None:
                    return None

                return await execute_dispatched_ready_plan(
                    fixture.app.skill_binding.plan,
                    guard,
                    live_run.context.run_id,
                    None,
                    binding=binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )

            blocked_outcome = asyncio.run(blocked())
            self.assertTrue(
                all(item["status"] == "blocked" for item in blocked_outcome.trace)
            )
            self.assertEqual(sum(len(adapter.calls) for adapter in fixture.adapters), 0)
            fixture.policy.enabled = True
            budget_run = fixture.app.new_run(
                RuntimeContext(
                    _Principal(), "budget-before-disable", ToolExecutionLimits(0, 100)
                ),
                result_policy=projector,
            )
            budget_guard = fixture.holder["guard"]
            budget_binding = bind_ready_run(
                fixture.app.skill_binding.plan, budget_guard, budget_run, projector
            )

            async def budget_blocked() -> object:
                async def notify(_progress: object, _event: dict[str, object]) -> None:
                    return None

                return await execute_dispatched_ready_plan(
                    fixture.app.skill_binding.plan,
                    budget_guard,
                    budget_run.context.run_id,
                    None,
                    binding=budget_binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )

            budget_outcome = asyncio.run(budget_blocked())
            self.assertTrue(
                all(item["status"] == "blocked" for item in budget_outcome.trace)
            )
            self.assertEqual(sum(len(adapter.calls) for adapter in fixture.adapters), 0)
            store.disable(reference)
            with self.assertRaises(AssemblyError):
                fixture.app.new_run(
                    RuntimeContext(_Principal(), "disabled-new", ToolExecutionLimits())
                )
            fixture.policy.enabled = True
            pinned_binding = bind_ready_run(
                fixture.app.skill_binding.plan, pinned_guard, pinned_run, projector
            )

            async def permitted_after_disable() -> object:
                async def notify(_progress: object, _event: dict[str, object]) -> None:
                    return None

                return await execute_dispatched_ready_plan(
                    fixture.app.skill_binding.plan,
                    pinned_guard,
                    pinned_run.context.run_id,
                    None,
                    binding=pinned_binding,
                    notify=notify,
                    emit_event=lambda *_args, **_kwargs: None,
                )

            permitted = asyncio.run(permitted_after_disable())
            self.assertTrue(all(item["status"] == "ok" for item in permitted.trace))

    def test_release_configuration_requires_actual_bindings_and_no_file_root(
        self,
    ) -> None:
        store = SkillReleaseStore()
        with self.assertRaises(SkillAssemblyError):
            SkillAssemblyConfiguration((), (self.workflow,))
        with self.assertRaises(SkillAssemblyError):
            SkillAssemblyConfiguration((self.source,), (self.workflow,), store)
        with tempfile.TemporaryDirectory() as raw:
            v1 = self._package(Path(raw), "1.0.0", "one")
            forged = self._package(Path(raw), "2.0.0", "forged")
            wrong = DependencyInventory(
                {name: "9.9.9" for name in _TOOLS},
                {self.workflow.workflow_id: self.workflow.version},
                {
                    self.workflow.evidence_policy_id: self.workflow.evidence_policy_version
                },
            )
            store.publish(
                v1,
                _inventory(
                    _bindings(self.plan, self.as_of, _Principal())[0], (self.workflow,)
                ),
            )
            reference = SkillReference("litho-cpk-diagnostic", "1.0.0")
            with self.assertRaises(SkillPackageError):
                store.loader(reference, wrong)
            manifest_path = forged / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for tool in manifest["tools"]:
                tool["version"] = "==9.9.9"
            self._write_text(manifest_path, json.dumps(manifest))
            store.publish(forged, wrong)
            forged_reference = SkillReference("litho-cpk-diagnostic", "2.0.0")
            store.activate(forged_reference)
            with self.assertRaises(AssemblyError):
                self._assemble(store, forged_reference.version)


if __name__ == "__main__":
    unittest.main()
