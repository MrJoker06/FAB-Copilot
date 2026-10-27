from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from app.agent_runtime.tools.contracts import (
    TOOL_CONTRACT_VERSION,
    ToolError,
    ToolErrorKind,
    ToolExecutionContext,
    ToolExecutionLimits,
    ToolExecutionState,
    ToolResult,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)


@dataclass(frozen=True)
class FakePrincipal:
    tenant_id: str = "tenant-a"
    user_id: str = "user-a"
    roles: tuple[str, ...] = ("analyst",)


@dataclass
class FakeEquipmentPort:
    equipment_id: str
    calls: list[str] = field(default_factory=list)

    def read_for_tenant(self, tenant_id: str) -> dict[str, str]:
        self.calls.append(tenant_id)
        return {"equipment_id": self.equipment_id, "tenant_id": tenant_id}


class FakeCancellation:
    def is_cancelled(self) -> bool:
        return False


class ToolContractTests(unittest.TestCase):
    def context(self, **overrides):
        values = {
            "principal": FakePrincipal(),
            "run_id": "run-1",
            "call_id": "call-1",
            "dependencies": FakeEquipmentPort("CMP-03"),
        }
        values.update(overrides)
        return ToolExecutionContext(**values)

    def error(self, kind=ToolErrorKind.INTERNAL) -> ToolError:
        return ToolError("TOOL_FAILED", "The tool could not complete.", kind)

    def test_typed_handler_uses_context_port_and_principal_once(self):
        port = FakeEquipmentPort("CMP-03")
        context = self.context(dependencies=port)

        def handler(
            value: ToolExecutionContext[FakeEquipmentPort],
        ) -> ToolResult[dict[str, str]]:
            payload = value.dependencies.read_for_tenant(value.principal.tenant_id)
            scope = ToolScope(
                value.principal.tenant_id, equipment_ids=(port.equipment_id,)
            )
            source = ToolSource(
                "fake:equipment", "fake-equipment-port", ToolSourceKind.FAKE, scope
            )
            return ToolResult(
                value.call_id,
                "get_equipment",
                "1",
                ToolStatus.SUCCEEDED,
                ToolExecutionState.COMPLETED,
                data=payload,
                sources=(source,),
                row_count=1,
                elapsed_ms=0.0,
            )

        result = handler(context)
        self.assertIs(context.dependencies, port)
        self.assertEqual(port.calls, ["tenant-a"])
        self.assertEqual(result.call_id, "call-1")
        self.assertEqual(
            result.data, {"equipment_id": "CMP-03", "tenant_id": "tenant-a"}
        )
        self.assertEqual(result.sources[0].scope.tenant_id, "tenant-a")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.contract_version, TOOL_CONTRACT_VERSION)

    def test_context_retains_payload_identity_without_invoking_port_or_cancellation(
        self,
    ):
        class UncalledPort:
            def read(self):
                raise AssertionError("port was invoked")

        class UncalledCancellation:
            def is_cancelled(self):
                raise AssertionError("cancellation was invoked")

        port = UncalledPort()
        context = self.context(dependencies=port, cancellation=UncalledCancellation())
        payload: list[str] = []
        result = ToolResult(
            "call-1",
            "equipment",
            "1",
            ToolStatus.SUCCEEDED,
            ToolExecutionState.COMPLETED,
            data=payload,
        )
        self.assertIs(context.dependencies, port)
        self.assertIs(result.data, payload)
        self.assertIsInstance(context.limits, ToolExecutionLimits)

    def test_context_requires_non_empty_whitespace_free_identifiers_and_protocol_shape(
        self,
    ):
        for run_id in ("", " \t"):
            with (
                self.subTest(run_id=run_id),
                self.assertRaisesRegex(ValueError, "run_id"),
            ):
                self.context(run_id=run_id)
        with self.assertRaisesRegex(ValueError, "principal"):
            self.context(principal=object())
        with self.assertRaisesRegex(ValueError, "cancellation"):
            self.context(cancellation=object())

    def test_limits_reject_bool_negative_nonfinite_and_preserve_zero_deadline(self):
        self.assertEqual(
            ToolExecutionLimits(deadline_monotonic=0.0).deadline_monotonic, 0.0
        )
        for kwargs in (
            {"remaining_calls": True},
            {"max_result_rows": -1},
            {"deadline_monotonic": float("inf")},
            {"deadline_monotonic": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ToolExecutionLimits(**kwargs)

    def test_scope_requires_paired_ordered_dates_and_nonblank_tuple_filters(self):
        scope = ToolScope("tenant-a", date(2026, 1, 1), date(2026, 1, 2), ("CMP-03",))
        self.assertEqual(scope.equipment_ids, ("CMP-03",))
        invalid = (
            {"tenant_id": " "},
            {"start_date": date(2026, 1, 1)},
            {"start_date": date(2026, 1, 2), "end_date": date(2026, 1, 1)},
            {
                "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "end_date": date(2026, 1, 1),
            },
            {"equipment_ids": ["CMP-03"]},
            {"equipment_ids": (" ",)},
            {"lot_ids": (1,)},
            {"grain": "\t"},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ToolScope(**({"tenant_id": "tenant-a"} | kwargs))

    def test_source_is_safe_metadata_and_rejects_blank_references(self):
        source = ToolSource(
            "report:summary",
            "report-adapter",
            ToolSourceKind.REPORT_API,
            ToolScope("tenant-a"),
        )
        self.assertEqual(source.source_kind, ToolSourceKind.REPORT_API)
        for source_ref, adapter_id in (
            ("", "adapter"),
            (" ", "adapter"),
            ("ref", "\n"),
        ):
            with (
                self.subTest(source_ref=source_ref, adapter_id=adapter_id),
                self.assertRaises(ValueError),
            ):
                ToolSource(
                    source_ref, adapter_id, ToolSourceKind.FAKE, ToolScope("tenant-a")
                )
        with self.assertRaises(ValueError):
            ToolSource("ref", "adapter", "database", ToolScope("tenant-a"))  # type: ignore[arg-type]

    def test_result_matrix_covers_every_status_state_error_combination(self):
        allowed = {
            ToolStatus.SUCCEEDED: {None: {ToolExecutionState.COMPLETED}},
            ToolStatus.INVALID_ARGUMENTS: {
                ToolErrorKind.PARSING: {ToolExecutionState.NOT_STARTED},
                ToolErrorKind.VALIDATION: {ToolExecutionState.NOT_STARTED},
            },
            ToolStatus.DENIED: {
                ToolErrorKind.AUTHORIZATION: {ToolExecutionState.NOT_STARTED}
            },
            ToolStatus.BLOCKED: {
                ToolErrorKind.BUDGET: {ToolExecutionState.NOT_STARTED}
            },
            ToolStatus.FAILED: {
                ToolErrorKind.DATA_SOURCE: {
                    ToolExecutionState.NOT_STARTED,
                    ToolExecutionState.COMPLETED,
                    ToolExecutionState.UNKNOWN,
                },
                ToolErrorKind.INTERNAL: {
                    ToolExecutionState.NOT_STARTED,
                    ToolExecutionState.COMPLETED,
                    ToolExecutionState.UNKNOWN,
                },
            },
            ToolStatus.TIMED_OUT: {
                ToolErrorKind.TIMEOUT: {
                    ToolExecutionState.NOT_STARTED,
                    ToolExecutionState.UNKNOWN,
                    ToolExecutionState.CANCELLED_CONFIRMED,
                }
            },
            ToolStatus.CANCELLED: {
                ToolErrorKind.CANCELLATION: {
                    ToolExecutionState.NOT_STARTED,
                    ToolExecutionState.UNKNOWN,
                    ToolExecutionState.CANCELLED_CONFIRMED,
                }
            },
        }
        error_kinds: tuple[ToolErrorKind | None, ...] = (None, *ToolErrorKind)
        for status in ToolStatus:
            for state in ToolExecutionState:
                for kind in error_kinds:
                    with self.subTest(status=status, state=state, kind=kind):
                        error = None if kind is None else self.error(kind)
                        arguments = ("call", "tool", "1", status, state)
                        if state in allowed[status].get(kind, set()):
                            ToolResult(*arguments, error=error)
                        else:
                            with self.assertRaises(ValueError):
                                ToolResult(*arguments, error=error)

    def test_failed_before_handler_invocation_preserves_not_started_fact(self):
        port = FakeEquipmentPort("CMP-03")
        context = self.context(dependencies=port)
        handler_calls: list[str] = []

        def handler(_: ToolExecutionContext[FakeEquipmentPort]) -> None:
            handler_calls.append("called")

        result = ToolResult(
            context.call_id,
            "get_equipment",
            "1",
            ToolStatus.FAILED,
            ToolExecutionState.NOT_STARTED,
            error=ToolError(
                "BINDING_MISSING",
                "The tool binding is unavailable.",
                ToolErrorKind.INTERNAL,
            ),
        )
        self.assertEqual(handler_calls, [])
        self.assertEqual(port.calls, [])
        self.assertIs(result.execution_state, ToolExecutionState.NOT_STARTED)
        self.assertIsNotNone(handler)

    def test_representative_bad_result_reaches_execution_state_rule(self):
        with self.assertRaisesRegex(
            ValueError, "^timed_out or cancelled result has an invalid execution state$"
        ):
            ToolResult(
                "call",
                "tool",
                "1",
                ToolStatus.TIMED_OUT,
                ToolExecutionState.COMPLETED,
                error=self.error(ToolErrorKind.TIMEOUT),
            )

    def test_result_rejects_payload_and_strict_numeric_coercion(self):
        with self.assertRaises(ValueError):
            ToolResult(
                "c",
                "tool",
                "1",
                ToolStatus.FAILED,
                ToolExecutionState.COMPLETED,
                data={"secret": "not permitted"},
                error=self.error(),
            )
        for extra in (
            {"row_count": True},
            {"row_count": -1},
            {"elapsed_ms": -0.1},
            {"elapsed_ms": float("nan")},
            {"elapsed_ms": 1},
            {"sources": []},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                ToolResult(
                    "c",
                    "tool",
                    "1",
                    ToolStatus.SUCCEEDED,
                    ToolExecutionState.COMPLETED,
                    **extra,
                )

    def test_error_and_result_type_and_version_guards(self):
        for values in (
            (Exception("raw"), "message", ToolErrorKind.INTERNAL, False),
            ("code", " ", ToolErrorKind.INTERNAL, False),
            ("code", "message", "internal", False),
            ("code", "message", ToolErrorKind.INTERNAL, 1),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ToolError(*values)  # type: ignore[arg-type]
        base = {
            "call_id": "c",
            "tool_name": "tool",
            "tool_version": "1",
            "status": ToolStatus.SUCCEEDED,
            "execution_state": ToolExecutionState.COMPLETED,
        }
        for extra in (
            {"contract_version": "2.0.0"},
            {"status": "succeeded"},
            {"execution_state": "completed"},
            {"sources": (object(),)},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                ToolResult(**(base | extra))  # type: ignore[arg-type]

    def test_envelopes_are_shallow_frozen_and_slotted(self):
        result = ToolResult(
            "c",
            "tool",
            "1",
            ToolStatus.SUCCEEDED,
            ToolExecutionState.COMPLETED,
            data=[],
        )
        with self.assertRaises(FrozenInstanceError):
            result.tool_name = "other"  # type: ignore[misc]
        with self.assertRaises((AttributeError, TypeError)):
            result.extra = "not allowed"  # type: ignore[attr-defined]
        result.data.append("mutable payload remains caller-owned")
        self.assertEqual(result.data, ["mutable payload remains caller-owned"])

    def test_contract_has_no_sql_or_connection_constructor_fields(self):
        with self.assertRaises(TypeError):
            ToolExecutionContext(
                principal=FakePrincipal(),
                run_id="r",
                call_id="c",
                dependencies=FakeEquipmentPort("E"),
                sql="select 1",
            )  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            ToolScope("tenant-a", query="select 1")  # type: ignore[call-arg]

    def test_tools_legacy_all_order_identity_and_live_patch(self):
        expected_names = [
            "DATE_PROPERTIES",
            "ParsedToolArguments",
            "TOOL_HANDLERS",
            "TOOLS",
            "_schema",
            "execute_registered_tool",
            "parse_tool_arguments",
            "search_agent_knowledge",
        ]
        tools = importlib.import_module("app.agent_runtime.tools")
        catalog = importlib.import_module("app.agent_runtime.tools.catalog")
        executor = importlib.import_module("app.agent_runtime.tools.executor")
        registry = importlib.import_module("app.agent_runtime.tools.registry")
        expected_modules = {
            "DATE_PROPERTIES": catalog,
            "TOOLS": catalog,
            "_schema": catalog,
            "ParsedToolArguments": executor,
            "execute_registered_tool": executor,
            "parse_tool_arguments": executor,
            "TOOL_HANDLERS": registry,
            "search_agent_knowledge": registry,
        }
        self.assertEqual(tools.__all__, expected_names)
        for name, module in expected_modules.items():
            with self.subTest(name=name):
                self.assertIs(getattr(tools, name), getattr(module, name))
        marker = object()
        registry.TOOL_HANDLERS["mod-004-test"] = marker
        try:
            self.assertIs(tools.TOOL_HANDLERS["mod-004-test"], marker)
        finally:
            del registry.TOOL_HANDLERS["mod-004-test"]
        self.assertIn("TOOLS", dir(tools))
        unknown_name = "not_a_tool_export"
        with self.assertRaises(AttributeError):
            getattr(tools, unknown_name)

    def test_fresh_legacy_first_access_caches_canonical_exports(self):
        root = Path(__file__).resolve().parents[1]
        code = """import sys
sys.path.insert(0, sys.argv[1])
import app.agent_runtime.tools as tools
assert 'app.agent_runtime.tools.catalog' not in sys.modules
assert 'app.agent_runtime.tools.registry' not in sys.modules
expected = ['DATE_PROPERTIES', 'ParsedToolArguments', 'TOOL_HANDLERS', 'TOOLS', '_schema', 'execute_registered_tool', 'parse_tool_arguments', 'search_agent_knowledge']
assert tools.__all__ == expected
first = tools.TOOLS
assert tools.TOOLS is first and tools.__dict__['TOOLS'] is first
from app.agent_runtime.tools import catalog, executor, registry
expected_modules = {'DATE_PROPERTIES': catalog, 'TOOLS': catalog, '_schema': catalog, 'ParsedToolArguments': executor, 'execute_registered_tool': executor, 'parse_tool_arguments': executor, 'TOOL_HANDLERS': registry, 'search_agent_knowledge': registry}
for name, module in expected_modules.items(): assert getattr(tools, name) is getattr(module, name), name
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code, str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_lazy_star_import_keeps_legacy_exports_available(self):
        namespace: dict[str, object] = {}
        exec("from app.agent_runtime.tools import *", namespace)  # noqa: S102
        self.assertIn("TOOLS", namespace)
        self.assertIn("TOOL_HANDLERS", namespace)

    def test_canonical_contract_import_enforces_active_forbidden_import_and_io_guards(
        self,
    ):
        root = Path(__file__).resolve().parents[1]
        code = """import importlib
import socket
import sqlite3
import sys
sys.path.insert(0, sys.argv[1])
forbidden = {'app.core.settings', 'app.core.identity', 'app.manufacturing.reports', 'app.manufacturing.enterprise_data', 'app.knowledge.rag', 'app.knowledge.sqlite_backend', 'app.persistence', 'app.persistence.database', 'app.agent_runtime.tools.catalog', 'app.agent_runtime.tools.registry'}
class DenyImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in forbidden: raise RuntimeError('blocked import: ' + fullname)
sys.meta_path.insert(0, DenyImports())
def audit(event, args):
    if event == 'open' and str(args[0]).endswith('.env'): raise RuntimeError('blocked env open')
    if event in {'sqlite3.connect', 'socket.connect'}: raise RuntimeError('blocked io: ' + event)
sys.addaudithook(audit)
import app.agent_runtime.tools.contracts
assert not any(name in sys.modules for name in forbidden)
try: importlib.import_module('app.core.settings')
except RuntimeError as error: assert str(error) == 'blocked import: app.core.settings'
else: raise AssertionError('import guard was not active')
try: open('.env')
except RuntimeError as error: assert str(error) == 'blocked env open'
else: raise AssertionError('env guard was not active')
try: sqlite3.connect(':memory:')
except RuntimeError as error: assert str(error) == 'blocked io: sqlite3.connect'
else: raise AssertionError('sqlite guard was not active')
try: socket.socket().connect(('127.0.0.1', 1))
except RuntimeError as error: assert str(error) == 'blocked io: socket.connect'
else: raise AssertionError('socket guard was not active')
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code, str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_contract_source_is_standalone_leaf_and_drives_fake_handler(self):
        source = (
            Path(__file__).resolve().parents[1] / "app/agent_runtime/tools/contracts.py"
        )
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "contracts.py"
            shutil.copyfile(source, target)
            code = """import importlib.util
import sys
source, original = sys.argv[1:]
spec = importlib.util.spec_from_file_location('isolated_contracts', source)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert module.__file__ == source
class Principal: tenant_id = 'tenant'; user_id = 'user'; roles = ('analyst',)
class Port:
    def __init__(self): self.calls = []
    def read(self, tenant): self.calls.append(tenant); return {'tenant': tenant}
port = Port()
context = module.ToolExecutionContext(Principal(), 'run', 'call', port)
def handler(value):
    payload = value.dependencies.read(value.principal.tenant_id)
    scope = module.ToolScope(value.principal.tenant_id)
    return module.ToolResult(value.call_id, 'fake', '1', module.ToolStatus.SUCCEEDED, module.ToolExecutionState.COMPLETED, payload, sources=(module.ToolSource('fake:result', 'fake-port', module.ToolSourceKind.FAKE, scope),), row_count=1, elapsed_ms=0.0)
result = handler(context)
assert port.calls == ['tenant'] and result.data == {'tenant': 'tenant'}
assert result.sources[0].scope.tenant_id == 'tenant'
assert 'app' not in sys.modules
assert not any(str(getattr(item, '__file__', '')).startswith(original) for item in sys.modules.values())
"""
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    code,
                    str(target),
                    str(source.parents[3]),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
