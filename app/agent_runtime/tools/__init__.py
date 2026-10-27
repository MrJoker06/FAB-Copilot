"""Stable Agent tool catalog, registry, and leaf executor.

Legacy exports stay lazy so importing the package alone does not import its
settings- and data-bound catalog/registry implementations.
"""

# ruff: noqa: RUF022

__all__ = [
    "DATE_PROPERTIES",
    "ParsedToolArguments",
    "TOOL_HANDLERS",
    "TOOLS",
    "_schema",
    "execute_registered_tool",
    "parse_tool_arguments",
    "search_agent_knowledge",
]

_EXPORT_MODULES = {
    "DATE_PROPERTIES": ".catalog",
    "TOOLS": ".catalog",
    "_schema": ".catalog",
    "ParsedToolArguments": ".executor",
    "execute_registered_tool": ".executor",
    "parse_tool_arguments": ".executor",
    "TOOL_HANDLERS": ".registry",
    "search_agent_knowledge": ".registry",
}


def __getattr__(name: str):
    """Resolve canonical legacy objects once, preserving their live identity."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _EXPORT_MODULES[name] == ".catalog":
        from . import catalog

        value = getattr(catalog, name)
    elif _EXPORT_MODULES[name] == ".executor":
        from . import executor

        value = getattr(executor, name)
    else:
        from . import registry

        value = getattr(registry, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
