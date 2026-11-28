"""Explicitly initialized result snapshots in an independent DB.

Tool results are Session-owned; analysis snapshots may also exist without a
Session and then expire on their own retention.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    analysis_bytes: int = 32 * 1024**2
    analysis_owner_bytes: int = 256 * 1024**2
    analysis_owner_count: int = 64
    analysis_session_count: int = 16

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
# Schema 2: page analyses have no session and expire on their own retention;
# session-bound rows never expire and follow the Session revocation instead.
_ANALYSIS_SCHEMA = """
CREATE TABLE analysis_snapshots(
 analysis_ref TEXT PRIMARY KEY, kind TEXT NOT NULL, tenant_id TEXT NOT NULL,
 owner_id TEXT NOT NULL, session_id TEXT, created_at TEXT NOT NULL,
 expires_at TEXT, content_json TEXT NOT NULL, stored_bytes INTEGER NOT NULL,
 CHECK ((session_id IS NULL) = (expires_at IS NOT NULL)));
CREATE INDEX analysis_owner ON analysis_snapshots(tenant_id,owner_id,session_id);
CREATE INDEX analysis_expiry ON analysis_snapshots(expires_at);
"""
_SCHEMA_VERSION = "2"
_ANALYSIS_PREFIXES = {"lot_commonality": "lca_"}
_TOTAL_USAGE = (
    "SELECT (SELECT COALESCE(SUM(stored_bytes),0) FROM tool_result_snapshots)"
    " + (SELECT COALESCE(SUM(stored_bytes),0) FROM analysis_snapshots),"
    " (SELECT COUNT(*) FROM tool_result_snapshots) + (SELECT COUNT(*) FROM analysis_snapshots)"
)


def _utc_text(moment: datetime) -> str:
    if type(moment) is not datetime or moment.utcoffset() is None:
        raise ResultStoreError("RESULT_INVALID")
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _statements(script: str):
    return (statement for statement in script.split(";") if statement.strip())


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
                if row is None or row[0] != _SCHEMA_VERSION:
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
                for statement in _statements(_SCHEMA):
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
            if version is not None and version[0] == "1":
                for statement in _statements(_ANALYSIS_SCHEMA):
                    connection.execute(statement)
                connection.execute(
                    "UPDATE result_store_meta SET value=? WHERE key='schema_version'",
                    (_SCHEMA_VERSION,),
                )
            elif version is None or version[0] != _SCHEMA_VERSION:
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
            ]
            for where, params, byte_limit, count_limit in checks:
                used, count = connection.execute(
                    f"SELECT COALESCE(SUM(stored_bytes),0), COUNT(*) FROM tool_result_snapshots WHERE {where}",
                    params,
                ).fetchone()
                if used + size > byte_limit or count >= count_limit:
                    raise ResultStoreError("RESULT_STORAGE_LIMIT")
            self._check_total(connection, size)
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
        authorize_snapshot=None,
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
            metadata = json.loads(row[0])
            content = json.loads(row[1])
            if authorize_snapshot is not None:
                if not authorize_snapshot(metadata, content):
                    raise ResultStoreError("RESULT_UNAVAILABLE")
                self._permitted(connection, scope, permit)
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
                    content,
                    {
                        **metadata,
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
            connection.execute(
                "DELETE FROM analysis_snapshots WHERE tenant_id=? AND owner_id=? AND session_id=?",
                scope,
            )
            connection.commit()

    def _check_total(self, connection, size):
        used, count = connection.execute(_TOTAL_USAGE).fetchone()
        if used + size > self.limits.total_bytes or count >= self.limits.total_count:
            raise ResultStoreError("RESULT_STORAGE_LIMIT")

    @staticmethod
    def _analysis_scope(kind, tenant_id, owner_id, session_id):
        if kind not in _ANALYSIS_PREFIXES:
            raise ResultStoreError("RESULT_INVALID")
        if session_id is None:
            ToolResultStore._scope(tenant_id, owner_id, "page")
            return (tenant_id, owner_id, None)
        return ToolResultStore._scope(tenant_id, owner_id, session_id)

    def save_analysis(
        self, *, kind, tenant_id, owner_id, session_id, content, now, retention, permit
    ):
        """Store one immutable analysis version; ``permit(session_id)`` is rechecked in the write transaction.

        Page versions (no Session) require a positive ``retention``; Session versions take none.
        """
        scope = self._analysis_scope(kind, tenant_id, owner_id, session_id)
        if session_id is None:
            if type(retention) is not timedelta or retention <= timedelta(0):
                raise ResultStoreError("RESULT_INVALID")
        elif retention is not None:
            raise ResultStoreError("RESULT_INVALID")
        created_at = _utc_text(now)
        expires_at = _utc_text(now + retention) if session_id is None else None
        body = canonical_json(content)
        size = len(body.encode("utf-8"))
        if size > self.limits.analysis_bytes:
            raise ResultStoreError("RESULT_STORAGE_LIMIT")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if session_id is None:
                if not permit(None):
                    raise ResultStoreError("RESULT_UNAVAILABLE")
            else:
                self._permitted(connection, scope, lambda: permit(session_id))
            connection.execute(
                "DELETE FROM analysis_snapshots WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (created_at,),
            )
            used, page_count = connection.execute(
                "SELECT COALESCE(SUM(stored_bytes),0), COALESCE(SUM(session_id IS NULL),0)"
                " FROM analysis_snapshots WHERE tenant_id=? AND owner_id=?",
                scope[:2],
            ).fetchone()
            if session_id is None:
                over_count = page_count >= self.limits.analysis_owner_count
            else:
                over_count = connection.execute(
                    "SELECT COUNT(*) FROM analysis_snapshots WHERE tenant_id=? AND owner_id=? AND session_id=?",
                    scope,
                ).fetchone()[0] >= self.limits.analysis_session_count
            if used + size > self.limits.analysis_owner_bytes or over_count:
                raise ResultStoreError("RESULT_STORAGE_LIMIT")
            self._check_total(connection, size)
            reference = _ANALYSIS_PREFIXES[kind] + secrets.token_hex(16)
            connection.execute(
                "INSERT INTO analysis_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                (reference, kind, *scope, created_at, expires_at, body, size),
            )
            connection.commit()
        return {"analysis_ref": reference, "created_at": created_at, "expires_at": expires_at}

    def read_analysis(self, *, kind, tenant_id, owner_id, analysis_ref, now, permit):
        """Missing, expired, foreign and revoked versions are indistinguishable."""
        self._analysis_scope(kind, tenant_id, owner_id, None)
        if type(analysis_ref) is not str or len(analysis_ref) > 128:
            raise ResultStoreError("RESULT_UNAVAILABLE")
        moment = _utc_text(now)
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT session_id,created_at,expires_at,content_json FROM analysis_snapshots"
                " WHERE analysis_ref=? AND kind=? AND tenant_id=? AND owner_id=?",
                (analysis_ref, kind, tenant_id, owner_id),
            ).fetchone()
            if row is None or (row[2] is not None and row[2] <= moment):
                raise ResultStoreError("RESULT_UNAVAILABLE")
            if row[0] is None:
                if not permit(None):
                    raise ResultStoreError("RESULT_UNAVAILABLE")
            else:
                self._permitted(
                    connection, (tenant_id, owner_id, row[0]), lambda: permit(row[0])
                )
            return {
                "analysis_ref": analysis_ref,
                "session_id": row[0],
                "created_at": row[1],
                "expires_at": row[2],
                "content": json.loads(row[3]),
            }

    def _cursor_key(self):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM result_store_meta WHERE key='cursor_key'"
            ).fetchone()
        if row is None:
            raise ResultStoreError("RESULT_STORE_SCHEMA_INVALID")
        return row[0].encode()

    def sign_token(self, payload):
        token = base64.urlsafe_b64encode(canonical_json(payload).encode()).decode()
        return token + "." + hmac.new(self._cursor_key(), token.encode(), hashlib.sha512).hexdigest()

    def verify_token(self, value):
        key = self._cursor_key()
        try:
            token, signature = value.split(".")
            if not hmac.compare_digest(
                signature, hmac.new(key, token.encode(), hashlib.sha512).hexdigest()
            ):
                raise ValueError
            payload = json.loads(base64.urlsafe_b64decode(token.encode()))
            if type(payload) is not dict:
                raise ValueError
            return payload
        except (ValueError, TypeError, AttributeError):
            raise ResultStoreError("RESULT_CURSOR_INVALID") from None
