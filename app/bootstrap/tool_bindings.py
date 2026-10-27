"""Concrete legacy tool binding assembly for the default registry."""

from __future__ import annotations

from ..agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
from ..knowledge.rag import search_agent_knowledge
from ..manufacturing.enterprise_data import (
    enterprise_data_manifest,
    enterprise_fab_summary,
    query_enterprise_data,
)
from ..manufacturing.reports import (
    defect_pareto,
    equipment_health,
    equipment_productivity,
    fab_overview,
    process_capability,
    process_pass_rate,
    recent_excursions,
    safe_select,
    sensor_summary,
    yield_trend,
)
from . import tool_catalog

if tool_catalog.TOOLS is not DEFAULT_TOOL_REGISTRY.model_tools:
    raise RuntimeError("legacy tool catalog must expose the registry model-tools list")

_LEGACY_BINDINGS = {
    "get_enterprise_data_manifest": enterprise_data_manifest,
    "get_enterprise_fab_summary": enterprise_fab_summary,
    "query_enterprise_data": query_enterprise_data,
    "get_fab_overview": fab_overview,
    "get_yield_trend": yield_trend,
    "get_process_pass_rate": process_pass_rate,
    "get_equipment_health": equipment_health,
    "get_equipment_productivity": equipment_productivity,
    "get_process_capability": process_capability,
    "get_defect_pareto": defect_pareto,
    "get_recent_excursions": recent_excursions,
    "get_sensor_summary": sensor_summary,
    "search_knowledge": search_agent_knowledge,
    "query_manufacturing_data": safe_select,
}

DEFAULT_TOOL_REGISTRY.initialize_legacy_handlers(_LEGACY_BINDINGS)


__all__ = [
    "defect_pareto",
    "enterprise_data_manifest",
    "enterprise_fab_summary",
    "equipment_health",
    "equipment_productivity",
    "fab_overview",
    "process_capability",
    "process_pass_rate",
    "query_enterprise_data",
    "recent_excursions",
    "safe_select",
    "search_agent_knowledge",
    "sensor_summary",
    "yield_trend",
]
