"""Bind a real Session and independent result store to one runtime invocation."""

from __future__ import annotations

import threading
import weakref

from ..agent_runtime.result_access_run import ResultAccessRun
from ..conversation.result_lifecycle import session_results_permitted
from ..core.storage_identity_ports import storage_identity_bindings

_active = weakref.WeakSet()
_active_lock = threading.Lock()


def cancel_session_result_runs(session_id, tenant_id, owner_id):
    # Cancellation improves local responsiveness; the durable intent and result
    # DB transaction remain the authority across processes and late callbacks.
    with _active_lock:
        runs = tuple(_active)
    for run in runs:
        if (
            run.session_id == session_id
            and run.principal.tenant_id == tenant_id
            and run.principal.user_id == owner_id
        ):
            run.cancel()


def make_result_access_run(session_id, run_id):
    bindings = storage_identity_bindings()
    principal = bindings.current_principal()

    def authorize():
        current = bindings.current_principal()
        return (
            "analyst" in current.roles
            and current.tenant_id == principal.tenant_id
            and current.user_id == principal.user_id
            and session_results_permitted(
                session_id, principal.tenant_id, principal.user_id
            )
        )

    reason = "NO_SESSION"
    store, enabled = None, False
    if session_id:
        reason = "RESULT_UNAVAILABLE"
        try:
            if authorize() and bindings.result_store_factory is not None:
                store = bindings.result_store_factory()
                enabled = store.enabled()
                reason = ""  # False here is an explicit persisted switch value.
        except Exception:  # noqa: BLE001 - backend setup failure is an explicit unavailable state
            reason = "RESULT_STORE_UNAVAILABLE"
    run = ResultAccessRun(
        session_id=session_id,
        run_id=run_id,
        principal=principal,
        store=store,
        enabled=enabled,
        authorize=authorize,
        unavailable_reason=reason,
    )
    with _active_lock:
        _active.add(run)
    return run
