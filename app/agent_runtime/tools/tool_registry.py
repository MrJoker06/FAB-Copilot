"""Dependency-free registry for legacy and typed Agent tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .definition import ToolBinding, ToolDefinition


@dataclass(frozen=True, slots=True)
class LegacyToolDefinition:
    """A live legacy kwargs contract; it deliberately does not claim validation."""

    name: str
    schema: Mapping[str, object]
    version: str = "legacy-v1"
    mode: str = "legacy_kwargs"


class LegacyBindingAdapter:
    """Resolve a legacy handler from its live mapping for every invocation."""

    def __init__(self, name: str, handlers: Mapping[str, Callable[..., Any]]) -> None:
        self.name = name
        self._handlers = handlers

    def invoke(self, arguments: Mapping[str, Any]) -> Any:
        handler = self._handlers.get(self.name)
        if handler is None:
            raise ValueError(f"未知工具: {self.name}")
        return handler(**arguments)

    def __call__(self, **arguments: Any) -> Any:
        return self.invoke(arguments)


class ToolRegistry:
    """One registry with explicit legacy kwargs and typed-native binding modes."""

    def __init__(self) -> None:
        self.model_tools: list[dict[str, object]] = []
        self.legacy_handlers: dict[str, Callable[..., Any]] = {}
        self._protocol_names: set[str] = set()
        self._native_bindings: dict[str, ToolBinding[Any, Any, Any]] = {}
        self._catalog_initialized = False
        self._legacy_handlers_initialized = False

    @staticmethod
    def _tool_name(item: object) -> str | None:
        if not isinstance(item, dict) or item.get("type") != "function":
            return None
        function = item.get("function")
        if not isinstance(function, dict):
            return None
        name = function.get("name")
        return name if isinstance(name, str) and name.strip() else None

    @classmethod
    def _valid_catalog_cell(cls, item: object) -> bool:
        if cls._tool_name(item) is None or not isinstance(item, dict):
            return False
        function = item["function"]
        return (
            isinstance(function, dict)
            and isinstance(function.get("description"), str)
            and isinstance(function.get("parameters"), dict)
        )

    def _catalog_names(self) -> set[str]:
        return {
            name
            for item in self.model_tools
            if (name := self._tool_name(item)) is not None
        }

    def initialize_legacy_catalog(
        self,
        model_tools: list[dict[str, object]],
        *,
        protocol_names: set[str] | None = None,
    ) -> None:
        """Atomically install the legacy schema cells without copying them."""
        if self._catalog_initialized:
            raise RuntimeError("legacy tool catalog is already initialized")
        if self.model_tools or self._native_bindings or self.legacy_handlers:
            raise RuntimeError(
                "legacy tool catalog must be initialized before bindings"
            )
        if not isinstance(model_tools, list):
            raise TypeError("legacy tool catalog must be a list")
        names = [self._tool_name(item) for item in model_tools]
        if any(name is None for name in names) or not all(
            self._valid_catalog_cell(item) for item in model_tools
        ):
            raise ValueError("legacy tool catalog contains an invalid function schema")
        concrete_names = {name for name in names if name is not None}
        if len(concrete_names) != len(names):
            raise ValueError("legacy tool catalog contains duplicate names")
        protocols = set() if protocol_names is None else set(protocol_names)
        if not all(isinstance(name, str) and name.strip() for name in protocols):
            raise ValueError("protocol tool names must be non-empty strings")
        if not protocols <= concrete_names:
            raise ValueError("protocol tool names must be declared in the catalog")
        self.model_tools.extend(model_tools)
        self._protocol_names.update(protocols)
        self._catalog_initialized = True

    def initialize_legacy_handlers(
        self, handlers: Mapping[str, Callable[..., Any]]
    ) -> None:
        """Atomically install the complete concrete legacy binding set."""
        if not self._catalog_initialized:
            raise RuntimeError("legacy tool catalog must be initialized first")
        if self._legacy_handlers_initialized:
            raise RuntimeError("legacy tool handlers are already initialized")
        if self.legacy_handlers:
            raise RuntimeError(
                "legacy tool handlers must be initialized before bindings"
            )
        if not isinstance(handlers, Mapping):
            raise TypeError("legacy tool handlers must be a mapping")
        expected = (
            self._catalog_names() - self._protocol_names - set(self._native_bindings)
        )
        if set(handlers) != expected:
            raise ValueError("legacy tool handlers must match executable catalog names")
        if not all(isinstance(name, str) and name.strip() for name in handlers):
            raise ValueError("legacy tool handler names must be non-empty strings")
        if not all(callable(handler) for handler in handlers.values()):
            raise TypeError("legacy tool handlers must be callable")
        self.legacy_handlers.update(handlers)
        self._legacy_handlers_initialized = True

    def register_legacy(self, name: str, handler: Callable[..., Any]) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool name must be a non-empty string")
        if not callable(handler):
            raise TypeError("legacy tool handler must be callable")
        if name in self._protocol_names:
            raise ValueError(f"protocol tool cannot have a legacy binding: {name}")
        if name in self._native_bindings:
            raise ValueError(f"tool already has a native binding: {name}")
        if self._catalog_initialized and name not in self._catalog_names():
            raise ValueError(f"tool is not declared in the legacy catalog: {name}")
        if name in self.legacy_handlers:
            raise ValueError(f"tool already has a legacy binding: {name}")
        self.legacy_handlers[name] = handler

    def register_native(self, binding: ToolBinding[Any, Any, Any]) -> None:
        if not isinstance(binding, ToolBinding):
            raise TypeError("native tool binding must be a ToolBinding")
        name = binding.definition.name
        if name in self._protocol_names:
            raise ValueError(f"protocol tool cannot have a native binding: {name}")
        if name in self._catalog_names():
            raise ValueError(f"tool is already declared in the legacy catalog: {name}")
        if name in self.legacy_handlers:
            raise ValueError(f"tool already has a legacy binding: {name}")
        if name in self._native_bindings:
            raise ValueError(f"tool already has a native binding: {name}")
        schema = deepcopy(binding.definition.json_schema())
        if not isinstance(schema, dict):
            raise TypeError("native tool schema must be a dict")
        self._native_bindings[name] = binding
        native_projection = {
            "type": "function",
            "function": {
                "name": name,
                "description": binding.definition.description,
                "parameters": schema,
            },
        }
        protocol_index = next(
            (
                index
                for index, item in enumerate(self.model_tools)
                if self._tool_name(item) in self._protocol_names
            ),
            len(self.model_tools),
        )
        self.model_tools.insert(protocol_index, native_projection)

    def resolve(self, name: str) -> LegacyBindingAdapter | ToolBinding[Any, Any, Any]:
        if name in self._protocol_names:
            raise ValueError(f"未知工具: {name}")
        native = self._native_bindings.get(name)
        if native is not None:
            return native
        if name in self.legacy_handlers:
            return LegacyBindingAdapter(name, self.legacy_handlers)
        raise ValueError(f"未知工具: {name}")

    def legacy_adapter(self, name: str) -> LegacyBindingAdapter:
        if name in self._protocol_names or name in self._native_bindings:
            raise ValueError(f"未知工具: {name}")
        return LegacyBindingAdapter(name, self.legacy_handlers)

    def legacy_definition(self, name: str) -> LegacyToolDefinition:
        if name in self._native_bindings:
            raise ValueError(f"未知工具: {name}")
        for cell in self.model_tools:
            if self._tool_name(cell) == name:
                return LegacyToolDefinition(
                    name,
                    cell,
                    mode=(
                        "answer_submission_protocol"
                        if name in self._protocol_names
                        else "legacy_kwargs"
                    ),
                )
        raise ValueError(f"未知工具: {name}")

    def native_definition(self, name: str) -> ToolDefinition[Any]:
        try:
            return self._native_bindings[name].definition
        except KeyError as error:
            raise ValueError(f"未知工具: {name}") from error


DEFAULT_TOOL_REGISTRY = ToolRegistry()


__all__ = [
    "DEFAULT_TOOL_REGISTRY",
    "LegacyBindingAdapter",
    "LegacyToolDefinition",
    "ToolRegistry",
]
