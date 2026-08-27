"""Compatibility facade for the Agent tool catalog and registry."""

from __future__ import annotations

from .agent_runtime.tools.catalog import DATE_PROPERTIES, TOOLS, _schema
from .agent_runtime.tools.registry import TOOL_HANDLERS, search_agent_knowledge

__all__ = [
    "_schema",
    "DATE_PROPERTIES",
    "TOOLS",
    "TOOL_HANDLERS",
    "search_agent_knowledge",
]
