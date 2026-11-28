"""Per-run assembly of the bounded default business-tool capability set."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..agent_runtime.execution.loop_dispatch import LoopDispatchBinding
from ..agent_runtime.execution.ready_dispatch import ReadyDispatchBinding
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import RuntimeContext
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import (
    ToolExecutionLimits,
    ToolScope,
    ToolSourceKind,
)
from ..agent_runtime.tools.definition import ToolBinding
from ..agent_runtime.tools.dispatch_contracts import PolicyDecision
from ..agent_runtime.tools.dispatcher import ToolDispatcher
from ..agent_runtime.tools.projection import model_function_view
from ..agent_runtime.tools.tool_registry import (
    LegacyBindingAdapter,
    LegacyToolDefinition,
    ToolRegistry,
)
from app.tools.knowledge_search.binding import create_knowledge_search_binding
from app.bootstrap.enterprise_data_assembly import get_enterprise_provider
from app.tools.enterprise_data.binding import (
    create_enterprise_manifest_binding,
    create_enterprise_sample_binding,
    create_enterprise_summary_binding,
)
from app.tools.enterprise_data.contracts import EnterpriseWindow
from app.tools.equipment_health.binding import create_equipment_health_binding
from app.tools.lot_commonality.binding import (
    LOT_COMMONALITY_DEFINITIONS,
    create_lot_commonality_bindings,
)
from app.tools.named_queries.binding import create_named_query_bindings
from app.tools.operational_reports.binding import (
    create_defect_pareto_binding,
    create_equipment_productivity_binding,
    create_recent_excursions_binding,
)
from app.tools.process_diagnostics.binding import (
    create_process_capability_binding,
    create_sensor_summary_binding,
)
from app.tools.production_reports.binding import (
    create_fab_overview_binding,
    create_process_pass_rate_binding,
    create_yield_trend_binding,
)
from ..planning_runtime.contracts import ExecutionPlan
from .loop_assembly import bind_loop_dispatcher
from .ready_assembly import bind_ready_dispatcher
from .tool_definitions import BUSINESS_TOOL_DEFINITIONS

_DECLARED_DEFINITIONS = {
    definition.name: definition for definition in BUSINESS_TOOL_DEFINITIONS
}
_NATIVE_CATALOG_JSON = json.dumps(
    [model_function_view(definition) for definition in BUSINESS_TOOL_DEFINITIONS],
    ensure_ascii=False,
    separators=(",", ":"),
)

_ALL_CAPABILITIES = frozenset(_DECLARED_DEFINITIONS)
_KNOWLEDGE_CAPABILITIES = frozenset({"search_knowledge"})
# Lot commonality is a separate profile: only its route sees these tools, and
# the 21-tool default catalog of every other route stays unchanged.
_LOT_COMMONALITY_CAPABILITIES = frozenset(LOT_COMMONALITY_DEFINITIONS)
_PROFILE_DEFINITIONS = {**_DECLARED_DEFINITIONS, **LOT_COMMONALITY_DEFINITIONS}
_LOT_COMMONALITY_CATALOG_JSON = json.dumps(
    [model_function_view(definition) for definition in LOT_COMMONALITY_DEFINITIONS.values()],
    ensure_ascii=False,
    separators=(",", ":"),
)
_KNOWLEDGE_CATALOG_JSON = json.dumps(
    [
        item
        for item in json.loads(_NATIVE_CATALOG_JSON)
        if item["function"]["name"] == "search_knowledge"
    ],
    ensure_ascii=False,
    separators=(",", ":"),
)

_COMPATIBLE = frozenset(
    (
        "get_enterprise_data_manifest",
        "get_enterprise_fab_summary",
        "query_enterprise_data",
        "get_fab_overview",
        "get_yield_trend",
        "get_process_pass_rate",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_process_capability",
        "get_defect_pareto",
        "get_recent_excursions",
        "get_sensor_summary",
        "search_knowledge",
    )
)
_ENTERPRISE_OR_KNOWLEDGE = frozenset(
    (
        "get_enterprise_data_manifest",
        "get_enterprise_fab_summary",
        "query_enterprise_data",
        "search_knowledge",
    )
)


class _LazyPort:
    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory
        self._value: object | None = None

    def __getattr__(self, name: str) -> object:
        if self._value is None:
            self._value = self._factory()
        return getattr(self._value, name)


class _RunRegistry(ToolRegistry):
    def __init__(
        self,
        handlers: Mapping[str, Callable[..., Any]],
        baseline: Mapping[str, Callable[..., Any]],
    ) -> None:
        self._catalog_json: str | None = None
        self._installed_capabilities: frozenset[str] | None = None
        self._catalog_exposed = False
        super().__init__()
        self._handlers, self._baseline = handlers, baseline

    @property
    def model_tools(self) -> list[dict[str, object]]:
        """Materialize the mutable compatibility view only when it is observed."""
        if self._catalog_json is not None and not self._catalog_exposed:
            self._model_tools = json.loads(self._catalog_json)
        self._catalog_exposed = True
        return self._model_tools

    @model_tools.setter
    def model_tools(self, value: list[dict[str, object]]) -> None:
        initialized = hasattr(self, "_model_tools")
        self._model_tools = value
        if initialized:
            self._catalog_exposed = True

    def install_declared_bindings(self, bindings, capabilities=None) -> None:
        """Install only canonical definitions with a fresh versioned schema snapshot.

        Sources and dependencies remain per-run.  The shared schema is immutable
        JSON; a caller cannot mutate a later run through this registry's catalog.
        """
        if self._native_bindings or self._model_tools or self.legacy_handlers:
            raise RuntimeError("run registry is already initialized")
        capabilities = _ALL_CAPABILITIES if capabilities is None else capabilities
        catalogs = {
            _ALL_CAPABILITIES: _NATIVE_CATALOG_JSON,
            _KNOWLEDGE_CAPABILITIES: _KNOWLEDGE_CATALOG_JSON,
            _LOT_COMMONALITY_CAPABILITIES: _LOT_COMMONALITY_CATALOG_JSON,
        }
        if capabilities not in catalogs:
            raise ValueError("unsupported default capability profile")
        native = {}
        for binding in bindings:
            if not isinstance(binding, ToolBinding):
                raise TypeError("default native binding is invalid")
            name = binding.definition.name
            if name in native or binding.definition is not _PROFILE_DEFINITIONS.get(
                name
            ):
                raise ValueError("default binding must use its declared definition")
            native[name] = binding
        if native.keys() != capabilities:
            raise ValueError("default native binding set is incomplete")
        catalog_json = catalogs[capabilities]
        catalog = json.loads(catalog_json) if self._catalog_exposed else None
        self._native_bindings.update(native)
        self._catalog_json = catalog_json
        self._installed_capabilities = capabilities
        if catalog is None:
            self._model_tools = []
        else:
            self._model_tools.extend(catalog)

    def try_model_tools_json(
        self, allowed_tools: frozenset[str], legacy_tools: frozenset[str]
    ) -> str | None:
        """Return the immutable catalog only while its mutable view is untouched."""
        if (
            self._catalog_exposed
            or self._catalog_json is None
            or allowed_tools != self._installed_capabilities
        ):
            return None
        for definition in BUSINESS_TOOL_DEFINITIONS:
            if definition.name not in allowed_tools:
                continue
            binding = self.resolve(definition.name)
            if isinstance(binding, LegacyBindingAdapter) and definition.name not in legacy_tools:
                return None
        return self._catalog_json

    def resolve(self, name: str):  # type: ignore[override]
        if name in _COMPATIBLE and self._handlers.get(name) is not self._baseline.get(
            name
        ):
            if not callable(self._handlers.get(name)):
                raise ValueError(f"unknown tool: {name}")
            return LegacyBindingAdapter(name, self._handlers)
        return super().resolve(name)

    def legacy_definition(self, name: str) -> LegacyToolDefinition:
        if name not in _COMPATIBLE or self._handlers.get(name) is self._baseline.get(
            name
        ):
            raise ValueError(f"unknown tool: {name}")
        for cell in self.model_tools:
            function = cell.get("function") if isinstance(cell, dict) else None
            if isinstance(function, dict) and function.get("name") == name:
                return LegacyToolDefinition(name, cell)
        raise ValueError(f"unknown tool: {name}")


class _DefaultToolPolicy:
    def __init__(
        self, declared: frozenset[str], principal: object, manufacturing_tenant: str, management=None, skill=None
    ) -> None:
        self.management = management
        self.skill = skill
        self._declared, self._principal, self._manufacturing_tenant = (
            declared,
            principal,
            manufacturing_tenant,
        )

    def authorize(
        self, principal: object, name: str, scope: ToolScope
    ) -> PolicyDecision:
        if (
            name not in self._declared
            or (self.management and not self.management.tool_allowed(name, principal))
            or (self.skill is not None and not self.skill.authorized())
        ):
            return PolicyDecision(
                False, "CAPABILITY_DENIED", "This tool is not authorized."
            )
        if principal is not self._principal or scope.tenant_id != getattr(
            principal, "tenant_id", None
        ):
            return PolicyDecision(
                False, "SCOPE_DENIED", "This scope is not authorized."
            )
        if "analyst" not in getattr(principal, "roles", ()):
            return PolicyDecision(
                False, "ROLE_DENIED", "This principal is not authorized."
            )
        if (
            name not in _ENTERPRISE_OR_KNOWLEDGE
            and scope.tenant_id != self._manufacturing_tenant
        ):
            return PolicyDecision(
                False, "SCOPE_DENIED", "This scope is not authorized."
            )
        return PolicyDecision(True)


@dataclass(frozen=True, slots=True)
class DefaultRunTools:
    ready: ReadyDispatchBinding | None
    loop: LoopDispatchBinding
    context: RuntimeContext
    dispatcher: ToolDispatcher


def build_default_run_tools(
    *,
    settings: object,
    principal: object,
    plan: ExecutionPlan,
    guard: object,
    run_id: str,
    usable_knowledge_result: Callable[[str, dict[str, object]], bool],
    handlers: Mapping[str, Callable[..., Any]] | None = None,
    baseline_handlers: Mapping[str, Callable[..., Any]] | None = None,
    session_id: str | None = None,
    management=None,
    skill=None,
) -> DefaultRunTools:
    """Build native bindings lazily; legacy functions are an explicit live-patch bridge."""
    from ..agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
    from app.tools.knowledge_search.runtime_search import create_runtime_knowledge_port
    from app.tools.enterprise_data.data_source import (
        ProviderEnterpriseToolsAdapter,
    )
    from app.tools.equipment_health.data_source import (
        SQLiteEquipmentHealthAdapter,
    )
    from app.tools.named_queries.data_source import (
        SQLiteNamedQueryAdapter,
    )
    from app.tools.operational_reports.data_source import (
        SQLiteOperationalReportsAdapter,
    )
    from app.tools.process_diagnostics.data_source import (
        SQLiteProcessDiagnosticsAdapter,
    )
    from app.tools.production_reports.data_source import (
        SQLiteProductionReportsAdapter,
    )
    from . import tool_bindings

    live = DEFAULT_TOOL_REGISTRY.legacy_handlers if handlers is None else handlers
    baseline = (
        tool_bindings._LEGACY_BINDINGS
        if baseline_handlers is None
        else baseline_handlers
    )
    registry = _RunRegistry(live, baseline)
    today = datetime.now(timezone.utc).date()
    tenant = getattr(settings, "enterprise_default_tenant_id", principal.tenant_id)
    manufacturing = getattr(settings, "manufacturing_database_path", None)
    equipment = getattr(settings, "equipment_database_path", None)
    quality = getattr(settings, "quality_database_path", None)
    production = _LazyPort(
        lambda: SQLiteProductionReportsAdapter(manufacturing, demo_tenant_id=tenant)
    )
    diagnostics = _LazyPort(
        lambda: SQLiteProcessDiagnosticsAdapter(
            manufacturing, equipment, demo_tenant_id=tenant
        )
    )
    operational = _LazyPort(
        lambda: SQLiteOperationalReportsAdapter(
            manufacturing_path=manufacturing,
            equipment_path=equipment,
            quality_path=quality,
            demo_tenant_id=tenant,
        )
    )
    named = _LazyPort(
        lambda: SQLiteNamedQueryAdapter(
            manufacturing_path=manufacturing,
            equipment_path=equipment,
            quality_path=quality,
            demo_tenant_id=tenant,
        )
    )
    health = _LazyPort(
        lambda: SQLiteEquipmentHealthAdapter(
            manufacturing, equipment, demo_tenant_id=tenant
        )
    )

    def _enterprise_port():
        provider = get_enterprise_provider(settings=settings, today=today)
        configured = getattr(settings, "enterprise_data_provider", "synthetic")
        if configured == "synthetic":
            source_kind = ToolSourceKind.FAKE
        else:
            source_kind = getattr(provider, "tool_source_kind", None)
            if not isinstance(source_kind, ToolSourceKind):
                raise ValueError(
                    "custom enterprise provider must declare tool_source_kind"
                )
        return ProviderEnterpriseToolsAdapter(
            provider,
            demo_tenant_id=principal.tenant_id,
            expected_provider_id=provider.provider_id,
            source_kind=source_kind,
        )

    enterprise = _LazyPort(_enterprise_port)
    knowledge = _LazyPort(
        lambda: create_runtime_knowledge_port(settings=settings, principal=principal)
    )
    if plan.route_intent in {"general_knowledge", "sop_lookup"}:
        declared = _KNOWLEDGE_CAPABILITIES
    elif plan.route_intent == "lot_commonality":
        declared = _LOT_COMMONALITY_CAPABILITIES
    else:
        declared = _ALL_CAPABILITIES
    if declared == _KNOWLEDGE_CAPABILITIES:
        bindings = (
            create_knowledge_search_binding(knowledge, default_tenant_id=tenant),
        )
    elif declared == _LOT_COMMONALITY_CAPABILITIES:
        from .lot_commonality_assembly import lot_commonality_service

        # Analyses created in a chat belong to its Session and are revoked with it.
        bindings = create_lot_commonality_bindings(
            lot_commonality_service(), session_id=session_id
        )
    else:
        bindings = (
            create_equipment_health_binding(health, today=lambda: today),
            create_process_capability_binding(diagnostics, today=lambda: today),
            create_sensor_summary_binding(diagnostics, today=lambda: today),
            create_fab_overview_binding(production, today=lambda: today),
            create_yield_trend_binding(production, today=lambda: today),
            create_process_pass_rate_binding(production, today=lambda: today),
            create_equipment_productivity_binding(operational, today=lambda: today),
            create_defect_pareto_binding(operational, today=lambda: today),
            create_recent_excursions_binding(operational, today=lambda: today),
            create_enterprise_manifest_binding(
                enterprise, window=EnterpriseWindow(as_of=today)
            ),
            create_enterprise_summary_binding(
                enterprise, window=EnterpriseWindow(as_of=today)
            ),
            create_enterprise_sample_binding(
                enterprise, window=EnterpriseWindow(as_of=today)
            ),
            create_knowledge_search_binding(knowledge, default_tenant_id=tenant),
            *create_named_query_bindings(named, as_of=today),
        )
    registry.install_declared_bindings(bindings, declared)
    if {binding.definition.name for binding in bindings} != declared:
        raise RuntimeError("default native bindings do not match declared capabilities")
    context = RuntimeContext(
        principal,
        run_id,
        ToolExecutionLimits(plan.budget.max_tool_calls, plan.budget.max_rows_per_call),
    )
    projector = ReadyResultPolicy(
        frozenset({"search_knowledge"}), usable_knowledge_result
    )
    allowed = declared
    route_tools = set(declared)
    if management is not None:
        rules = management.policies()
        allowed = frozenset(name for name in declared if management.tool_allowed(name, principal, rules))
        for name, provider in management.plugin_tools().items():
            if plan.route_intent not in provider.routes:
                continue
            route_tools.add(name)
            if management.tool_allowed(name, principal, rules):
                binding = provider.bind(settings, principal)
                if not isinstance(binding, ToolBinding) or binding.definition is not provider.definition:
                    raise ValueError("plugin binding differs from installed definition")
                registry.register_native(binding)
                allowed = allowed | {name}
    if any(step.tool not in route_tools for step in plan.steps):
        raise ValueError("plan contains an undeclared default capability")
    if skill is not None:
        skill.require_current()
        if not skill.tools <= allowed:
            from .duty_chat_skill import DutySkillError

            raise DutySkillError("SKILL_DEPENDENCY_UNAVAILABLE", "所选技能的运行依赖不可用。", 409)
        skill.bind(plan, registry)
        allowed = skill.tools
    dispatcher = ToolDispatcher(
        run_id=run_id,
        registry=registry,
        policy=_DefaultToolPolicy(allowed, principal, tenant, management, skill),
        budget=LoopGuardToolBudget(guard),
        allowed_tools=allowed,
        legacy_tools=_COMPATIBLE & allowed,
        result_policy=projector,
    )
    ready = (
        bind_ready_dispatcher(plan, guard, context, dispatcher, projector)
        if plan.status == "ready"
        else None
    )
    return DefaultRunTools(
        ready,
        bind_loop_dispatcher(plan, guard, context, dispatcher, projector),
        context,
        dispatcher,
    )


__all__ = ["DefaultRunTools", "build_default_run_tools"]
