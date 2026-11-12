"""MOD-015d storage/identity Port contract, installer and delegation checks."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.bootstrap.storage_identity_assembly import (
    DEFAULT_STORAGE_IDENTITY_BINDINGS,
    install_default_storage_identity,
)
from app.conversation import sessions
from app.core import model_capabilities
from app.core.identity import Principal, reset_principal, set_principal
from app.core.storage_identity_ports import (
    INSTALLER_NAME,
    PrincipalView,
    StorageIdentityBindings,
    configured_storage_identity,
    install_storage_identity,
    reset_storage_identity,
    storage_identity_bindings,
)
from app.knowledge import rag, search_query, search_registry, sqlite_backend
from app.model_gateway import health, registry
from app.personal_knowledge_runtime import service as personal_service
from app.telemetry import runtime_status
from scripts.check_module_boundaries import imported_modules

PROJECT_DIR = Path(__file__).resolve().parents[1]
REMOVED_EDGES = {
    "app/conversation/sessions.py": {
        "app.persistence.database",
        "app.persistence.execution_store",
        "app.core.identity",
    },
    "app/knowledge/rag.py": {
        "app.persistence.database",
        "app.core.identity",
        "app.knowledge.sqlite_backend",
    },
    "app/knowledge/search_registry.py": {"app.knowledge.sqlite_backend"},
    "app/model_gateway/health.py": {"app.persistence.database"},
    "app/model_gateway/registry.py": {"app.persistence.database", "app.core.identity"},
    "app/persistence/database.py": {"app.model_gateway.registry"},
    "app/personal_knowledge_runtime/service.py": {
        "app.telemetry.audit",
        "app.persistence.database",
    },
    "app/telemetry/runtime_status.py": {
        "app.persistence.database",
        "app.core.identity",
    },
}


def _run_python(code: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as directory:
        env = {
            **os.environ,
            "AGENT_LOG_PATH": str(Path(directory) / "events.jsonl"),
            "AGENT_RUN_LOG_DIR": str(Path(directory) / "runs"),
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env=env,
        )


class _Cursor:
    rowcount = 1
    lastrowid = 1

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, log: list) -> None:
        self.log = log

    def execute(self, sql, parameters=()):
        self.log.append(("execute", " ".join(str(sql).split())[:60], parameters))
        return _Cursor()

    def commit(self):
        self.log.append(("commit",))


class _Backend:
    def defect_aliases(self, principal):
        return {}

    def search(self, principal, request):
        return []


def _fake_bindings(log: list, principal: Principal) -> StorageIdentityBindings:
    @contextmanager
    def session():
        log.append(("session",))
        yield _Connection(log)

    backend = _Backend()
    return StorageIdentityBindings(
        session_factory=session,
        current_principal=lambda: principal,
        defect_alias_reader=lambda: {"Bridge": ("fake-bridge",)},
        audit_emit=lambda event, run_id, **fields: log.append(
            ("emit", event, run_id, fields)
        ),
        executions_for_session=lambda connection, session_id: (
            log.append(("executions", session_id)) or {}
        ),
        reconcile_plan_steps=lambda run_id, trace, *, connection=None: (
            log.append(("reconcile", run_id, len(trace), connection is not None)) or 0
        ),
        factory_search_backend_factory=lambda: backend,
    )


class StorageIdentityPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous = configured_storage_identity()

    def tearDown(self) -> None:
        reset_storage_identity()
        if self._previous is not None:
            install_storage_identity(self._previous)

    def test_port_and_capability_modules_import_only_stdlib(self) -> None:
        for module in (
            "app.core.storage_identity_ports",
            "app.core.model_capabilities",
        ):
            with self.subTest(module=module):
                result = _run_python(
                    "import json, sys\n"
                    f"import {module}\n"
                    "print(json.dumps(sorted(m for m in sys.modules if m == 'app' or m.startswith('app.'))))\n"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                loaded = set(json.loads(result.stdout.strip().splitlines()[-1]))
                self.assertEqual(loaded, {"app", "app.core", module})

    def test_unconfigured_consumers_fail_with_installer_name(self) -> None:
        code = """
import json
from app.conversation import sessions
from app.knowledge import rag, search_registry
from app.model_gateway import health, registry
from app.personal_knowledge_runtime import service
from app.telemetry import runtime_status
from app.core.storage_identity_ports import StorageIdentityNotConfiguredError
calls = {
    "sessions.db_session": lambda: sessions.db_session(),
    "sessions.current_principal": lambda: sessions.current_principal(),
    "sessions.list_sessions": lambda: sessions.list_sessions(),
    "rag.current_principal": lambda: rag.current_principal(),
    "rag.get_active_defect_aliases": lambda: rag.get_active_defect_aliases(),
    "search_registry.sqlite": lambda: search_registry.get_factory_search_backend("sqlite"),
    "health.get_model_health": lambda: health.get_model_health("model"),
    "registry.list_models": lambda: registry.list_models(),
    "registry.current_principal": lambda: registry.current_principal(),
    "service.pending_personal_jobs": lambda: service.pending_personal_jobs(),
    "service.emit": lambda: service.emit("event", "run"),
    "runtime_status.admin_runtime_overview": lambda: runtime_status.admin_runtime_overview(),
}
outcome = {}
for name, call in calls.items():
    try:
        call()
    except StorageIdentityNotConfiguredError as error:
        outcome[name] = str(error)
    else:
        outcome[name] = None
import sys
outcome["_runtime_dependencies_loaded"] = "app.api.runtime_dependencies" in sys.modules
print(json.dumps(outcome))
"""
        result = _run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(outcome.pop("_runtime_dependencies_loaded"))
        self.assertEqual(len(outcome), 12)
        for name, message in outcome.items():
            with self.subTest(name=name):
                self.assertIsNotNone(message)
                self.assertIn(INSTALLER_NAME, message)

    def test_composition_roots_install_the_default_bindings(self) -> None:
        for module in ("app.main", "app.agent_runtime.service"):
            with self.subTest(module=module):
                result = _run_python(
                    f"import {module}\n"
                    "from app.core.storage_identity_ports import configured_storage_identity\n"
                    "from app.bootstrap.storage_identity_assembly import DEFAULT_STORAGE_IDENTITY_BINDINGS\n"
                    "print(configured_storage_identity() is DEFAULT_STORAGE_IDENTITY_BINDINGS)\n"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip().splitlines()[-1], "True")

    def test_default_installer_is_idempotent_and_keeps_custom_bindings(self) -> None:
        reset_storage_identity()
        self.assertIs(
            install_default_storage_identity(), DEFAULT_STORAGE_IDENTITY_BINDINGS
        )
        self.assertIs(
            install_default_storage_identity(), DEFAULT_STORAGE_IDENTITY_BINDINGS
        )
        self.assertIs(storage_identity_bindings(), DEFAULT_STORAGE_IDENTITY_BINDINGS)
        custom = _fake_bindings([], Principal("tenant", "user"))
        install_storage_identity(custom)
        self.assertIs(install_default_storage_identity(), custom)
        self.assertIs(storage_identity_bindings(), custom)
        with self.assertRaises(TypeError):
            install_storage_identity(object())  # type: ignore[arg-type]

    def test_consumers_delegate_to_installed_bindings_at_call_time(self) -> None:
        log: list = []
        principal = Principal("tenant-x", "user-y", ("reviewer",))
        install_storage_identity(_fake_bindings(log, principal))

        created = sessions.create_session("title")
        self.assertEqual(created["title"], "title")
        self.assertIs(sessions.current_principal(), principal)
        insert = next(item for item in log if item[0] == "execute")
        self.assertEqual(insert[2][1:3], ("tenant-x", "user-y"))
        self.assertEqual(sessions.executions_for_session("connection", "session"), {})
        self.assertEqual(sessions.reconcile_plan_steps("run", [{}], connection="c"), 0)
        self.assertIn(("executions", "session"), log)
        self.assertIn(("reconcile", "run", 1, True), log)

        log.clear()
        self.assertEqual(
            registry.validate_model_definition(
                "model-a", "Model A", "deepseek", "provider-a", "https://model.test/"
            ),
            ("model-a", "Model A", "provider-a", "https://model.test"),
        )
        self.assertIs(registry.current_principal(), principal)
        self.assertEqual(log[0], ("session",))

        log.clear()
        overview = runtime_status.admin_runtime_overview()
        self.assertEqual(overview["recent_runs"], [])
        self.assertEqual(log[0], ("session",))

        log.clear()
        self.assertEqual(personal_service.pending_personal_jobs(), [])
        personal_service.emit("personal_event", "job", status="ok")
        self.assertEqual(log[0], ("session",))
        self.assertEqual(log[-1], ("emit", "personal_event", "job", {"status": "ok"}))

        log.clear()
        self.assertIs(rag.current_principal(), principal)
        self.assertEqual(
            rag._infer_filters("fake-bridge", None, None, None)["defect_type"], "Bridge"
        )
        self.assertIsInstance(
            search_registry.get_factory_search_backend("sqlite"), _Backend
        )

        log.clear()
        health.ensure_model_health("model-a")
        self.assertEqual(log[0], ("session",))
        self.assertEqual(log[-1], ("commit",))

    def test_real_principal_satisfies_principal_view(self) -> None:
        self.assertIsInstance(Principal("tenant", "user"), PrincipalView)

    def test_moved_pure_helpers_are_reexported_as_the_same_objects(self) -> None:
        self.assertIs(
            registry.normalize_capabilities, model_capabilities.normalize_capabilities
        )
        self.assertIs(
            registry.MODEL_CAPABILITY_DEFAULTS,
            model_capabilities.MODEL_CAPABILITY_DEFAULTS,
        )
        self.assertIs(sqlite_backend.sqlite_fts_query, search_query.sqlite_fts_query)
        self.assertIs(rag.sqlite_fts_query, search_query.sqlite_fts_query)
        self.assertEqual(
            rag._fts_query("LITHO overlay"),
            search_query.sqlite_fts_query("LITHO overlay"),
        )

    def test_removed_storage_identity_import_edges_stay_absent(self) -> None:
        app_dir = PROJECT_DIR / "app"
        for relative, removed in REMOVED_EDGES.items():
            with self.subTest(path=relative):
                path = PROJECT_DIR / relative
                ast.parse(path.read_text(encoding="utf-8"))
                targets = {edge.target for edge in imported_modules(path, app_dir)}
                self.assertEqual(targets & removed, set())
                if relative != "app/persistence/database.py":
                    self.assertIn("app.core.storage_identity_ports", targets)

    def test_concrete_patches_reach_consumers_through_the_default_binding(self) -> None:
        reset_storage_identity()
        install_default_storage_identity()
        log: list = []

        @contextmanager
        def patched_session(path=None):
            log.append(("session",))
            yield _Connection(log)

        with patch("app.demo_data.database.db_session", patched_session):
            self.assertEqual(sessions.list_sessions(), [])
            health.ensure_model_health("patched")
            self.assertEqual(personal_service.pending_personal_jobs(), [])
        self.assertEqual(
            [item for item in log if item == ("session",)], [("session",)] * 3
        )

        principal = Principal("tenant-p", "user-p")
        with patch("app.core.identity.current_principal", return_value=principal):
            self.assertIs(rag.current_principal(), principal)
            self.assertIs(sessions.current_principal(), principal)
        token = set_principal(Principal("tenant-c", "user-c"))
        try:
            self.assertEqual(registry.current_principal().tenant_id, "tenant-c")
            self.assertEqual(sessions._scope(), ("tenant-c", "user-c"))
        finally:
            reset_principal(token)
        with patch(
            "app.demo_data.database.get_active_defect_aliases",
            return_value={"Gate": ("gate-x",)},
        ):
            self.assertEqual(rag.get_active_defect_aliases(), {"Gate": ("gate-x",)})
        with patch("app.knowledge.sqlite_backend.SqliteFactorySearchBackend", _Backend):
            self.assertIsInstance(
                search_registry.get_factory_search_backend("sqlite"), _Backend
            )

    def test_legacy_module_patch_points_still_win(self) -> None:
        reset_storage_identity()
        install_default_storage_identity()
        principal = Principal("tenant-l", "user-l")
        with patch.object(rag, "current_principal", return_value=principal):
            self.assertIs(rag.current_principal(), principal)
        with patch.object(
            rag, "get_active_defect_aliases", return_value={"Bridge": ("legacy",)}
        ):
            self.assertEqual(
                rag._infer_filters("legacy", None, None, None)["defect_type"], "Bridge"
            )
        marker = object()
        with patch("app.personal_knowledge_runtime.service.db_session", marker):
            self.assertIs(personal_service._document_dependencies().db_session, marker)
            self.assertIs(personal_service._search_dependencies().db_session, marker)
        original = health.db_session
        with patch.object(health, "db_session", marker):
            self.assertIs(health.db_session, marker)
        self.assertIs(health.db_session, original)
        self.assertEqual(sessions._scope.__module__, "app.conversation.sessions")


if __name__ == "__main__":
    unittest.main()
