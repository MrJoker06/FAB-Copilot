"""Canonical executable Agent tool registry."""

from __future__ import annotations

from typing import Any, Callable

from ...manufacturing.enterprise_data import (
    enterprise_data_manifest,
    enterprise_fab_summary,
    query_enterprise_data,
)
from ...knowledge.rag import search_agent_knowledge
from ...manufacturing.reports import (
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


TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
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


__all__ = ["TOOL_HANDLERS", "search_agent_knowledge"]
