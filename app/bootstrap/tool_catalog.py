"""Application-owned legacy model schemas installed into the default registry."""

from __future__ import annotations

from ..agent_runtime.tools.projection import model_function_view
from ..agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
from ..evidence.answer_synthesizer import SUBMIT_ANALYSIS_TOOL
from app.core.manufacturing_terms import ANALYSIS_SCOPES, MANUFACTURING_STEPS
from .tool_definitions import BUSINESS_TOOL_DEFINITIONS


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


DATE_PROPERTIES = {
    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD，默认最近90天"},
    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认今天"},
}


TOOLS = [model_function_view(definition) for definition in BUSINESS_TOOL_DEFINITIONS] + [
    SUBMIT_ANALYSIS_TOOL
]

DEFAULT_TOOL_REGISTRY.initialize_legacy_catalog(
    TOOLS, protocol_names={"submit_analysis"}
)
TOOLS = DEFAULT_TOOL_REGISTRY.model_tools

__all__ = [
    "ANALYSIS_SCOPES",
    "DATE_PROPERTIES",
    "MANUFACTURING_STEPS",
    "SUBMIT_ANALYSIS_TOOL",
    "TOOLS",
    "_schema",
]
