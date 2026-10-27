"""Leaf operations for one model-requested tool call."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .tool_registry import LegacyBindingAdapter


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
            raise ValueError("工具参数必须是 JSON 对象")  # noqa: TRY004
    except Exception as exc:  # noqa: BLE001
        return ParsedToolArguments({"_raw": str(raw)[:1000]}, exc)
    return ParsedToolArguments(arguments)


def execute_registered_tool(
    name: str, arguments: dict[str, Any], registry: Mapping[str, Callable[..., Any]]
) -> Any:
    """Resolve and invoke one handler while retaining result identity."""
    return LegacyBindingAdapter(name, registry).invoke(arguments)


__all__ = ["ParsedToolArguments", "execute_registered_tool", "parse_tool_arguments"]
