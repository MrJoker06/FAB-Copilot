"""Protocol views derived from one ``ToolDefinition``.

Every outward description of a tool is produced here from the definition, so
model function catalogs and MCP listings cannot drift from the parser, schema
and description the runtime actually enforces.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .contracts import ToolResult, ToolStatus
from .definition import ToolDefinition

# MCP requires object-shaped structured content; list results are wrapped.
_ROWS_KEY = "rows"


def model_function_view(definition: ToolDefinition[Any]) -> dict[str, object]:
    """Chat-completions ``function`` tool entry; byte-compatible with the legacy view."""
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": deepcopy(definition.json_schema()),
        },
    }


def _wrapped_output_schema(schema: dict[str, object]) -> dict[str, object]:
    if schema.get("type") == "object":
        return schema
    return {
        "type": "object",
        "properties": {_ROWS_KEY: schema},
        "required": [_ROWS_KEY],
        "additionalProperties": False,
    }


def mcp_tool_view(definition: ToolDefinition[Any]) -> dict[str, object]:
    """MCP ``tools/list`` entry for one definition."""
    view: dict[str, object] = {"name": definition.name}
    if definition.title is not None:
        view["title"] = definition.title
    view["description"] = definition.description
    view["inputSchema"] = deepcopy(definition.json_schema())
    if definition.output_schema is not None:
        view["outputSchema"] = _wrapped_output_schema(
            deepcopy(dict(definition.output_schema))
        )
    view["annotations"] = {"readOnlyHint": definition.read_only}
    return view


def mcp_structured_content(data: object) -> dict[str, object]:
    return data if isinstance(data, dict) else {_ROWS_KEY: data}


def mcp_call_result(result: ToolResult[Any]) -> dict[str, object]:
    """MCP ``tools/call`` result; failures become ``isError`` results, not exceptions."""
    if not isinstance(result, ToolResult):
        raise TypeError("result must be a ToolResult")
    if result.status is ToolStatus.SUCCEEDED:
        structured = mcp_structured_content(result.data)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        structured, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            ],
            "structuredContent": structured,
            "isError": False,
        }
    if result.error is not None:
        message = f"{result.error.code}: {result.error.public_message}"
    else:
        message = f"tool call {result.status.value}"
    return {"content": [{"type": "text", "text": message}], "isError": True}
