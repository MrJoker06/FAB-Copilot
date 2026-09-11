"""Compatibility facade for :mod:`app.model_gateway.health`.

The local ``db_session`` name intentionally remains patchable for legacy health
tests and integrations. Each wrapper resolves it at call time.
"""
from __future__ import annotations

from .model_gateway import health as _canonical
from .persistence.database import db_session

_now = _canonical._now
_stamp = _canonical._stamp
_parse = _canonical._parse
_public = _canonical._public


def ensure_model_health(model_id: str, connection=None) -> None:
    return _canonical._ensure_model_health(model_id, connection, db_session)


def get_model_health(model_id: str) -> dict:
    return _canonical._get_model_health(model_id, db_session)


def claim_model_call(model_id: str, *, cooldown_seconds: int, lease_seconds: int) -> tuple[bool, dict, str | None]:
    return _canonical._claim_model_call(model_id, cooldown_seconds=cooldown_seconds, lease_seconds=lease_seconds, session_factory=db_session)


def record_model_success(model_id: str) -> tuple[dict, str | None]:
    return _canonical._record_model_success(model_id, db_session)


def record_model_failure(model_id: str, category: str, *, threshold: int, cooldown_seconds: int) -> tuple[dict, str | None]:
    return _canonical._record_model_failure(model_id, category, threshold=threshold, cooldown_seconds=cooldown_seconds, session_factory=db_session)


def __getattr__(name: str):
    return getattr(_canonical, name)
