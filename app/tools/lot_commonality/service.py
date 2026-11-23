"""Lot commonality analyses as bounded, re-readable versions behind one authorization path.

The HTTP API and the optional Agent tools both call this service, so a given
``analysis_ref`` yields the same counts and members through either entry.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Protocol

from app.agent_runtime.tools.contracts import ToolPrincipal
from app.tools.lot_commonality.analysis import (
    AnalysisSnapshot,
    create_snapshot,
    read_members,
    read_records,
    summarize,
)
from app.tools.lot_commonality.contracts import (
    DEFAULT_LIMITS,
    AnalysisLimits,
    LotCommonalityAccessError,
    LotCommonalityInputError,
    LotHistorySource,
)

ANALYSIS_REF_RE = re.compile(r"^lca_[a-f0-9]{32}$")
CURSOR_PREFIX = "lcc_"
DEFAULT_RETENTION = timedelta(days=7)
REQUIRED_ROLE = "analyst"


class LotCommonalityResultError(Exception):
    """A stored version cannot be used; codes follow the shared result-store vocabulary."""

    DETAILS = {
        "RESULT_UNAVAILABLE": "结果当前不可读取。",
        "RESULT_CURSOR_INVALID": "结果分页游标无效，请从第一页重新读取。",
        "RESULT_STORAGE_LIMIT": "分析结果保存容量不足，请稍后重试或缩小范围。",
        "RESULT_STORE_UNAVAILABLE": "分析结果存储当前不可用。",
    }

    def __init__(self, code: str) -> None:
        if code not in self.DETAILS:
            code = "RESULT_STORE_UNAVAILABLE"
        super().__init__(code)
        self.error_code = code
        self.detail = self.DETAILS[code]


@dataclass(frozen=True)
class StoredAnalysis:
    analysis_ref: str
    session_id: str | None
    created_at: str
    expires_at: str | None
    content: Mapping[str, object]


class AnalysisStore(Protocol):
    """Raises ``LotCommonalityResultError``; session permission is the store's concern."""

    def save(
        self, *, principal: ToolPrincipal, session_id: str | None,
        content: Mapping[str, object], now: datetime, retention: timedelta | None,
    ) -> StoredAnalysis: ...

    def load(self, *, principal: ToolPrincipal, analysis_ref: str, now: datetime) -> StoredAnalysis: ...

    def sign(self, payload: Mapping[str, object]) -> str: ...

    def verify(self, token: str) -> dict[str, object]: ...


def _digest(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class LotCommonalityService:
    store_factory: Callable[[], AnalysisStore]
    source_factory: Callable[[], LotHistorySource]
    clock: Callable[[], datetime]
    display_timezone: tzinfo
    retention: timedelta = DEFAULT_RETENTION
    limits: AnalysisLimits = field(default=DEFAULT_LIMITS)

    @staticmethod
    def _authorize(principal: ToolPrincipal) -> None:
        if REQUIRED_ROLE not in tuple(principal.roles):
            raise LotCommonalityAccessError()

    def _display(self, value: str | None) -> str | None:
        if value is None:
            return None
        return datetime.fromisoformat(value).astimezone(self.display_timezone).isoformat(timespec="seconds")

    def _summary(self, snapshot: AnalysisSnapshot, stored: StoredAnalysis) -> dict[str, object]:
        return summarize(
            snapshot,
            analysis_ref=stored.analysis_ref,
            created_at=self._display(stored.created_at),
            expires_at=self._display(stored.expires_at),
        )

    def create(
        self, body: object, principal: ToolPrincipal, *, session_id: str | None = None
    ) -> dict[str, object]:
        self._authorize(principal)
        snapshot = create_snapshot(body, self.source_factory(), principal, self.limits)
        # Session versions live as long as their Session; only page versions expire.
        stored = self.store_factory().save(
            principal=principal, session_id=session_id, content=snapshot.to_dict(),
            now=self.clock(), retention=self.retention if session_id is None else None,
        )
        return self._summary(snapshot, stored)

    def _load(self, analysis_ref: object, principal: ToolPrincipal) -> tuple[AnalysisStore, StoredAnalysis, AnalysisSnapshot]:
        self._authorize(principal)
        if not isinstance(analysis_ref, str) or not ANALYSIS_REF_RE.fullmatch(analysis_ref):
            raise LotCommonalityResultError("RESULT_UNAVAILABLE")
        store = self.store_factory()
        stored = store.load(principal=principal, analysis_ref=analysis_ref, now=self.clock())
        try:
            snapshot = AnalysisSnapshot.from_dict(stored.content)
        except (KeyError, TypeError, ValueError):
            raise LotCommonalityResultError("RESULT_STORE_UNAVAILABLE") from None
        return store, stored, snapshot

    def read(self, analysis_ref: object, principal: ToolPrincipal) -> dict[str, object]:
        _, stored, snapshot = self._load(analysis_ref, principal)
        return self._summary(snapshot, stored)

    def _page(self, operation, reader, analysis_ref, body, principal):
        store, stored, snapshot = self._load(analysis_ref, principal)
        if not isinstance(body, Mapping):
            raise LotCommonalityInputError("请求体必须是对象。")
        query = {key: value for key, value in body.items() if key != "cursor"}
        binding = _digest(
            {"op": operation, "ref": stored.analysis_ref, "tenant": principal.tenant_id,
             "user": principal.user_id, "query": query}
        )[:32]
        cursor = body.get("cursor")
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor.startswith(CURSOR_PREFIX) or len(cursor) > 2048:
                raise LotCommonalityResultError("RESULT_CURSOR_INVALID")
            payload = store.verify(cursor[len(CURSOR_PREFIX):])
            offset = payload.get("o")
            if (
                set(payload) != {"v", "q", "o"}
                or payload.get("v") != 1
                or payload.get("q") != binding
                or isinstance(offset, bool)
                or not isinstance(offset, int)
                or offset < 1
            ):
                raise LotCommonalityResultError("RESULT_CURSOR_INVALID")
        page, next_offset = reader(snapshot, query, analysis_ref=stored.analysis_ref, offset=offset)
        if next_offset is not None:
            page["page"]["next_cursor"] = CURSOR_PREFIX + store.sign({"v": 1, "q": binding, "o": next_offset})
        return page

    def members(self, analysis_ref: object, body: object, principal: ToolPrincipal) -> dict[str, object]:
        return self._page("members", read_members, analysis_ref, body, principal)

    def records(self, analysis_ref: object, body: object, principal: ToolPrincipal) -> dict[str, object]:
        return self._page("records", read_records, analysis_ref, body, principal)
