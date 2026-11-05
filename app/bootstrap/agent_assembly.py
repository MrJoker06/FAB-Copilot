"""Explicit assembly for the small typed agent application pilot."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from inspect import isawaitable, iscoroutinefunction
from typing import TYPE_CHECKING, Any

from ..agent_runtime.application import AgentRun
from ..agent_runtime.definition import AgentDefinition, ComponentReference
from ..agent_runtime.execution.runtime_contracts import ModelRequest, RuntimeContext
from ..agent_runtime.execution.runtime_ports import EventSink, ModelResponsePort
from ..agent_runtime.tools.definition import ToolBinding
from ..agent_runtime.tools.dispatch_contracts import (
    ToolBudget,
    ToolPolicy,
    ToolResultPolicy,
)
from ..agent_runtime.tools.dispatcher import ToolDispatcher
from ..agent_runtime.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from .skill_assembly import (
        SkillAssemblyConfiguration,
        SkillBinding,
        SkillExecutionRequest,
    )

_PUBLIC_ERROR = "Agent assembly is invalid."


class AssemblyError(ValueError):
    """A deliberately non-diagnostic public assembly failure."""

    def __init__(self) -> None:
        super().__init__(_PUBLIC_ERROR)


def _valid_capabilities(value: object) -> bool:
    return isinstance(value, frozenset) and all(
        isinstance(item, str) and item.strip() and len(item) <= 128 and "*" not in item
        for item in value
    )


def _async_callable(value: object) -> bool:
    return iscoroutinefunction(value) or iscoroutinefunction(type(value).__call__)


def _valid_port(value: object, method: str, *, asynchronous: bool = False) -> bool:
    candidate = getattr(value, method, None)
    return callable(candidate) and _async_callable(candidate) is asynchronous


def _valid_factory(value: object) -> bool:
    return callable(value) and not _async_callable(value)


def _tools_json(
    bindings: tuple[ToolBinding[Any, Any, Any], ...], capabilities: frozenset[str]
) -> tuple[ToolRegistry, str]:
    registry = ToolRegistry()
    for binding in bindings:
        registry.register_native(binding)
    selected = [
        item
        for item in registry.model_tools
        if isinstance(item, dict)
        and isinstance(item.get("function"), dict)
        and item["function"].get("name") in capabilities
    ]
    tools_json = json.dumps(
        selected, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    ModelRequest(call_id="assembly-validation", messages=(), tools_json=tools_json)
    return registry, tools_json


@dataclass(frozen=True, slots=True)
class AgentApplication:
    definition: AgentDefinition
    model: ModelResponsePort
    events: EventSink
    bindings: tuple[ToolBinding[Any, Any, Any], ...]
    policy: ToolPolicy
    budget_factory: Callable[[], ToolBudget]
    server_capabilities: frozenset[str]
    model_policy_ref: ComponentReference
    policy_ref: ComponentReference
    effective_capabilities: frozenset[str]
    skill_binding: SkillBinding | None = None

    def new_run(
        self, context: RuntimeContext, *, result_policy: ToolResultPolicy | None = None
    ) -> AgentRun:
        if not isinstance(context, RuntimeContext):
            raise AssemblyError()
        try:
            skill_context = ()
            skill_metadata = ()
            if self.skill_binding is not None:
                self.skill_binding.revalidate()
                skill_context = self.skill_binding.model_context
                skill_metadata = self.skill_binding.metadata
            registry, tools_json = _tools_json(
                self.bindings, self.effective_capabilities
            )
            budget = self.budget_factory()
            if isawaitable(budget):
                closer = getattr(budget, "close", None)
                if callable(closer):
                    closer()
                raise TypeError
            if not _valid_port(budget, "claim") or not _valid_port(
                budget, "record_result"
            ):
                raise TypeError
            dispatcher = ToolDispatcher(
                run_id=context.run_id,
                registry=registry,
                policy=self.policy,
                budget=budget,
                allowed_tools=self.effective_capabilities,
                result_policy=result_policy,
            )
        except AssemblyError:
            raise
        except Exception:  # noqa: BLE001 - assembly errors are deliberately opaque
            raise AssemblyError() from None
        return AgentRun(
            self.definition,
            context,
            self.model,
            dispatcher,
            self.events,
            tools_json,
            skill_context,
            skill_metadata,
        )


def assemble_agent(
    definition: AgentDefinition,
    *,
    model: ModelResponsePort,
    events: EventSink,
    bindings: tuple[ToolBinding[Any, Any, Any], ...],
    policy: ToolPolicy,
    budget_factory: Callable[[], ToolBudget],
    server_capabilities: frozenset[str],
    model_policy_ref: ComponentReference,
    policy_ref: ComponentReference,
    skill_configuration: SkillAssemblyConfiguration | None = None,
    skill_request: SkillExecutionRequest | None = None,
) -> AgentApplication:
    try:
        skill_binding = None
        if (
            not isinstance(definition, AgentDefinition)
            or (
                definition.skill_refs
                and (skill_configuration is None or skill_request is None)
            )
            or (
                not definition.skill_refs
                and (skill_configuration is not None or skill_request is not None)
            )
            or not _valid_port(model, "complete", asynchronous=True)
            or not _valid_port(events, "emit", asynchronous=True)
            or not isinstance(bindings, tuple)
            or any(not isinstance(binding, ToolBinding) for binding in bindings)
            or not _valid_port(policy, "authorize")
            or not _valid_factory(budget_factory)
            or not isinstance(model_policy_ref, ComponentReference)
            or not isinstance(policy_ref, ComponentReference)
            or model_policy_ref != definition.model_policy
            or policy_ref != definition.default_policy
            or not _valid_capabilities(server_capabilities)
        ):
            raise AssemblyError()
        names = [binding.definition.name for binding in bindings]
        if len(set(names)) != len(names) or set(names) != definition.allowed_tools:
            raise AssemblyError()
        references = {
            reference.component_id: reference for reference in definition.tools
        }
        if any(
            not binding.definition.read_only
            or binding.definition.version != references[binding.definition.name].version
            for binding in bindings
        ):
            raise AssemblyError()
        effective_capabilities = definition.allowed_tools & server_capabilities
        if definition.skill_refs:
            # Keep this import opt-in: historical source slices deliberately do
            # not copy the new Skill composition modules.
            from .skill_assembly import (
                SkillAssemblyConfiguration,
                SkillAssemblyError,
                SkillExecutionRequest,
                resolve_skill_binding,
            )

            if not isinstance(
                skill_configuration, SkillAssemblyConfiguration
            ) or not isinstance(skill_request, SkillExecutionRequest):
                raise AssemblyError()
            try:
                skill_binding = resolve_skill_binding(
                    definition,
                    skill_configuration,
                    skill_request,
                    bindings,
                    server_capabilities,
                )
            except SkillAssemblyError:
                raise AssemblyError() from None
            effective_capabilities &= frozenset(
                step.tool for step in skill_binding.plan.steps
            )
        _tools_json(bindings, effective_capabilities)
    except AssemblyError:
        raise
    except Exception:  # noqa: BLE001 - assembly errors are deliberately opaque
        raise AssemblyError() from None
    return AgentApplication(
        definition,
        model,
        events,
        bindings,
        policy,
        budget_factory,
        server_capabilities,
        model_policy_ref,
        policy_ref,
        effective_capabilities,
        skill_binding,
    )
