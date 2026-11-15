"""Explicitly initialized, session-owned result snapshots in an independent DB."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..core.tool_result_units import canonical_json, result_page, result_units
from .connection import _connect_single, sqlite_journal_mode


class ResultStoreError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResultStoreLimits:
    snapshot_bytes: int = 4 * 1024**2
    run_bytes: int = 16 * 1024**2
    run_count: int = 16
    session_bytes: int = 64 * 1024**2
    session_count: int = 128
    total_bytes: int = 1024**3
    total_count: int = 4096

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("Result store limits must be positive integers")


_SCHEMA = """
CREATE TABLE result_store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE result_store_sessions(
 tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, session_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id, owner_id, session_id));
CREATE TABLE tool_result_snapshots(
 result_ref TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
 session_id TEXT NOT NULL, run_id TEXT NOT NULL, call_id TEXT NOT NULL,
 metadata_json TEXT NOT NULL, content_json TEXT NOT NULL, stored_bytes INTEGER NOT NULL,
 UNIQUE(tenant_id, owner_id, session_id, run_id, call_id));
CREATE INDEX snapshots_session ON tool_result_snapshots(tenant_id,owner_id,session_id);
"""


class ToolResultStore:
    def __init__(self, path: Path, *, limits: ResultStoreLimits | None = None):
        self.path = Path(path)
        self.limits = limits or ResultStoreLimits()

    def _validate_path(self):
        for path in (self.path, *self.path.parents):
            if path.is_symlink():
                raise ResultStoreError("RESULT_STORE_PATH_INVALID")
            if path.exists():
                info = path.stat()
                if getattr(info, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
                ):
                    raise ResultStoreError("RESULT_STORE_PATH_INVALID")
        if self.path.exists() and not self.path.is_file():
            raise ResultStoreError("RESULT_STORE_PATH_INVALID")

    @contextmanager
    def _connection(self, *, create=False):
        self._validate_path()
        if not create and not self.path.exists():
            raise ResultStoreError("RESULT_STORE_UNAVAILABLE")
        connection = _connect_single(self.path)
        try:
            if not create:
                row = connection.execute(
                    "SELECT value FROM result_store_meta WHERE key='schema_version'"
                ).fetchone()
                if row is None or row[0] != "1":
                    raise ResultStoreError("RESULT_STORE_SCHEMA_INVALID")
            yield connection
        finally:
            connection.close()

    def initialize(self):
        with self._connection(create=True) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if tables and "result_store_meta" not in tables:
                raise ResultStoreError("RESULT_STORE_SCHEMA_INVALID")
            connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(self.path)}")
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not tables:
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.executemany(
                    "INSERT INTO result_store_meta VALUES (?,?)",
                    [
                        ("schema_version", "1"),
                        ("cursor_key", secrets.token_hex(32)),
                        ("enabled", "true"),
                    ],
                )
            version = connection.execute(
                "SELECT value FROM result_store_meta WHERE key='schema_version'"
            ).fetchone()
            if version is None or version[0] != "1":
                raise ResultStoreError("RESULT_STORE_SCHEMA_INVALID")
            connection.commit()

    def enabled(self) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM result_store_meta WHERE key='enabled'"
            ).fetchone()
            if row is None or row[0] not in {"true", "false"}:
                raise ResultStoreError("RESULT_STORE_CONFIG_INVALID")
            return row[0] == "true"

    def set_enabled(self, enabled: bool):
        if type(enabled) is not bool:
            raise ResultStoreError("RESULT_STORE_CONFIG_INVALID")
        with self._connection() as connection:
            updated = connection.execute(
                "UPDATE result_store_meta SET value=? WHERE key='enabled'",
                ("true" if enabled else "false",),
            )
            if updated.rowcount != 1:
                raise ResultStoreError("RESULT_STORE_CONFIG_INVALID")
            connection.commit()

    @staticmethod
    def _scope(tenant_id, owner_id, session_id):
        values = (tenant_id, owner_id, session_id)
        if any(type(item) is not str or not item or len(item) > 128 for item in values):
            raise ResultStoreError("RESULT_UNAVAILABLE")
        return values

    @staticmethod
    def _permitted(connection, scope, permit):
        if (
            not permit()
            or connection.execute(
                "SELECT 1 FROM result_store_sessions WHERE tenant_id=? AND owner_id=? AND session_id=?",
                scope,
            ).fetchone()
        ):
            raise ResultStoreError("RESULT_UNAVAILABLE")

    def save(
        self,
        *,
        tenant_id,
        owner_id,
        session_id,
        run_id,
        call_id,
        metadata,
        content,
        permit,
    ):
        scope = self._scope(tenant_id, owner_id, session_id)
        if any(
            type(item) is not str or not item or len(item) > 128
            for item in (run_id, call_id)
        ):
            raise ResultStoreError("RESULT_INVALID")
        body = canonical_json(content)
        result_units(content)
        if type(metadata) is not dict:
            raise ResultStoreError("RESULT_INVALID")
        meta = canonical_json(metadata)
        size = len(body.encode("utf-8")) + len(meta.encode("utf-8"))
        if size > self.limits.snapshot_bytes:
            raise ResultStoreError("RESULT_STORAGE_LIMIT")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._permitted(connection, scope, permit)
            previous = connection.execute(
                "SELECT result_ref,metadata_json,content_json FROM tool_result_snapshots WHERE tenant_id=? AND owner_id=? AND session_id=? AND run_id=? AND call_id=?",
                (*scope, run_id, call_id),
            ).fetchone()
            if previous:
                if previous[1] != meta or previous[2] != body:
                    raise ResultStoreError("RESULT_CALL_CONFLICT")
                return previous[0]
            checks = [
                (
                    "tenant_id=? AND owner_id=? AND session_id=? AND run_id=?",
                    (*scope, run_id),
                    self.limits.run_bytes,
                    self.limits.run_count,
                ),
                (
                    "tenant_id=? AND owner_id=? AND session_id=?",
                    scope,
                    self.limits.session_bytes,
                    self.limits.session_count,
                ),
                ("1=1", (), self.limits.total_bytes, self.limits.total_count),
            ]
            for where, params, byte_limit, count_limit in checks:
                used, count = connection.execute(
                    f"SELECT COALESCE(SUM(stored_bytes),0), COUNT(*) FROM tool_result_snapshots WHERE {where}",
                    params,
                ).fetchone()
                if used + size > byte_limit or count >= count_limit:
                    raise ResultStoreError("RESULT_STORAGE_LIMIT")
            reference = "tr_" + secrets.token_hex(16)
            connection.execute(
                "INSERT INTO tool_result_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                (reference, *scope, run_id, call_id, meta, body, size),
            )
            connection.commit()
            return reference

    def read(
        self,
        *,
        tenant_id,
        owner_id,
        session_id,
        result_ref,
        permit,
        cursor=None,
        limit=20,
        max_bytes=4096,
    ):
        scope = self._scope(tenant_id, owner_id, session_id)
        if (
            type(result_ref) is not str
            or len(result_ref) > 128
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ResultStoreError("RESULT_INVALID")
        if cursor is not None and (type(cursor) is not str or len(cursor) > 2048):
            raise ResultStoreError("RESULT_INVALID")
        with self._connection() as connection:
            connection.execute("BEGIN")
            self._permitted(connection, scope, permit)
            row = connection.execute(
                "SELECT metadata_json,content_json FROM tool_result_snapshots WHERE tenant_id=? AND owner_id=? AND session_id=? AND result_ref=?",
                (*scope, result_ref),
            ).fetchone()
            if row is None:
                raise ResultStoreError("RESULT_UNAVAILABLE")
            key = (
                connection.execute(
                    "SELECT value FROM result_store_meta WHERE key='cursor_key'"
                )
                .fetchone()[0]
                .encode()
            )
            index, char_offset = 0, 0
            if cursor is not None:
                try:
                    token, signature = cursor.split(".")
                    if not hmac.compare_digest(
                        signature,
                        hmac.new(key, token.encode(), hashlib.sha512).hexdigest(),
                    ):
                        raise ValueError
                    payload = json.loads(base64.urlsafe_b64decode(token.encode()))
                    if payload["ref"] != result_ref or payload["v"] != 1:
                        raise ValueError
                    index, char_offset = payload["unit"], payload["char"]
                except (ValueError, KeyError, TypeError):
                    raise ResultStoreError("RESULT_CURSOR_INVALID") from None

            def next_cursor(unit, char):
                token = base64.urlsafe_b64encode(
                    canonical_json(
                        {"v": 1, "ref": result_ref, "unit": unit, "char": char}
                    ).encode()
                ).decode()
                return (
                    token
                    + "."
                    + hmac.new(key, token.encode(), hashlib.sha512).hexdigest()
                )

            try:
                return result_page(
                    json.loads(row[1]),
                    {
                        **json.loads(row[0]),
                        "result_ref": result_ref,
                        "version": "1.0.0",
                    },
                    index=index,
                    char_offset=char_offset,
                    limit=limit,
                    max_bytes=max_bytes,
                    cursor_for=next_cursor,
                )
            except ValueError as exc:
                raise ResultStoreError(
                    "RESULT_RESPONSE_LIMIT"
                    if "budget" in str(exc)
                    else "RESULT_CURSOR_INVALID"
                ) from None

    def revoke_session(self, *, tenant_id, owner_id, session_id):
        scope = self._scope(tenant_id, owner_id, session_id)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO result_store_sessions VALUES (?,?,?)", scope
            )
            connection.execute(
                "DELETE FROM tool_result_snapshots WHERE tenant_id=? AND owner_id=? AND session_id=?",
                scope,
            )
            connection.commit()
