"""Leaf operations for one model-requested tool call."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class ParsedToolArguments:
    """Parsed arguments and a retained parsing error, if any."""

    arguments: dict[str, Any]
    error: Exception | None = None


def parse_tool_arguments(raw_arguments: Any) -> ParsedToolArguments:
    """Parse one model argument payload using the legacy fallback semantics."""
    raw = raw_arguments or "{}"
    try:
        arguments = json.loads(raw)
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是 JSON 对象")
    except Exception as exc:
        return ParsedToolArguments({"_raw": str(raw)[:1000]}, exc)
    return ParsedToolArguments(arguments)


def execute_registered_tool(
    name: str, arguments: dict[str, Any], registry: Mapping[str, Callable[..., Any]]
) -> Any:
    """Resolve and invoke one handler while retaining result identity."""
    handler = registry.get(name)
    if handler is None:
        raise ValueError(f"未知工具: {name}")
    return handler(**arguments)


__all__ = ["ParsedToolArguments", "execute_registered_tool", "parse_tool_arguments"]
