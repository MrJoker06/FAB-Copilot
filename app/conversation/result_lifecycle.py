"""Durable session deletion coordination for the independent result store."""

from __future__ import annotations

from ..core.storage_identity_ports import storage_identity_bindings


class SessionResultCleanupPending(RuntimeError):
    def __init__(self):
        super().__init__("会话结果清理尚未完成，请稍后重试。")


def session_results_permitted(session_id: str, tenant_id: str, owner_id: str) -> bool:
    bindings = storage_identity_bindings()
    with bindings.session_factory() as connection:
        row = connection.execute(
            """SELECT 1 FROM chat_sessions s
               WHERE s.session_id=? AND s.tenant_id=? AND s.owner_user_id=?
                 AND NOT EXISTS (SELECT 1 FROM session_result_deletions d
                   WHERE d.session_id=s.session_id AND d.tenant_id=s.tenant_id
                     AND d.owner_user_id=s.owner_user_id)""",
            (session_id, tenant_id, owner_id),
        ).fetchone()
    return row is not None


def finish_result_deletion(session_id: str, tenant_id: str, owner_id: str) -> None:
    """No agent write transaction is held while acquiring the result-store lock."""
    bindings = storage_identity_bindings()
    factory = bindings.result_store_factory
    if factory is None:
        raise SessionResultCleanupPending()
    try:
        if bindings.cancel_session_runs is not None:
            bindings.cancel_session_runs(session_id, tenant_id, owner_id)
        factory().revoke_session(
            tenant_id=tenant_id, owner_id=owner_id, session_id=session_id
        )
        with bindings.session_factory() as connection:
            connection.execute(
                "DELETE FROM agent.chat_sessions WHERE session_id=? AND tenant_id=? AND owner_user_id=?",
                (session_id, tenant_id, owner_id),
            )
            connection.execute(
                "UPDATE agent.session_result_deletions SET status='completed' WHERE session_id=? AND tenant_id=? AND owner_user_id=?",
                (session_id, tenant_id, owner_id),
            )
            connection.commit()
    except Exception:  # noqa: BLE001 - retain durable intent for any cleanup failure
        raise SessionResultCleanupPending() from None


def recover_result_deletions() -> None:
    bindings = storage_identity_bindings()
    if bindings.result_store_factory is None:
        return
    while True:
        with bindings.session_factory() as connection:
            rows = connection.execute(
                "SELECT session_id,tenant_id,owner_user_id FROM session_result_deletions WHERE status='pending' LIMIT 100"
            ).fetchall()
        if not rows:
            return
        for row in rows:
            finish_result_deletion(row[0], row[1], row[2])
