"""Composition root for the default storage and identity bindings.

Each binding resolves the concrete module attribute at call time, so existing
patches such as ``patch("app.demo_data.database.db_session")`` or a
``set_principal`` context keep reaching every consumer.
"""

from __future__ import annotations

from typing import Any

from ..core import identity
from ..core.storage_identity_ports import (
    StorageIdentityBindings,
    install_storage_identity,
)
from ..knowledge import sqlite_backend
from ..demo_data import database
from ..persistence import execution_store
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


DEFAULT_STORAGE_IDENTITY_BINDINGS = StorageIdentityBindings(
    session_factory=_session_factory,
    current_principal=_current_principal,
    defect_alias_reader=_defect_aliases,
    audit_emit=_audit_emit,
    executions_for_session=_executions_for_session,
    reconcile_plan_steps=_reconcile_plan_steps,
    factory_search_backend_factory=_sqlite_factory_search_backend,
)


def install_default_storage_identity() -> StorageIdentityBindings:
    """Install the default bindings unless a composition root already installed some."""
    return install_storage_identity(DEFAULT_STORAGE_IDENTITY_BINDINGS, replace=False)


__all__ = ["DEFAULT_STORAGE_IDENTITY_BINDINGS", "install_default_storage_identity"]
