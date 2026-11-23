from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.tool_result_units import canonical_json, result_units
from app.persistence.tool_result_store import (
    ResultStoreError,
    ResultStoreLimits,
    ToolResultStore,
)


class ToolResultStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "results.db"
        self.store = ToolResultStore(self.path)
        self.scope = {
            "tenant_id": "tenant-a", "owner_id": "owner-a", "session_id": "session-a"
        }
        self.meta = {
            "tool": "get_equipment_health",
            "source_ref": "TOOL:S1",
            "queried_at": "2026-11-15T00:00:00+00:00",
            "scope": {"equipment_id": "A", "start": "2026-11-14", "end": "2026-11-14"},
        }
        self.store.initialize()

    def save(self, content, *, call_id="call-a", store=None, **kwargs):
        return (store or self.store).save(
            **self.scope,
            run_id="run-a",
            call_id=call_id,
            metadata=self.meta,
            content=content,
            permit=lambda: True,
            **kwargs,
        )

    def read(self, ref, **kwargs):
        return self.store.read(
            **self.scope, result_ref=ref, permit=lambda: True, **kwargs
        )

    def test_fixed_units_match_hand_written_fixture(self):
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "evaluations/mod_029_result_access_v1.json"
            ).read_text(encoding="utf-8")
        )
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                kind, units = result_units(case["input"])
                self.assertEqual(kind, case["unit_kind"])
                self.assertEqual(units, case["expected_units"])

    def test_commit_restart_and_complete_record_pagination(self):
        expected = [
            {"equipment_id": "A", "value": 0},
            {"equipment_id": "B", "value": 2},
            {"equipment_id": "C", "value": None},
        ]
        ref = self.save(expected)
        first = self.read(ref, limit=2)
        self.assertEqual(first["units"], expected[:2])
        self.assertTrue(first["has_more"])
        self.store = ToolResultStore(self.path)
        self.store.initialize()
        second = self.read(ref, cursor=first["next_cursor"], limit=2)
        self.assertEqual(second["units"], expected[2:])
        self.assertFalse(second["has_more"])
        self.assertEqual(second["queried_at"], self.meta["queried_at"])
        self.assertEqual(second["scope"], self.meta["scope"])

    def test_fragments_reconstruct_long_unicode_record_and_respect_full_byte_budget(
        self,
    ):
        record = {"message": '中文组合e\u0301"\n' * 300}
        expected = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        ref = self.save([record])
        cursor, fragments, last_offset = None, [], 0
        for _ in range(100):
            page = self.read(ref, cursor=cursor, max_bytes=1000)
            self.assertLessEqual(len(canonical_json(page).encode("utf-8")), 1000)
            self.assertEqual(page["format"], "unit_fragment")
            self.assertEqual(page["start_char"], last_offset)
            self.assertGreater(page["end_char"], last_offset)
            last_offset = page["end_char"]
            fragments.append(page["text"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        else:
            self.fail("fragment pagination did not terminate")
        self.assertEqual("".join(fragments), expected)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_RESPONSE_LIMIT"):
            self.read(ref, max_bytes=8)

    def test_duplicate_call_is_immutable_and_does_not_consume_another_slot(self):
        self.store = ToolResultStore(self.path, limits=ResultStoreLimits(total_count=1))
        ref = self.save([1])
        self.assertEqual(self.save([1]), ref)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_CALL_CONFLICT"):
            self.save([2])
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORAGE_LIMIT"):
            self.save([1], call_id="call-b")
        self.assertEqual(self.read(ref)["units"], [1])

    def test_all_byte_and_count_quotas_reject_without_evicting(self):
        for name in (
            "snapshot_bytes",
            "run_bytes",
            "session_bytes",
            "total_bytes",
            "run_count",
            "session_count",
            "total_count",
        ):
            with self.subTest(limit=name):
                path = Path(self.temp.name) / (name + ".db")
                limit = 1 if name.endswith("count") else 1000
                store = ToolResultStore(path, limits=ResultStoreLimits(**{name: limit}))
                store.initialize()
                ref = self.save([0], store=store)
                with self.assertRaisesRegex(ResultStoreError, "RESULT_STORAGE_LIMIT"):
                    self.save(["x" * 1500], call_id="call-b", store=store)
                self.assertEqual(
                    store.read(**self.scope, result_ref=ref, permit=lambda: True)[
                        "units"
                    ],
                    [0],
                )

    def test_concurrent_capacity_claims_do_not_oversell(self):
        store = ToolResultStore(self.path, limits=ResultStoreLimits(total_count=1))

        def publish(number):
            try:
                return self.save([number], call_id=str(number), store=store)
            except ResultStoreError as exc:
                return exc.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(publish, range(4)))
        self.assertEqual(sum(item.startswith("tr_") for item in results), 1)
        self.assertEqual(results.count("RESULT_STORAGE_LIMIT"), 3)

    def test_session_revocation_removes_content_and_rejects_late_publish(self):
        ref = self.save([1])
        self.store.revoke_session(**self.scope)
        self.store.revoke_session(**self.scope)
        self.store = ToolResultStore(self.path)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.read(ref)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.save([2], call_id="late")
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM tool_result_snapshots"
                ).fetchone()[0],
                0,
            )

    def test_live_permission_and_scope_checked_for_each_page(self):
        ref = self.save([1, 2])
        cursor = self.read(ref, limit=1)["next_cursor"]
        for changed in (
            {"tenant_id": "other"},
            {"owner_id": "other"},
            {"session_id": "other"},
        ):
            with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
                self.store.read(
                    **{**self.scope, **changed}, result_ref=ref, permit=lambda: True
                )
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.store.read(
                **self.scope, result_ref=ref, permit=lambda: False, cursor=cursor
            )

    def test_signed_cursor_rejects_tampering_and_cross_reference_reuse(self):
        ref = self.save([1, 2])
        other = self.save([3, 4], call_id="other")
        cursor = self.read(ref, limit=1)["next_cursor"]
        for bad in (
            cursor[:-1] + ("a" if cursor[-1] != "a" else "b"),
            "not-a-cursor",
            "",
        ):
            with self.assertRaisesRegex(ResultStoreError, "RESULT_CURSOR_INVALID"):
                self.read(ref, cursor=bad)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_CURSOR_INVALID"):
            self.read(other, cursor=cursor)
        for bad_limit in (True, 0, -1, 51, 1.5):
            with self.assertRaisesRegex(ResultStoreError, "RESULT_INVALID"):
                self.read(ref, limit=bad_limit)

    def test_configuration_is_persistent_and_does_not_delete_snapshots(self):
        ref = self.save([1])
        self.assertTrue(self.store.enabled())
        self.store.set_enabled(False)
        self.store = ToolResultStore(self.path)
        self.store.initialize()
        self.assertFalse(self.store.enabled())
        self.store.set_enabled(True)
        self.assertEqual(self.read(ref)["units"], [1])
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORE_CONFIG_INVALID"):
            self.store.set_enabled(1)

    def test_explicit_initialization_and_existing_database_refusal(self):
        missing = Path(self.temp.name) / "missing.db"
        store = ToolResultStore(missing)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORE_UNAVAILABLE"):
            store.enabled()
        self.assertFalse(missing.exists())
        unrelated = Path(self.temp.name) / "business.db"
        with closing(sqlite3.connect(unrelated)) as connection:
            connection.execute("CREATE TABLE protected(value TEXT)")
        before = unrelated.read_bytes()
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORE_SCHEMA_INVALID"):
            ToolResultStore(unrelated).initialize()
        self.assertEqual(unrelated.read_bytes(), before)

    def test_invalid_content_is_not_stringified_or_saved(self):
        for value in ({1: "bad-key"}, {"x": float("nan")}, {"x": object()}, (1, 2)):
            with self.assertRaises(ValueError):
                self.save(value)

    def test_storage_abort_rolls_back_and_incompatible_schema_is_not_read(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "CREATE TRIGGER reject_result BEFORE INSERT ON tool_result_snapshots BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
            connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.save([1])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM tool_result_snapshots"
                ).fetchone()[0],
                0,
            )
            connection.execute(
                "UPDATE result_store_meta SET value='future' WHERE key='schema_version'"
            )
            connection.commit()
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORE_SCHEMA_INVALID"):
            self.store.enabled()

    def test_concurrent_delete_and_publish_never_revive_session_results(self):
        self.save([0])

        def publish(number):
            try:
                return self.save([number], call_id=str(number))
            except ResultStoreError as exc:
                return exc.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            writes = [pool.submit(publish, number) for number in range(4)]
            self.store.revoke_session(**self.scope)
            for result in writes:
                result.result()
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM tool_result_snapshots"
                ).fetchone()[0],
                0,
            )
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.save([9], call_id="after-revoke")

    def test_symlink_database_is_rejected(self):
        alias = Path(self.temp.name) / "alias.db"
        try:
            alias.symlink_to(self.path)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {type(exc).__name__}")
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORE_PATH_INVALID"):
            ToolResultStore(alias).enabled()


class AnalysisSnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "results.db"
        self.store = ToolResultStore(self.path)
        self.store.initialize()
        self.now = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)

    def save(self, *, store=None, owner_id="owner-a", session_id=None, content=None, now=None, permit=None):
        return (store or self.store).save_analysis(
            kind="lot_commonality", tenant_id="tenant-a", owner_id=owner_id, session_id=session_id,
            content=content if content is not None else {"value": 1}, now=now or self.now,
            retention=timedelta(days=7) if session_id is None else None,
            permit=permit or (lambda _session: True),
        )

    def read(self, ref, *, tenant_id="tenant-a", owner_id="owner-a", now=None, permit=None):
        return self.store.read_analysis(
            kind="lot_commonality", tenant_id=tenant_id, owner_id=owner_id, analysis_ref=ref,
            now=now or self.now, permit=permit or (lambda _session: True),
        )

    def count(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM analysis_snapshots").fetchone()[0]

    def test_schema_1_store_is_upgraded_in_place(self):
        path = Path(self.temp.name) / "v1.db"
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(
                """
                CREATE TABLE result_store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE result_store_sessions(tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                  session_id TEXT NOT NULL, PRIMARY KEY(tenant_id, owner_id, session_id));
                CREATE TABLE tool_result_snapshots(result_ref TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL, session_id TEXT NOT NULL, run_id TEXT NOT NULL, call_id TEXT NOT NULL,
                  metadata_json TEXT NOT NULL, content_json TEXT NOT NULL, stored_bytes INTEGER NOT NULL,
                  UNIQUE(tenant_id, owner_id, session_id, run_id, call_id));
                INSERT INTO result_store_meta VALUES ('schema_version','1'),('cursor_key','k'),('enabled','true');
                INSERT INTO tool_result_snapshots VALUES ('tr_old','t','o','s','r','c','{}','[1]',3);
                """
            )
        store = ToolResultStore(path)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORE_SCHEMA_INVALID"):
            store.enabled()
        store.initialize()
        store.initialize()
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(
                connection.execute("SELECT value FROM result_store_meta WHERE key='schema_version'").fetchone()[0], "2"
            )
            self.assertEqual(connection.execute("SELECT result_ref FROM tool_result_snapshots").fetchall(), [("tr_old",)])
        self.assertTrue(self.save(store=store)["analysis_ref"].startswith("lca_"))

    def test_versions_are_owner_scoped_and_expire(self):
        saved = self.save(content={"lots": ["A"]})
        self.assertEqual(saved["created_at"], "2026-11-21T02:00:00+00:00")
        self.assertEqual(saved["expires_at"], "2026-11-28T02:00:00+00:00")
        self.assertEqual(self.read(saved["analysis_ref"])["content"], {"lots": ["A"]})
        for kwargs in ({"owner_id": "owner-b"}, {"tenant_id": "tenant-b"}, {"now": self.now + timedelta(days=7)}):
            with self.subTest(**{key: str(value) for key, value in kwargs.items()}):
                with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
                    self.read(saved["analysis_ref"], **kwargs)
        self.save(now=self.now + timedelta(days=7))
        self.assertEqual(self.count(), 1)

    def test_session_versions_follow_revocation(self):
        page = self.save()
        bound = self.save(session_id="session-a")
        self.assertIsNone(bound["expires_at"])
        later = self.now + timedelta(days=30)
        self.assertEqual(self.read(bound["analysis_ref"], now=later)["session_id"], "session-a")
        self.save(now=later)
        self.assertEqual(self.count(), 2)
        # A deleted Session whose cleanup is still pending must already hide its versions.
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.read(bound["analysis_ref"], permit=lambda session: session != "session-a")
        self.store.revoke_session(tenant_id="tenant-a", owner_id="owner-a", session_id="session-a")
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.read(bound["analysis_ref"])
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.save(session_id="session-a")
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.save(session_id="session-b", permit=lambda _session: False)
        self.assertEqual(self.count(), 1)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_UNAVAILABLE"):
            self.read(page["analysis_ref"], now=later)

    def test_quota_and_size_limits_reject_without_writing(self):
        limited = ToolResultStore(
            self.path,
            limits=ResultStoreLimits(analysis_bytes=64, analysis_owner_count=2, analysis_session_count=1),
        )
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORAGE_LIMIT"):
            self.save(store=limited, content={"text": "x" * 64})
        self.save(store=limited)
        self.save(store=limited)
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORAGE_LIMIT"):
            self.save(store=limited)
        self.save(store=limited, session_id="session-a")
        with self.assertRaisesRegex(ResultStoreError, "RESULT_STORAGE_LIMIT"):
            self.save(store=limited, session_id="session-a")
        self.save(store=limited, session_id="session-b")
        self.save(store=limited, owner_id="owner-b")
        self.assertEqual(self.count(), 5)

    def test_retention_must_match_the_version_kind(self):
        for session_id, retention in ((None, None), (None, timedelta(0)), ("session-a", timedelta(days=7))):
            with self.subTest(session_id=session_id, retention=retention):
                with self.assertRaisesRegex(ResultStoreError, "RESULT_INVALID"):
                    self.store.save_analysis(
                        kind="lot_commonality", tenant_id="tenant-a", owner_id="owner-a", session_id=session_id,
                        content={}, now=self.now, retention=retention, permit=lambda _session: True,
                    )
        self.assertEqual(self.count(), 0)

    def test_signed_tokens_reject_tampering(self):
        token = self.store.sign_token({"v": 1, "o": 4})
        self.assertEqual(self.store.verify_token(token), {"v": 1, "o": 4})
        body, signature = token.split(".")
        for value in (body + "." + signature[:-1] + ("0" if signature[-1] != "0" else "1"), body, "x.y"):
            with self.subTest(value=value[:12]):
                with self.assertRaisesRegex(ResultStoreError, "RESULT_CURSOR_INVALID"):
                    self.store.verify_token(value)


if __name__ == "__main__":
    unittest.main()
