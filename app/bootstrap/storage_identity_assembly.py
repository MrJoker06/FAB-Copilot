"""Composition root for the default storage and identity bindings.

Each binding resolves the concrete module attribute at call time, so existing
patches such as ``patch("app.demo_data.database.db_session")`` or a
``set_principal`` context keep reaching every consumer.
"""

from __future__ import annotations

from typing import Any

from ..core import identity
from ..core.settings import get_settings
from ..core.storage_identity_ports import (
    StorageIdentityBindings,
    install_storage_identity,
    storage_identity_bindings,
)
from ..knowledge import sqlite_backend
from ..demo_data import database
from ..persistence import execution_store
from ..persistence.tool_result_store import ToolResultStore, ResultStoreError
from ..telemetry import audit


def _session_factory():
    return database.db_session()


def _current_principal():
    return identity.current_principal()


def _defect_aliases():
    return database.get_active_defect_aliases()


def _audit_emit(event: str, run_id: str, **fields: Any) -> None:
    audit.emit(event, run_id, **fields)


def _executions_for_session(connection, session_id: str) -> dict[int, dict]:
    return execution_store.executions_for_session(connection, session_id)


def _reconcile_plan_steps(run_id: str, trace: list[dict], *, connection=None) -> int:
    return execution_store.reconcile_plan_steps(run_id, trace, connection=connection)


def _sqlite_factory_search_backend():
    return sqlite_backend.SqliteFactorySearchBackend()


def result_store():
    """Explicit host operation; importing the assembly never creates the DB."""
    settings = get_settings()
    path = settings.tool_result_database_path or settings.agent_database_path.with_name("tool_results.db")
    known = (settings.database_path, settings.agent_database_path, settings.knowledge_database_path,
             settings.manufacturing_database_path, settings.equipment_database_path, settings.quality_database_path,
             settings.personal_database_path or settings.agent_database_path.with_name("personal_knowledge.db"))
    if any(path.resolve() == item.resolve() or (path.exists() and item.exists() and path.samefile(item)) for item in known):
        raise ResultStoreError("RESULT_STORE_PATH_INVALID")
    store = ToolResultStore(path)
    store.initialize()
    return store


def initialize_result_storage():
    from ..conversation.result_lifecycle import recover_result_deletions
    factory = storage_identity_bindings().result_store_factory
    if factory is not None:
        factory()
    recover_result_deletions()


def configured_result_store():
    factory = storage_identity_bindings().result_store_factory
    if factory is None:
        raise ResultStoreError("RESULT_STORE_UNAVAILABLE")
    return factory()


def _cancel_session_runs(session_id, tenant_id, owner_id):
    from .result_access_assembly import cancel_session_result_runs
    cancel_session_result_runs(session_id, tenant_id, owner_id)


DEFAULT_STORAGE_IDENTITY_BINDINGS = StorageIdentityBindings(
    session_factory=_session_factory,
    current_principal=_current_principal,
    defect_alias_reader=_defect_aliases,
    audit_emit=_audit_emit,
    executions_for_session=_executions_for_session,
    reconcile_plan_steps=_reconcile_plan_steps,
    factory_search_backend_factory=_sqlite_factory_search_backend,
    result_store_factory=result_store,
    cancel_session_runs=_cancel_session_runs,
)


def install_default_storage_identity() -> StorageIdentityBindings:
    """Install the default bindings unless a composition root already installed some."""
    return install_storage_identity(DEFAULT_STORAGE_IDENTITY_BINDINGS, replace=False)


__all__ = ["DEFAULT_STORAGE_IDENTITY_BINDINGS", "install_default_storage_identity"]
