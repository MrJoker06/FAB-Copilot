"""Compatibility view over the bootstrap-installed legacy bindings."""

# ruff: noqa: F401

from __future__ import annotations

from ...bootstrap.tool_bindings import (
    defect_pareto,
    enterprise_data_manifest,
    enterprise_fab_summary,
    equipment_health,
    equipment_productivity,
    fab_overview,
    process_capability,
    process_pass_rate,
    query_enterprise_data,
    recent_excursions,
    safe_select,
    search_agent_knowledge,
    sensor_summary,
    yield_trend,
)
from .tool_registry import DEFAULT_TOOL_REGISTRY

TOOL_HANDLERS = DEFAULT_TOOL_REGISTRY.legacy_handlers


__all__ = ["TOOL_HANDLERS", "search_agent_knowledge"]
