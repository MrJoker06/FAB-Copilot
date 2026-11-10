"""Isolated, lazy search sources used by the default tool composition."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from app.agent_runtime.tools.contracts import ToolSourceKind
from app.knowledge.search_registry import get_factory_search_backend
from app.tools.knowledge_search.contracts import (
    KnowledgeSearchTimeoutError,
    PersonalSearchBatch,
)
from app.knowledge.sqlite_backend import SqliteFactorySearchBackend
from app.manufacturing.processes import process_query_terms
from app.personal_knowledge_runtime.metadata import _json_list
from app.personal_knowledge_runtime.search import fts_query, search_knowledge
from app.tools.knowledge_search.backend_search import BackendKnowledgeSearchAdapter


def _readonly_session(knowledge_path: object, *, query_timeout_ms: int = 2_000):
    knowledge = Path(knowledge_path) if knowledge_path else None

    @contextmanager
    def session():
        if knowledge is None or not knowledge.is_file():
            raise RuntimeError("knowledge search source is unavailable")
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        started = time.monotonic()
        timed_out = False
        active_error = False
        try:
            connection.execute("PRAGMA busy_timeout = 500")
            try:
                connection.execute(
                    "ATTACH DATABASE ? AS knowledge",
                    (knowledge.resolve().as_uri() + "?mode=ro",),
                )
            except sqlite3.OperationalError:
                # Some Windows SQLite builds do not apply SQLITE_OPEN_URI to
                # ATTACH DATABASE and reject the file:// URI.  Fall back to a
                # plain attach; PRAGMA query_only below keeps the source read-only.
                connection.execute(
                    "ATTACH DATABASE ? AS knowledge",
                    (str(knowledge.resolve()),),
                )
            connection.execute("PRAGMA query_only = ON")

            def progress() -> int:
                nonlocal timed_out
                timed_out = (time.monotonic() - started) * 1000 > query_timeout_ms
                return int(timed_out)

            connection.set_progress_handler(progress, 1_000)
            yield connection
        except sqlite3.OperationalError as error:
            active_error = True
            if timed_out or "interrupted" in str(error).lower():
                raise KnowledgeSearchTimeoutError(
                    "knowledge-search source timed out"
                ) from None
            raise
        except TimeoutError:
            active_error = True
            raise KnowledgeSearchTimeoutError(
                "knowledge-search source timed out"
            ) from None
        except BaseException:
            active_error = True
            raise
        finally:
            cleanup_error: Exception | None = None
            try:
                connection.set_progress_handler(None, 0)
            except Exception as error:  # noqa: BLE001 - cleanup must not mask body errors.
                cleanup_error = error
            try:
                connection.close()
            except Exception as error:  # noqa: BLE001 - cleanup must not mask body errors.
                # A close failure must never replace the original timeout or
                # query failure that is exposed at the adapter boundary.
                cleanup_error = cleanup_error or error
            if cleanup_error is not None and not active_error:
                raise cleanup_error

    return session


def _quality_aliases(quality_path: object, *, query_timeout_ms: int = 2_000):
    quality = Path(quality_path) if quality_path else None

    def read(_principal):
        if quality is None or not quality.is_file():
            raise RuntimeError("knowledge search source is unavailable")
        connection = sqlite3.connect(quality.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        started = time.monotonic()
        timed_out = False
        active_error = False
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA busy_timeout = 500")

            def progress() -> int:
                nonlocal timed_out
                timed_out = (time.monotonic() - started) * 1000 > query_timeout_ms
                return int(timed_out)

            connection.set_progress_handler(progress, 1_000)
            rows = connection.execute(
                """SELECT t.canonical_name, a.alias FROM defect_types t
                   LEFT JOIN defect_type_aliases a ON a.defect_type_id=t.defect_type_id
                   WHERE t.is_active=1 ORDER BY t.canonical_name, a.alias"""
            ).fetchall()
        except sqlite3.OperationalError as error:
            active_error = True
            if timed_out or "interrupted" in str(error).lower():
                raise KnowledgeSearchTimeoutError(
                    "knowledge-search source timed out"
                ) from None
            raise
        except TimeoutError:
            active_error = True
            raise KnowledgeSearchTimeoutError(
                "knowledge-search source timed out"
            ) from None
        except BaseException:
            active_error = True
            raise
        finally:
            cleanup_error: Exception | None = None
            try:
                connection.set_progress_handler(None, 0)
            except Exception as error:  # noqa: BLE001 - cleanup must not mask body errors.
                cleanup_error = error
            try:
                connection.close()
            except Exception as error:  # noqa: BLE001 - cleanup must not mask body errors.
                cleanup_error = cleanup_error or error
            if cleanup_error is not None and not active_error:
                raise cleanup_error
        aliases: dict[str, list[str]] = {}
        for row in rows:
            aliases.setdefault(row["canonical_name"], [row["canonical_name"]])
            if row["alias"] is not None:
                aliases[row["canonical_name"]].append(row["alias"])
        return {name: tuple(dict.fromkeys(values)) for name, values in aliases.items()}

    return read


class _PersonalPort:
    def __init__(self, session, owner: str) -> None:
        self._session, self._owner = session, owner

    def search(
        self, principal, owner_user_id: str, query: str, limit: int
    ) -> PersonalSearchBatch:
        if owner_user_id != self._owner:
            raise ValueError("personal knowledge owner mismatch")
        deps = SimpleNamespace(
            db_session=self._session,
            fts_query=lambda text: fts_query(text, process_query_terms),
            json_list=_json_list,
        )
        return PersonalSearchBatch(
            owner_user_id, tuple(search_knowledge(deps, owner_user_id, query, limit))
        )


def create_runtime_knowledge_port(*, settings: object, principal: object):
    """Resolve only the configured factory source at first knowledge invocation."""
    name = getattr(settings, "factory_search_backend", "sqlite")
    default_tenant = getattr(
        settings, "enterprise_default_tenant_id", principal.tenant_id
    )
    if name == "sqlite":
        session = _readonly_session(getattr(settings, "knowledge_database_path", None))
        factory = SqliteFactorySearchBackend(
            session_factory=session,
            alias_reader=_quality_aliases(
                getattr(settings, "quality_database_path", None)
            ),
        )
        owner = (
            principal.user_id
            if principal.tenant_id == default_tenant
            else f"{principal.tenant_id}:{principal.user_id}"
        )
        personal = _PersonalPort(session, owner)
        factory_source_kind = ToolSourceKind.SQLITE
    else:
        factory = get_factory_search_backend(name)
        session = _readonly_session(getattr(settings, "knowledge_database_path", None))
        owner = (
            principal.user_id
            if principal.tenant_id == default_tenant
            else f"{principal.tenant_id}:{principal.user_id}"
        )
        personal = _PersonalPort(session, owner)
        factory_source_kind = getattr(factory, "tool_source_kind", None)
        if not isinstance(factory_source_kind, ToolSourceKind):
            raise ValueError(
                "custom factory search backend must declare tool_source_kind"
            )
    return BackendKnowledgeSearchAdapter(
        factory,
        personal,
        demo_tenant_id=principal.tenant_id,
        default_tenant_id=default_tenant,
        source_kind=factory_source_kind,
        personal_source_kind=ToolSourceKind.SQLITE,
        source_ref="runtime:knowledge-search",
    )


__all__ = ["create_runtime_knowledge_port"]
