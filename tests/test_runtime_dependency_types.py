"""Type guards for coordinator dependency groups, run state and event ports."""

from __future__ import annotations

import ast
import collections.abc
import dataclasses
import inspect
import json
import subprocess
import sys
import tempfile
import types
import typing
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app.agent_runtime.service as agent
from app.agent_runtime import coordinator_state, dependencies, ports, telemetry
from app.agent_runtime.coordinator_state import CoordinatorRunState
from app.agent_runtime.dependencies import (
    AvailabilityDependencies,
    CoordinatorDependencies,
    LoopDependencies,
    ModelDependencies,
    PreparationDependencies,
    ReadyDependencies,
)
from app.agent_runtime.execution import agent_loop
from app.agent_runtime.execution.agent_loop import AgentLoopContext
from app.agent_runtime.execution.pilot_stages import publish_stage_event
from app.agent_runtime.execution.runtime_contracts import ModelUsage, RuntimeEvent
from app.agent_runtime.telemetry import (
    RUNTIME_STAGE_AUDIT_EVENT,
    AuditEventSink,
    runtime_event_audit_fields,
)
from app.agent_runtime.tools.contracts import ToolExecutionState, ToolStatus
from app.core.settings import ModelConnection, Settings
from app.telemetry import audit

ROOT = Path(__file__).resolve().parents[1]
GROUPS = (
    PreparationDependencies,
    AvailabilityDependencies,
    ModelDependencies,
    ReadyDependencies,
    LoopDependencies,
)
TYPED_DATACLASSES = (
    (dependencies, (*GROUPS, CoordinatorDependencies)),
    (coordinator_state, (CoordinatorRunState,)),
    (agent_loop, (AgentLoopContext,)),
)
# Field annotations that may still be ``Any`` at the top level.  Intentionally
# empty: ``Any`` is accepted only as the value type of a ``str``-keyed JSON
# mapping (``dict[str, Any]``), which carries arbitrary serialisable payloads.
ANY_FIELD_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()
_JSON_MAPPINGS = frozenset({"dict", "Mapping"})
_SENTINEL = object()


def _type_checking_namespace(module: types.ModuleType) -> dict[str, object]:
    """Execute a module's ``if TYPE_CHECKING:`` imports and return the names."""
    tree = ast.parse(inspect.getsource(module))
    namespace: dict[str, object] = {
        "__name__": module.__name__,
        "__package__": module.__package__,
    }
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            code = compile(
                ast.Module(body=node.body, type_ignores=[]), module.__file__, "exec"
            )
            exec(code, namespace)  # noqa: S102 - trusted repository imports only
    return {k: v for k, v in namespace.items() if not k.startswith("__")}


def _resolution_namespace(module: types.ModuleType) -> dict[str, object]:
    # Port aliases keep forward references to their own TYPE_CHECKING names.
    return {
        **_type_checking_namespace(ports),
        **vars(ports),
        **_type_checking_namespace(module),
        **vars(module),
    }


def _disallowed_any(annotation: str) -> list[str]:
    """Return each ``Any`` use that is not the value of a ``str``-keyed mapping."""
    tree = ast.parse(annotation, mode="eval")
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in _JSON_MAPPINGS
            and isinstance(node.slice, ast.Tuple)
            and len(node.slice.elts) == 2
            and isinstance(node.slice.elts[0], ast.Name)
            and node.slice.elts[0].id == "str"
            and isinstance(node.slice.elts[1], ast.Name)
            and node.slice.elts[1].id == "Any"
        ):
            allowed.add(id(node.slice.elts[1]))
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "Any" and id(node) not in allowed
    ]


def _unwrap_optional(hint: object) -> tuple[object, bool]:
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        args = [arg for arg in typing.get_args(hint) if arg is not type(None)]
        if len(args) == 1:
            return args[0], True
    return hint, False


def _is_callable_port(hint: object) -> bool:
    return (
        isinstance(hint, type)
        and getattr(hint, "_is_protocol", False)
        and "__call__" in vars(hint)
    )


def _call_shapes(hint: object) -> tuple[tuple[list, dict], tuple[list, dict], bool]:
    """Return (all-arguments, required-only) call shapes and whether it is async."""
    if _is_callable_port(hint):
        call = vars(hint)["__call__"]
        parameters = list(inspect.signature(call).parameters.values())[1:]
        full_pos, full_kw, req_pos, req_kw = [], {}, [], {}
        for parameter in parameters:
            required = parameter.default is inspect.Parameter.empty
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                full_pos.append(_SENTINEL)
                if required:
                    req_pos.append(_SENTINEL)
            elif parameter.kind is inspect.Parameter.KEYWORD_ONLY:
                full_kw[parameter.name] = _SENTINEL
                if required:
                    req_kw[parameter.name] = _SENTINEL
            elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
                full_kw["extra_audit_field"] = _SENTINEL
            else:
                raise AssertionError(
                    f"{hint.__name__}: {parameter} must be positional- or keyword-only"
                )
        return (full_pos, full_kw), (req_pos, req_kw), inspect.iscoroutinefunction(call)
    if typing.get_origin(hint) is collections.abc.Callable:
        arguments = typing.get_args(hint)[0]
        if arguments is Ellipsis:
            raise AssertionError(f"{hint} must declare its parameters")
        shape = ([_SENTINEL] * len(arguments), {})
        return shape, shape, False
    raise TypeError(hint)


def _assert_satisfies(
    test: unittest.TestCase, label: str, hint: object, value: object
) -> None:
    full, required, asynchronous = _call_shapes(hint)
    test.assertTrue(callable(value), label)
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        # Builtins such as time.perf_counter expose no signature before 3.13.
        return
    for args, kwargs in (full, required):
        try:
            signature.bind(*args, **kwargs)
        except TypeError as exc:  # pragma: no cover - failure detail
            test.fail(
                f"{label}: {signature} does not accept {len(args)} positional / {sorted(kwargs)}: {exc}"
            )
    test.assertEqual(inspect.iscoroutinefunction(value), asynchronous, label)


def _resolved_hints(module: types.ModuleType, cls: type) -> dict[str, object]:
    return typing.get_type_hints(cls, globalns=_resolution_namespace(module))


class DependencyAnnotationGuardTests(unittest.TestCase):
    def test_no_field_annotation_is_any(self):
        self.assertEqual(ANY_FIELD_ALLOWLIST, frozenset())
        checked = 0
        for _module, classes in TYPED_DATACLASSES:
            for cls in classes:
                for item in dataclasses.fields(cls):
                    with self.subTest(owner=cls.__name__, field=item.name):
                        self.assertIsInstance(item.type, str)
                        if (cls.__name__, item.name) in ANY_FIELD_ALLOWLIST:
                            continue
                        self.assertEqual(_disallowed_any(item.type), [], item.type)
                        checked += 1
        total = sum(
            len(dataclasses.fields(cls))
            for _module, classes in TYPED_DATACLASSES
            for cls in classes
        )
        self.assertEqual(checked, total)

    def test_ports_use_any_only_for_json_mappings_and_audit_fields(self):
        tree = ast.parse(inspect.getsource(ports))
        # ``AuditEmitter`` forwards arbitrary audit fields as ``**fields: Any``.
        allowed = {
            id(node.kwarg.annotation)
            for node in ast.walk(tree)
            if isinstance(node, ast.arguments) and node.kwarg is not None
        }
        self.assertEqual(len(allowed), 1)
        offending = []
        for node in ast.walk(tree):
            annotation = None
            if isinstance(node, ast.arg) and node.annotation is not None:
                annotation = node.annotation
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.returns is not None
            ):
                annotation = node.returns
            elif isinstance(node, ast.AnnAssign):
                annotation = node.value if node.value is not None else node.annotation
            if annotation is None or id(annotation) in allowed:
                continue
            text = ast.unparse(annotation)
            offending.extend(f"{text}: {item}" for item in _disallowed_any(text))
        self.assertEqual(offending, [])
        emitter = inspect.signature(vars(ports.AuditEmitter)["__call__"])
        self.assertEqual(
            emitter.parameters["fields"].kind, inspect.Parameter.VAR_KEYWORD
        )

    def test_guards_reject_negative_controls(self):
        self.assertEqual(_disallowed_any("Any"), ["Any"])
        self.assertEqual(_disallowed_any("Any | None"), ["Any"])
        self.assertEqual(_disallowed_any("list[Any]"), ["Any"])
        self.assertEqual(_disallowed_any("dict[Any, str]"), ["Any"])
        self.assertEqual(_disallowed_any("dict[str, Any] | None"), [])
        with self.assertRaises(AssertionError):
            _assert_satisfies(self, "arity", ports.ModelHealthReader, lambda: {})
        with self.assertRaises(AssertionError):
            _assert_satisfies(
                self,
                "keywords",
                ports.ModelCallClaimer,
                lambda model_id: (True, {}, None),
            )

        async def not_sync(model_id):
            return {}

        with self.assertRaises(AssertionError):
            _assert_satisfies(self, "async", ports.ModelHealthReader, not_sync)

    def test_dependency_groups_keep_field_names_order_and_defaults(self):
        self.assertEqual(
            [item.name for item in dataclasses.fields(CoordinatorDependencies)],
            [
                "preparation",
                "availability",
                "model",
                "ready",
                "loop",
                "tool_run_factory",
                "offline_tool_runner",
            ],
        )
        self.assertEqual(
            [item.default for item in dataclasses.fields(CoordinatorDependencies)][-2:],
            [None, None],
        )
        self.assertEqual(sum(len(dataclasses.fields(group)) for group in GROUPS), 58)
        self.assertEqual(
            [item.name for item in dataclasses.fields(PreparationDependencies)][:3],
            ["system_prompt", "perf_counter", "settings_type"],
        )


class DependencyTypeResolutionTests(unittest.TestCase):
    def test_every_annotation_resolves_to_an_importable_type(self):
        for module, classes in TYPED_DATACLASSES:
            for cls in classes:
                with self.subTest(owner=cls.__name__):
                    hints = _resolved_hints(module, cls)
                    for item in dataclasses.fields(cls):
                        self.assertIn(item.name, hints)
                        self.assertIsNot(hints[item.name], typing.Any, item.name)

    def test_every_port_signature_resolves(self):
        namespace = {**_type_checking_namespace(ports), **vars(ports)}
        names = [
            name for name in ports.__all__ if _is_callable_port(getattr(ports, name))
        ]
        self.assertEqual(len(names), 22)
        for name in names:
            with self.subTest(port=name):
                hints = typing.get_type_hints(
                    vars(getattr(ports, name))["__call__"], globalns=namespace
                )
                self.assertIn("return", hints)
        for name in ("ToolRunBindings", "RuntimeSettings", "RuntimeModelConnection"):
            port = getattr(ports, name)
            for member, value in vars(port).items():
                if isinstance(value, property):
                    with self.subTest(port=name, member=member):
                        typing.get_type_hints(value.fget, globalns=namespace)

    def test_configuration_views_match_the_concrete_settings(self):
        settings_fields = {item.name for item in dataclasses.fields(Settings)}
        connection_fields = {item.name for item in dataclasses.fields(ModelConnection)}
        for port, concrete in (
            (ports.RuntimeSettings, settings_fields),
            (ports.RuntimeModelConnection, connection_fields),
        ):
            members = {
                name
                for name, value in vars(port).items()
                if isinstance(value, property)
            }
            with self.subTest(port=port.__name__):
                self.assertTrue(members)
                self.assertLessEqual(members, concrete)
        settings = agent.get_settings()
        self.assertIsInstance(settings, ports.RuntimeSettings)
        self.assertIsInstance(settings.model_connection, ports.RuntimeModelConnection)


class LegacyAssemblySatisfiesPortsTests(unittest.TestCase):
    def test_real_service_snapshot_satisfies_every_group_annotation(self):
        deps = agent._coordinator_dependencies()
        self.assertIsInstance(deps, CoordinatorDependencies)
        checked = 0
        for group_type in GROUPS:
            group = getattr(
                deps,
                {
                    PreparationDependencies: "preparation",
                    AvailabilityDependencies: "availability",
                    ModelDependencies: "model",
                    ReadyDependencies: "ready",
                    LoopDependencies: "loop",
                }[group_type],
            )
            hints = _resolved_hints(dependencies, group_type)
            for item in dataclasses.fields(group_type):
                value = getattr(group, item.name)
                hint, _optional = _unwrap_optional(hints[item.name])
                label = f"{group_type.__name__}.{item.name}"
                with self.subTest(field=label):
                    self._check_value(label, hint, value)
                    checked += 1
        self.assertEqual(checked, 58)

        hints = _resolved_hints(dependencies, CoordinatorDependencies)
        for name in ("tool_run_factory", "offline_tool_runner"):
            hint, optional = _unwrap_optional(hints[name])
            self.assertTrue(optional)
            with self.subTest(field=name):
                _assert_satisfies(self, name, hint, getattr(deps, name))

    def _check_value(self, label: str, hint: object, value: object) -> None:
        origin = typing.get_origin(hint)
        if _is_callable_port(hint) or origin is collections.abc.Callable:
            _assert_satisfies(self, label, hint, value)
        elif origin is type:
            (target,) = typing.get_args(hint)
            self.assertIsInstance(value, type, label)
            if getattr(target, "_is_protocol", False):
                members = {
                    name
                    for name, item in vars(target).items()
                    if isinstance(item, property)
                }
                self.assertLessEqual(
                    members, {item.name for item in dataclasses.fields(value)}, label
                )
            else:
                self.assertTrue(issubclass(value, target), label)
        elif origin in (list, dict):
            self.assertIsInstance(value, origin, label)
        else:
            # Plain classes and runtime-checkable Protocols such as ModelGatewayPort.
            self.assertIsInstance(value, hint, label)

    def test_legacy_channels_satisfy_event_ports(self):
        _assert_satisfies(self, "audit.emit", ports.AuditEmitter, audit.emit)
        _assert_satisfies(
            self, "telemetry.notify", ports.ProgressSink, telemetry.notify
        )
        _assert_satisfies(self, "service._notify", ports.ProgressSink, agent._notify)
        _assert_satisfies(
            self, "service._stream_answer", ports.AnswerStreamer, agent._stream_answer
        )
        _assert_satisfies(
            self, "health", ports.ModelHealthReader, agent.get_model_health
        )
        _assert_satisfies(self, "claim", ports.ModelCallClaimer, agent.claim_model_call)
        _assert_satisfies(
            self, "success", ports.ModelSuccessRecorder, agent.record_model_success
        )
        _assert_satisfies(
            self, "failure", ports.ModelFailureRecorder, agent.record_model_failure
        )
        for name in (
            "_retryable_model_error",
            "_model_error_category",
            "_model_failure_reason",
        ):
            with self.subTest(name=name):
                hint = (
                    ports.ModelErrorPredicate
                    if name == "_retryable_model_error"
                    else ports.ModelErrorClassifier
                )
                _assert_satisfies(self, name, hint, getattr(agent, name))
        _assert_satisfies(
            self, "_model_retry_delay", ports.ModelRetryDelay, agent._model_retry_delay
        )

    def test_stage_loop_context_receives_assignable_dependency_types(self):
        # stages/loop.py forwards these dependency fields into AgentLoopContext.
        loop_hints = _resolved_hints(agent_loop, AgentLoopContext)
        group_hints: dict[str, object] = {}
        for group_type in GROUPS:
            group_hints.update(_resolved_hints(dependencies, group_type))
        same = {
            "notify": "notify",
            "stream_answer": "stream_answer",
            "emit_event": "emit",
            "model_gateway": "model_gateway",
            "record_model_success": "record_model_success",
            "record_model_failure": "record_model_failure",
            "execute_tool": "execute_registered_tool",
            "knowledge_fallback_state": "knowledge_fallback_state",
            "validate_evidence": "validate_evidence",
            "create_answer_contract": "create_answer_contract",
            "validator_system_message": "validator_system_message",
            "synthesizer_system_message": "synthesizer_system_message",
            "synthesize_legacy_answer": "synthesize_legacy_answer",
            "synthesize_submission": "synthesize_submission",
            "emit_answer_synthesis": "emit_answer_synthesis",
            "offline_answer": "offline_answer",
            "evidence_observation_type": "evidence_observation_type",
            "request_synthesis_correction": "request_synthesis_correction",
        }
        for context_field, dependency_field in same.items():
            with self.subTest(field=context_field):
                self.assertEqual(
                    loop_hints[context_field], group_hints[dependency_field]
                )


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def __call__(
        self, event: str, run_id: str, *, full_content=None, **fields: object
    ) -> None:
        self.calls.append((event, run_id, fields))


class AuditEventSinkTests(unittest.IsolatedAsyncioTestCase):
    def _events(self) -> tuple[RuntimeEvent, RuntimeEvent]:
        model = RuntimeEvent(
            run_id="run-1",
            call_id="model-1",
            kind="model_response",
            status=ToolStatus.SUCCEEDED,
            usage=ModelUsage(2, 3, 5),
        )
        tool = RuntimeEvent(
            run_id="run-1",
            call_id="tool-1",
            kind="tool_result",
            status=ToolStatus.SUCCEEDED,
            tool_name="get_equipment_health",
            row_count=4,
            execution_state=ToolExecutionState.COMPLETED,
        )
        return model, tool

    async def test_forwards_model_and_tool_events_with_fixed_fields(self):
        recorder = _Recorder()
        sink = AuditEventSink(recorder)
        model, tool = self._events()
        await publish_stage_event(model, sink=sink)
        await sink.emit(tool)

        self.assertEqual(RUNTIME_STAGE_AUDIT_EVENT, "runtime_stage_completed")
        self.assertEqual(
            recorder.calls,
            [
                (
                    "runtime_stage_completed",
                    "run-1",
                    {
                        "call_id": "model-1",
                        "kind": "model_response",
                        "status": "succeeded",
                        "runtime_event_schema_version": "1.0.0",
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                ),
                (
                    "runtime_stage_completed",
                    "run-1",
                    {
                        "call_id": "tool-1",
                        "kind": "tool_result",
                        "status": "succeeded",
                        "runtime_event_schema_version": "1.0.0",
                        "tool_name": "get_equipment_health",
                        "row_count": 4,
                        "execution_state": "completed",
                    },
                ),
            ],
        )
        self.assertEqual(
            list(recorder.calls[1][2]),
            [
                "call_id",
                "kind",
                "status",
                "runtime_event_schema_version",
                "tool_name",
                "row_count",
                "execution_state",
            ],
        )
        self.assertEqual(runtime_event_audit_fields(tool), recorder.calls[1][2])

    async def test_failed_tool_event_keeps_none_row_count_and_state(self):
        recorder = _Recorder()
        event = RuntimeEvent(
            run_id="run-2",
            call_id="tool-2",
            kind="tool_result",
            status=ToolStatus.DENIED,
            tool_name="query_enterprise_data",
            execution_state=ToolExecutionState.NOT_STARTED,
        )
        await AuditEventSink(recorder).emit(event)
        self.assertEqual(recorder.calls[0][2]["status"], "denied")
        self.assertIsNone(recorder.calls[0][2]["row_count"])
        self.assertEqual(recorder.calls[0][2]["execution_state"], "not_started")

    async def test_emitter_failure_propagates(self):
        def broken(*_args, **_kwargs):
            raise OSError("audit log unavailable")

        model, _tool = self._events()
        with self.assertRaisesRegex(OSError, "audit log unavailable"):
            await publish_stage_event(model, sink=AuditEventSink(broken))

    async def test_real_audit_emit_keeps_envelope_schema_and_runtime_version(self):
        logger = MagicMock()
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.object(audit, "_logger", logger),
            patch.object(audit, "RUN_LOG_DIR", Path(raw)),
        ):
            await AuditEventSink(audit.emit).emit(self._events()[1])
        record = json.loads(logger.info.call_args.args[0])
        self.assertEqual(record["event"], "runtime_stage_completed")
        self.assertEqual(record["run_id"], "run-1")
        self.assertEqual(record["schema_version"], audit.SCHEMA_VERSION)
        self.assertEqual(record["runtime_event_schema_version"], "1.0.0")
        self.assertEqual(record["execution_state"], "completed")

    def test_sink_satisfies_event_sink_port_and_is_not_wired_by_default(self):
        sink = AuditEventSink(_Recorder())
        self.assertTrue(inspect.iscoroutinefunction(sink.emit))
        self.assertEqual(list(inspect.signature(sink.emit).parameters), ["event"])
        users = sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "app").rglob("*.py")
            if "AuditEventSink" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(users, ["app/agent_runtime/telemetry.py"])


class LightImportTests(unittest.TestCase):
    def test_dependency_types_add_no_heavy_runtime_imports(self):
        code = (
            "import json, sys\n"
            "before = set(sys.modules)\n"
            "import app.agent_runtime.dependencies, app.agent_runtime.coordinator_state\n"
            "first = sorted(set(sys.modules) - before)\n"
            "import app.agent_runtime.ports\n"
            "second = sorted(set(sys.modules) - before)\n"
            "print(json.dumps([first, second]))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = json.loads(result.stdout)
        baseline = {
            "app",
            "app.agent_runtime",
            "app.agent_runtime.contracts",
            "app.agent_runtime.coordinator",
            "app.agent_runtime.coordinator_state",
            "app.agent_runtime.dependencies",
            "app.agent_runtime.stages",
            # Prompt truncation helpers are pure stdlib (json/dataclasses) and
            # are deliberately pulled in by the loop stage's tool messages.
            "app.core",
            "app.core.tool_result_projection",
            *(
                f"app.agent_runtime.stages.{name}"
                for name in ("availability", "loop", "model", "prepare", "ready")
            ),
        }
        self.assertEqual({name for name in first if name.startswith("app")}, baseline)
        self.assertEqual(
            {name for name in second if name.startswith("app")},
            baseline | {"app.agent_runtime.ports"},
        )
        for name in second:
            with self.subTest(module=name):
                self.assertNotIn(name.split(".")[0], {"httpx", "sqlite3", "_sqlite3"})
                self.assertFalse(
                    name.startswith(
                        (
                            "app.model_gateway",
                            "app.persistence",
                            "app.core.settings",
                            "app.telemetry",
                        )
                    ),
                    name,
                )


if __name__ == "__main__":
    unittest.main()
