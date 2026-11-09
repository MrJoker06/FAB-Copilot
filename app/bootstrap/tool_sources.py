"""Explicit source composition for the native business-tool families.

This module deliberately has no settings, environment or database discovery.
Callers select the consumer-owned ports and receive the existing canonical
bindings.  It is intended for isolated validation and gradual source migration;
the default application assembly remains its own compatibility composition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..agent_runtime.tools.definition import ToolBinding
from ..knowledge.search_tool.binding import create_knowledge_search_binding
from ..knowledge.search_tool.contracts import KnowledgeSearchPort
from ..manufacturing.enterprise_tools.binding import (
    create_enterprise_manifest_binding,
    create_enterprise_sample_binding,
    create_enterprise_summary_binding,
)
from ..manufacturing.enterprise_tools.contracts import (
    EnterpriseDataPort,
    EnterpriseWindow,
)
from ..manufacturing.equipment_health.binding import create_equipment_health_binding
from ..manufacturing.equipment_health.contracts import EquipmentHealthPort
from ..manufacturing.equipment_health.summary import (
    create_equipment_health_summary_binding,
)
from ..manufacturing.named_queries.binding import create_named_query_bindings
from ..manufacturing.named_queries.contracts import NamedQueryPort
from ..manufacturing.operational_reports.binding import (
    create_defect_pareto_binding,
    create_equipment_productivity_binding,
    create_recent_excursions_binding,
)
from ..manufacturing.operational_reports.contracts import OperationalReportsPort
from ..manufacturing.process_diagnostics.binding import (
    create_process_capability_binding,
    create_sensor_summary_binding,
)
from ..manufacturing.process_diagnostics.contracts import ProcessDiagnosticsPort
from ..manufacturing.production_reports.binding import (
    create_fab_overview_binding,
    create_process_pass_rate_binding,
    create_yield_trend_binding,
)
from ..manufacturing.production_reports.contracts import ProductionReportsPort


@dataclass(frozen=True, slots=True)
class ToolSources:
    """Optional, explicit consumer ports; omitted families are never discovered."""

    equipment_health: EquipmentHealthPort | None = None
    process_diagnostics: ProcessDiagnosticsPort | None = None
    production_reports: ProductionReportsPort | None = None
    operational_reports: OperationalReportsPort | None = None
    enterprise_data: EnterpriseDataPort | None = None
    knowledge_search: KnowledgeSearchPort | None = None
    named_queries: NamedQueryPort | None = None


def create_tool_bindings(
    sources: ToolSources,
    *,
    as_of: date,
    default_tenant_id: str,
    include_equipment_health_summary: bool = False,
) -> tuple[ToolBinding, ...]:
    """Create canonical bindings without opening a source or selecting a fallback."""
    if (
        not isinstance(sources, ToolSources)
        or not isinstance(as_of, date)
        or isinstance(as_of, datetime)
    ):
        raise TypeError("sources and as_of must be explicit")
    if not isinstance(default_tenant_id, str) or not default_tenant_id.strip():
        raise ValueError("default_tenant_id must be non-empty")
    if not isinstance(include_equipment_health_summary, bool):
        raise TypeError("include_equipment_health_summary must be bool")
    bindings: tuple[ToolBinding, ...] = ()
    if sources.equipment_health is not None:
        bindings += (
            create_equipment_health_binding(
                sources.equipment_health, today=lambda: as_of
            ),
        )
    if sources.process_diagnostics is not None:
        bindings += (
            create_process_capability_binding(
                sources.process_diagnostics, today=lambda: as_of
            ),
            create_sensor_summary_binding(
                sources.process_diagnostics, today=lambda: as_of
            ),
        )
    if sources.production_reports is not None:
        bindings += (
            create_fab_overview_binding(
                sources.production_reports, today=lambda: as_of
            ),
            create_yield_trend_binding(sources.production_reports, today=lambda: as_of),
            create_process_pass_rate_binding(
                sources.production_reports, today=lambda: as_of
            ),
        )
    if sources.operational_reports is not None:
        bindings += (
            create_equipment_productivity_binding(
                sources.operational_reports, today=lambda: as_of
            ),
            create_defect_pareto_binding(
                sources.operational_reports, today=lambda: as_of
            ),
            create_recent_excursions_binding(
                sources.operational_reports, today=lambda: as_of
            ),
        )
    if sources.enterprise_data is not None:
        window = EnterpriseWindow(as_of)
        bindings += (
            create_enterprise_manifest_binding(sources.enterprise_data, window=window),
            create_enterprise_summary_binding(sources.enterprise_data, window=window),
            create_enterprise_sample_binding(sources.enterprise_data, window=window),
        )
    if sources.knowledge_search is not None:
        bindings += (
            create_knowledge_search_binding(
                sources.knowledge_search, default_tenant_id=default_tenant_id
            ),
        )
    if sources.named_queries is not None:
        bindings += create_named_query_bindings(sources.named_queries, as_of=as_of)
    if include_equipment_health_summary and sources.equipment_health is not None:
        bindings += (
            create_equipment_health_summary_binding(
                sources.equipment_health, today=lambda: as_of
            ),
        )
    elif include_equipment_health_summary:
        raise ValueError(
            "equipment-health summary requires an explicit equipment source"
        )
    if len({binding.definition.name for binding in bindings}) != len(bindings):
        raise RuntimeError("tool source composition contains duplicate names")
    return bindings


__all__ = ["ToolSources", "create_tool_bindings"]
