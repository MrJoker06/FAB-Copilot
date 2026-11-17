from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.bootstrap.storage_identity_assembly import DEFAULT_STORAGE_IDENTITY_BINDINGS
from app.conversation import sessions
from app.conversation.result_lifecycle import (
    SessionResultCleanupPending,
    recover_result_deletions,
    session_results_permitted,
)
from app.core.storage_identity_ports import (
    configured_storage_identity,
    install_storage_identity,
    reset_storage_identity,
)
from app.demo_data import database
from app.persistence.tool_result_store import ResultStoreError, ToolResultStore
from tests.test_persistence_separation import storage_environment


class SessionResultLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, storage_environment(Path(self.temp.name)))
        env.start()
        self.addCleanup(env.stop)
        previous = configured_storage_identity()
        self.addCleanup(
            lambda: (
                install_storage_identity(previous)
                if previous is not None
                else reset_storage_identity()
            )
        )
        self.store = ToolResultStore(Path(self.temp.name) / "results.db")
        self.store.initialize()
        self.bindings = replace(
            DEFAULT_STORAGE_IDENTITY_BINDINGS, result_store_factory=lambda: self.store
        )
        install_storage_identity(self.bindings)
        database.initialize()
        self.session = sessions.create_session()["session_id"]
        principal = self.bindings.current_principal()
        self.scope = {
            "tenant_id": principal.tenant_id,
            "owner_id": principal.user_id,
            "session_id": self.session,
        }
        self.ref = self.store.save(
            **self.scope,
            run_id="run",
            call_id="call",
            metadata={"queried_at": "2026-11-15"},
            content=[{"value": 7}],
            permit=lambda: True,
        )

    def test_archive_restore_and_run_end_do_not_remove_result(self):
        sessions.archive_session(self.session)
        self.assertTrue(sessions.get_session(self.session)["archived_at"])
        self.assertEqual(
            self.store.read(**self.scope, result_ref=self.ref, permit=lambda: True)[
                "units"
            ],
            [{"value": 7}],
        )
        sessions.restore_session(self.session)
        self.assertIsNone(sessions.get_session(self.session)["archived_at"])

    def test_permanent_deletion_removes_session_and_revokes_late_results(self):
        self.assertTrue(sessions.delete_session_permanently(self.session)["deleted"])
        with self.assertRaises(ValueError):
            sessions.get_session(self.session)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.store.read(**self.scope, result_ref=self.ref, permit=lambda: True)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.store.save(
                **self.scope,
                run_id="late",
                call_id="late",
                metadata={},
                content=[1],
                permit=lambda: True,
            )
        self.assertEqual(
            sessions.delete_sessions_permanently([self.session])["deleted_count"], 0
        )

    def test_cleanup_failure_blocks_session_and_is_recovered_from_durable_intent(self):
        with patch.object(
            self.store,
            "revoke_session",
            side_effect=OSError("private DB path must not escape"),
        ):
            with self.assertRaises(SessionResultCleanupPending) as caught:
                sessions.delete_session_permanently(self.session)
            self.assertNotIn("private", str(caught.exception))
        self.assertFalse(
            session_results_permitted(
                self.session, self.scope["tenant_id"], self.scope["owner_id"]
            )
        )
        self.assertFalse(sessions.list_sessions())
        with self.assertRaises(ValueError):
            sessions.append_message(self.session, "user", "late message")
        with self.assertRaises(ValueError):
            sessions.session_history(self.session)
        recover_result_deletions()
        with database.db_session() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM session_result_deletions WHERE session_id=?",
                    (self.session,),
                ).fetchone()[0],
                "completed",
            )
        recover_result_deletions()
        with self.assertRaises(ResultStoreError):
            self.store.read(**self.scope, result_ref=self.ref, permit=lambda: True)

    def test_cleanup_commit_then_session_delete_failure_recovers_without_result_revival(
        self,
    ):
        with database.db_session() as connection:
            connection.execute(
                "CREATE TRIGGER agent.reject_session_delete BEFORE DELETE ON chat_sessions BEGIN SELECT RAISE(ABORT,'injected delete failure'); END"
            )
            connection.commit()
        with self.assertRaises(SessionResultCleanupPending):
            sessions.delete_session_permanently(self.session)
        with database.db_session() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM chat_sessions WHERE session_id=?",
                    (self.session,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM session_result_deletions WHERE session_id=?",
                    (self.session,),
                ).fetchone()[0],
                "pending",
            )
        # The result transaction committed before the main DB failure. The
        # surviving session is blocked and cannot revive content on retry.
        self.assertFalse(
            session_results_permitted(
                self.session, self.scope["tenant_id"], self.scope["owner_id"]
            )
        )
        with self.assertRaises(ResultStoreError):
            ToolResultStore(self.store.path).read(
                **self.scope, result_ref=self.ref, permit=lambda: True
            )
        with self.assertRaises(ResultStoreError):
            self.store.save(
                **self.scope,
                run_id="late",
                call_id="late",
                metadata={},
                content=[2],
                permit=lambda: True,
            )
        with database.db_session() as connection:
            connection.execute("DROP TRIGGER agent.reject_session_delete")
            connection.commit()
        recover_result_deletions()
        recover_result_deletions()
        with database.db_session() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM chat_sessions WHERE session_id=?",
                    (self.session,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM session_result_deletions WHERE session_id=?",
                    (self.session,),
                ).fetchone()[0],
                "completed",
            )

    def test_batch_reports_partial_failure_without_deleting_unowned_sessions(self):
        other = sessions.create_session()["session_id"]
        original = self.store.revoke_session

        def selective(**scope):
            if scope["session_id"] == self.session:
                raise OSError("injected")
            original(**scope)

        with patch.object(self.store, "revoke_session", side_effect=selective):
            result = sessions.delete_sessions_permanently(
                [self.session, other, "missing"]
            )
        self.assertEqual(result["deleted_session_ids"], [other])
        self.assertEqual(result["failed_session_ids"], [self.session])
        self.assertEqual(result["missing_session_ids"], ["missing"])
        recover_result_deletions()


if __name__ == "__main__":
    unittest.main()
