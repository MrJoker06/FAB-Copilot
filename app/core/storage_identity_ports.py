"""Narrow storage and identity Ports consumed by session, knowledge, model and telemetry code.

Consumers depend on this stdlib-only contract instead of importing the SQLite
store, the execution store, the audit sink or the request identity context.  The
application composition root installs concrete bindings explicitly; nothing is
installed at import time, so an unassembled consumer fails with a clear error
instead of silently opening a database.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

INSTALLER_NAME = (
    "app.bootstrap.storage_identity_assembly.install_default_storage_identity"
)


@runtime_checkable
class PrincipalView(Protocol):
    """Read-only identity facts consumers may rely on."""

    @property
    def tenant_id(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def roles(self) -> tuple[str, ...]: ...

    @property
    def knowledge_owner_id(self) -> str: ...


SessionFactory = Callable[[], AbstractContextManager[Any]]
PrincipalProvider = Callable[[], PrincipalView]
DefectAliasReader = Callable[[], Mapping[str, Sequence[str]]]
AuditEmitter = Callable[..., None]
ExecutionsForSession = Callable[[Any, str], dict]
PlanStepReconciler = Callable[..., int]
FactorySearchBackendFactory = Callable[[], Any]


@dataclass(frozen=True)
class StorageIdentityBindings:
    session_factory: SessionFactory
    current_principal: PrincipalProvider
    defect_alias_reader: DefectAliasReader
    audit_emit: AuditEmitter
    executions_for_session: ExecutionsForSession
    reconcile_plan_steps: PlanStepReconciler
    factory_search_backend_factory: FactorySearchBackendFactory


class StorageIdentityNotConfiguredError(RuntimeError):
    """Raised when a consumer runs before the composition root installed bindings."""


_lock = threading.Lock()
_bindings: StorageIdentityBindings | None = None


def install_storage_identity(
    bindings: StorageIdentityBindings, *, replace: bool = True
) -> StorageIdentityBindings:
    """Install ``bindings`` and return the active bindings.

    With ``replace=False`` an existing installation is kept, which lets the
    default assembly stay idempotent without overriding a custom composition.
    """
    global _bindings
    if not isinstance(bindings, StorageIdentityBindings):
        raise TypeError("storage/identity bindings must be StorageIdentityBindings")
    with _lock:
        if replace or _bindings is None:
            _bindings = bindings
        return _bindings


def configured_storage_identity() -> StorageIdentityBindings | None:
    return _bindings


def storage_identity_bindings() -> StorageIdentityBindings:
    bindings = _bindings
    if bindings is None:
        raise StorageIdentityNotConfiguredError(
            "storage/identity bindings are not configured; call "
            f"{INSTALLER_NAME}() from the composition root before using "
            "session, knowledge, model registry/health, personal knowledge or "
            "runtime status consumers"
        )
    return bindings


def reset_storage_identity() -> None:
    """Clear the installed bindings (test isolation only)."""
    global _bindings
    with _lock:
        _bindings = None


__all__ = [
    "AuditEmitter",
    "DefectAliasReader",
    "ExecutionsForSession",
    "FactorySearchBackendFactory",
    "INSTALLER_NAME",
    "PlanStepReconciler",
    "PrincipalProvider",
    "PrincipalView",
    "SessionFactory",
    "StorageIdentityBindings",
    "StorageIdentityNotConfiguredError",
    "configured_storage_identity",
    "install_storage_identity",
    "reset_storage_identity",
    "storage_identity_bindings",
]
