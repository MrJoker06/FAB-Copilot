"""The native business-tool contract exposed by the default composition."""

from __future__ import annotations

from ..knowledge.search_tool.binding import KNOWLEDGE_SEARCH_DEFINITION
from ..manufacturing.enterprise_tools.binding import (
    ENTERPRISE_MANIFEST_DEFINITION,
    ENTERPRISE_SAMPLE_DEFINITION,
    ENTERPRISE_SUMMARY_DEFINITION,
)
from app.tools.equipment_health.binding import EQUIPMENT_HEALTH_DEFINITION
from ..manufacturing.named_queries.binding import NAMED_QUERY_DEFINITIONS
from app.tools.operational_reports.binding import (
    DEFECT_PARETO_DEFINITION,
    EQUIPMENT_PRODUCTIVITY_DEFINITION,
    RECENT_EXCURSIONS_DEFINITION,
)
from app.tools.process_diagnostics.binding import (
    PROCESS_CAPABILITY_DEFINITION,
    SENSOR_SUMMARY_DEFINITION,
)
from app.tools.production_reports.binding import (
    FAB_OVERVIEW_DEFINITION,
    PROCESS_PASS_RATE_DEFINITION,
    YIELD_TREND_DEFINITION,
)

DEFAULT_CAPABILITY_VERSION = "2.0.0"

BUSINESS_TOOL_DEFINITIONS = (
    EQUIPMENT_HEALTH_DEFINITION,
    PROCESS_CAPABILITY_DEFINITION,
    SENSOR_SUMMARY_DEFINITION,
    FAB_OVERVIEW_DEFINITION,
    YIELD_TREND_DEFINITION,
    PROCESS_PASS_RATE_DEFINITION,
    EQUIPMENT_PRODUCTIVITY_DEFINITION,
    DEFECT_PARETO_DEFINITION,
    RECENT_EXCURSIONS_DEFINITION,
    ENTERPRISE_MANIFEST_DEFINITION,
    ENTERPRISE_SUMMARY_DEFINITION,
    ENTERPRISE_SAMPLE_DEFINITION,
    KNOWLEDGE_SEARCH_DEFINITION,
    *(NAMED_QUERY_DEFINITIONS[name] for name in NAMED_QUERY_DEFINITIONS),
)

if len({definition.name for definition in BUSINESS_TOOL_DEFINITIONS}) != 21:
    raise RuntimeError("default business tool definitions must be unique and complete")

__all__ = ["BUSINESS_TOOL_DEFINITIONS", "DEFAULT_CAPABILITY_VERSION"]
