from __future__ import annotations

import subprocess
import sys
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime.tools.definition import ToolBinding, ToolDefinition
from app.agent_runtime.tools.tool_registry import LegacyBindingAdapter, ToolRegistry


def catalog(*names: str) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {"name": name, "description": name, "parameters": {}},
        }
        for name in names
    ]


class CountingMapping(Mapping[str, object]):
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values
        self.get_calls = 0

    def __getitem__(self, key: str) -> object:
        return self.values[key]

    def __iter__(self):
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default=None):
        self.get_calls += 1
        return self.values.get(key, default)


class ToolRegistryTests(unittest.TestCase):
    def test_default_catalog_and_handler_aliases_share_the_registry_containers(self):
        from app.agent_runtime.tools import TOOLS as package_tools
        from app.agent_runtime.tools.catalog import TOOLS as facade_tools
        from app.agent_runtime.tools.registry import TOOL_HANDLERS
        from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
        from app.bootstrap import tool_bindings, tool_catalog

        self.assertIs(tool_catalog.TOOLS, DEFAULT_TOOL_REGISTRY.model_tools)
        self.assertIs(facade_tools, DEFAULT_TOOL_REGISTRY.model_tools)
        self.assertIs(package_tools, DEFAULT_TOOL_REGISTRY.model_tools)
        self.assertIs(TOOL_HANDLERS, DEFAULT_TOOL_REGISTRY.legacy_handlers)
        self.assertIs(
            TOOL_HANDLERS["search_knowledge"], tool_bindings.search_agent_knowledge
        )

    def test_legacy_definition_is_a_dynamic_view_of_the_live_catalog_cells(self):
        registry = ToolRegistry()
        entries = catalog("first")
        registry.initialize_legacy_catalog(entries)
        definition = registry.legacy_definition("first")
        self.assertIs(definition.schema, entries[0])
        entries[0]["function"]["name"] = "renamed"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "未知工具: first"):
            registry.legacy_definition("first")
        self.assertIs(registry.legacy_definition("renamed").schema, entries[0])
        del registry.model_tools[:]
        with self.assertRaisesRegex(ValueError, "未知工具: renamed"):
            registry.legacy_definition("renamed")

    def test_catalog_initialization_is_atomic_and_rejects_invalid_states(self):
        invalid_catalogs = (
            [{"type": "function", "function": {"name": ""}}],
            catalog("duplicate", "duplicate"),
            [
                {
                    "type": "function",
                    "function": {"name": "bad", "description": 1, "parameters": {}},
                }
            ],
        )
        for entries in invalid_catalogs:
            registry = ToolRegistry()
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                registry.initialize_legacy_catalog(entries)
            self.assertEqual(registry.model_tools, [])
            self.assertFalse(registry._catalog_initialized)
        registry = ToolRegistry()
        with self.assertRaises(ValueError):
            registry.initialize_legacy_catalog(
                catalog("only"), protocol_names={"other"}
            )
        self.assertEqual(registry.model_tools, [])
        registry.register_native(self.binding("native"))
        with self.assertRaises(RuntimeError):
            registry.initialize_legacy_catalog(catalog("legacy"))
        self.assertFalse(registry._catalog_initialized)
        registry = ToolRegistry()
        registry.initialize_legacy_catalog(catalog("once"))
        snapshot = list(registry.model_tools)
        with self.assertRaises(RuntimeError):
            registry.initialize_legacy_catalog(catalog("twice"))
        self.assertEqual(registry.model_tools, snapshot)

    def test_native_registration_is_atomic_and_cannot_collide_with_catalog(self):
        registry = ToolRegistry()
        registry.initialize_legacy_catalog(
            catalog("legacy", "submit"), protocol_names={"submit"}
        )
        for name in ("legacy", "submit"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                registry.register_native(self.binding(name))
        self.assertEqual(registry._native_bindings, {})
        schema = {"type": "object", "properties": {"value": {"type": "string"}}}
        registry.register_native(self.binding("native", schema))
        self.assertEqual(
            [item["function"]["name"] for item in registry.model_tools],  # type: ignore[index]
            ["legacy", "native", "submit"],
        )
        projected = registry.model_tools[1]["function"]["parameters"]  # type: ignore[index]
        self.assertEqual(projected, schema)
        self.assertIsNot(projected, schema)
        projected["properties"]["value"]["type"] = "integer"  # type: ignore[index]
        self.assertEqual(schema["properties"]["value"]["type"], "string")
        with self.assertRaises(ValueError):
            registry.register_native(self.binding("native"))
        before = list(registry.model_tools)
        with self.assertRaises(RuntimeError):
            registry.register_native(
                self.binding("broken", error=RuntimeError("schema"))
            )
        self.assertEqual(registry.model_tools, before)
        self.assertNotIn("broken", registry._native_bindings)
        with self.assertRaises(TypeError):
            registry.register_native(self.binding("not-a-dict", schema=[]))  # type: ignore[arg-type]
        self.assertNotIn("not-a-dict", registry._native_bindings)

    def test_mixed_catalog_native_and_legacy_initialization_stays_disjoint(self):
        registry = ToolRegistry()
        registry.initialize_legacy_catalog(
            catalog("legacy", "submit"), protocol_names={"submit"}
        )
        binding = self.binding("native")
        registry.register_native(binding)
        registry.initialize_legacy_handlers({"legacy": lambda: "legacy"})
        self.assertIs(registry.resolve("native"), binding)
        with self.assertRaisesRegex(ValueError, "^未知工具: native$"):
            registry.legacy_definition("native")
        with self.assertRaisesRegex(ValueError, "^未知工具: native$"):
            registry.legacy_adapter("native")

    def test_legacy_registration_and_bulk_initialization_are_atomic(self):
        local = ToolRegistry()
        with self.assertRaises(TypeError):
            local.register_legacy("bad", object())  # type: ignore[arg-type]
        local.register_legacy("local", lambda: None)
        self.assertEqual(set(local.legacy_handlers), {"local"})
        registry = ToolRegistry()
        with self.assertRaises(RuntimeError):
            registry.initialize_legacy_handlers({})
        registry.initialize_legacy_catalog(
            catalog("one", "two", "submit"), protocol_names={"submit"}
        )
        for handlers in (
            {"one": lambda: None},
            {"one": lambda: None, "two": lambda: None, "extra": lambda: None},
            {"one": lambda: None, "two": object()},
            {"one": lambda: None, "submit": lambda: None},
        ):
            with (
                self.subTest(handlers=handlers),
                self.assertRaises((TypeError, ValueError)),
            ):
                registry.initialize_legacy_handlers(handlers)  # type: ignore[arg-type]
            self.assertEqual(registry.legacy_handlers, {})
            self.assertFalse(registry._legacy_handlers_initialized)
        good = {"one": lambda: "one", "two": lambda: "two"}
        registry.initialize_legacy_handlers(good)
        self.assertIs(registry.legacy_handlers["one"], good["one"])
        with self.assertRaises(RuntimeError):
            registry.initialize_legacy_handlers(good)

    def test_legacy_adapter_live_patching_and_generic_mapping_semantics(self):
        values: dict[str, object] = {}
        adapter = LegacyBindingAdapter("tool", values)
        first = object()
        second = object()
        calls: list[dict[str, object]] = []
        values["tool"] = lambda **kwargs: calls.append(kwargs) or first
        self.assertIs(adapter.invoke({"value": 1}), first)
        with patch.dict(
            values, {"tool": lambda **kwargs: calls.append(kwargs) or second}
        ):
            self.assertIs(adapter.invoke({"value": 2}), second)
        self.assertIs(adapter.invoke({"value": 3}), first)
        with (
            patch.dict(values, {}, clear=True),
            self.assertRaisesRegex(ValueError, "^未知工具: tool$"),
        ):
            adapter.invoke({})
        with (
            patch.dict(values, {"tool": None}),
            self.assertRaisesRegex(ValueError, "^未知工具: tool$"),
        ):
            adapter.invoke({})
        self.assertEqual(calls, [{"value": 1}, {"value": 2}, {"value": 3}])
        raised = CountingMapping({"boom": self.raise_once})
        with self.assertRaisesRegex(RuntimeError, "handler failure"):
            LegacyBindingAdapter("boom", raised).invoke({})
        self.assertEqual(raised.get_calls, 1)
        handler_calls = []

        def runtime_handler(**_: object) -> None:
            handler_calls.append("called")
            raise RuntimeError("runtime handler")

        with self.assertRaisesRegex(RuntimeError, "runtime handler"):
            LegacyBindingAdapter("runtime", {"runtime": runtime_handler}).invoke({})
        self.assertEqual(handler_calls, ["called"])
        missing = CountingMapping({})
        with self.assertRaisesRegex(ValueError, "^未知工具: absent$"):
            LegacyBindingAdapter("absent", missing).invoke({})
        self.assertEqual(missing.get_calls, 1)

    def test_registry_never_exposes_protocol_or_native_as_legacy_execution(self):
        registry = ToolRegistry()
        registry.initialize_legacy_catalog(
            catalog("legacy", "submit"), protocol_names={"submit"}
        )
        registry.initialize_legacy_handlers({"legacy": lambda: "legacy"})
        registry.legacy_handlers["submit"] = lambda: "patched"
        with self.assertRaisesRegex(ValueError, "^未知工具: submit$"):
            registry.resolve("submit")
        with self.assertRaisesRegex(ValueError, "^未知工具: submit$"):
            registry.legacy_adapter("submit")
        native_registry = ToolRegistry()
        native_registry.register_native(self.binding("native"))
        native_registry.legacy_handlers["native"] = lambda: "patched"
        self.assertIsInstance(native_registry.resolve("native"), ToolBinding)
        with self.assertRaisesRegex(ValueError, "^未知工具: native$"):
            native_registry.legacy_adapter("native")

    def test_catalog_and_registry_import_orders_preserve_live_default_views(self):
        root = Path(__file__).resolve().parents[1]
        runner = """import importlib.abc
import socket
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
events = []
def audit(event, args):
    if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.sendto', 'socket.gethostbyname'} or event.startswith('sqlite3.connect'):
        events.append(event)
        raise AssertionError(event)
sys.addaudithook(audit)
try:
    with socket.socket() as value:
        value.connect(('127.0.0.1', 9))
except AssertionError:
    pass
else:
    raise AssertionError('network negative control')
try:
    sqlite3.connect(':memory:')
except AssertionError:
    pass
else:
    raise AssertionError('sqlite negative control')
events.clear()
class CatalogOnlyDeny(importlib.abc.MetaPathFinder):
    blocked = ('app.bootstrap.tool_bindings', 'app.manufacturing.reports', 'app.knowledge.rag', 'app.core.settings')
    def find_spec(self, name, path=None, target=None):
        if any(name == item or name.startswith(item + '.') for item in self.blocked):
            raise AssertionError(name)
finder = CatalogOnlyDeny()
if sys.argv[2] == 'catalog-first':
    sys.meta_path.insert(0, finder)
    from app.agent_runtime.tools.catalog import TOOLS
    assert 'app.bootstrap.tool_bindings' not in sys.modules
    sys.meta_path.remove(finder)
    from app.agent_runtime.tools.registry import TOOL_HANDLERS
else:
    from app.agent_runtime.tools.registry import TOOL_HANDLERS
    from app.agent_runtime.tools.catalog import TOOLS
from app.agent_runtime.tools import TOOLS as package_tools, TOOL_HANDLERS as package_handlers
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
from app.bootstrap import tool_catalog
from app.agent_runtime.tools.catalog import DATE_PROPERTIES, SUBMIT_ANALYSIS_TOOL, _schema
assert TOOLS is package_tools is tool_catalog.TOOLS is DEFAULT_TOOL_REGISTRY.model_tools
assert TOOL_HANDLERS is package_handlers is DEFAULT_TOOL_REGISTRY.legacy_handlers
assert len(TOOLS) == 15 and len(TOOL_HANDLERS) == 14
assert SUBMIT_ANALYSIS_TOOL is tool_catalog.SUBMIT_ANALYSIS_TOOL
assert DATE_PROPERTIES is tool_catalog.DATE_PROPERTIES and _schema is tool_catalog._schema
assert events == [], events
"""
        for order in ("catalog-first", "registry-first"):
            completed = subprocess.run(
                [sys.executable, "-I", "-c", runner, str(root), order],
                text=True,
                capture_output=True,
                check=False,
                cwd=root,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    @staticmethod
    def raise_once(**_: object) -> None:
        raise RuntimeError("handler failure")

    @staticmethod
    def binding(
        name: str,
        schema: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> ToolBinding:
        @dataclass(frozen=True)
        class Input:
            @classmethod
            def from_arguments(cls, arguments):
                return cls()

            @classmethod
            def json_schema(cls):
                if error is not None:
                    raise error
                return schema if schema is not None else {"type": "object"}

        definition = ToolDefinition(name, "1", "native", Input, lambda value: value)
        return ToolBinding(definition, lambda value, context: None, object())


if __name__ == "__main__":
    unittest.main()
