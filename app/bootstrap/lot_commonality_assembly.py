"""Default composition of lot commonality analysis: local SQLite source, shared result store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.conversation.result_lifecycle import session_results_permitted
from app.core.settings import get_settings
from app.persistence.tool_result_store import ResultStoreError, ToolResultStore
from app.tools.lot_commonality.service import (
    LotCommonalityResultError,
    LotCommonalityService,
    StoredAnalysis,
)
from app.tools.lot_commonality.sqlite_source import SQLiteLotHistorySource

from .storage_identity_assembly import configured_result_store

_KIND = "lot_commonality"
# The demo manufacturing data records local Shanghai time without an offset; a
# fixed offset avoids depending on tzdata, which Windows Python may lack.
SOURCE_TIMEZONE = "Asia/Shanghai"
SOURCE_OFFSET = timezone(timedelta(hours=8))


class ResultStoreAnalyses:
    """Adapts the shared result store and the Session deletion rule to the service."""

    def __init__(self, store: ToolResultStore) -> None:
        self.store = store

    @staticmethod
    def _permit(principal):
        def permit(session_id):
            return session_id is None or session_results_permitted(
                session_id, principal.tenant_id, principal.user_id
            )

        return permit

    def _call(self, operation, **arguments):
        try:
            return operation(**arguments)
        except ResultStoreError as exc:
            raise LotCommonalityResultError(exc.code) from None

    def save(self, *, principal, session_id, content, now, retention):
        stored = self._call(
            self.store.save_analysis, kind=_KIND, tenant_id=principal.tenant_id,
            owner_id=principal.user_id, session_id=session_id, content=content,
            now=now, retention=retention, permit=self._permit(principal),
        )
        return StoredAnalysis(stored["analysis_ref"], session_id, stored["created_at"], stored["expires_at"], content)

    def load(self, *, principal, analysis_ref, now):
        stored = self._call(
            self.store.read_analysis, kind=_KIND, tenant_id=principal.tenant_id,
            owner_id=principal.user_id, analysis_ref=analysis_ref, now=now,
            permit=self._permit(principal),
        )
        return StoredAnalysis(
            stored["analysis_ref"], stored["session_id"], stored["created_at"],
            stored["expires_at"], stored["content"],
        )

    def sign(self, payload):
        return self._call(self.store.sign_token, payload=payload)

    def verify(self, token):
        return self._call(self.store.verify_token, value=token)


def _store() -> ResultStoreAnalyses:
    try:
        return ResultStoreAnalyses(configured_result_store())
    except ResultStoreError as exc:
        raise LotCommonalityResultError(exc.code) from None


def _source() -> SQLiteLotHistorySource:
    settings = get_settings()
    return SQLiteLotHistorySource(
        settings.manufacturing_database_path,
        demo_tenant_id=settings.enterprise_default_tenant_id,
        timezone_name=SOURCE_TIMEZONE,
        utc_offset_minutes=480,
    )


def lot_commonality_service() -> LotCommonalityService:
    return LotCommonalityService(
        store_factory=_store,
        source_factory=_source,
        clock=lambda: datetime.now(SOURCE_OFFSET),
        display_timezone=SOURCE_OFFSET,
    )
