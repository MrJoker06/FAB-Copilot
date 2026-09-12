"""Compatibility facade for :mod:`app.conversation.decision_arbiter`."""
from __future__ import annotations

from .conversation import decision_arbiter as _canonical
from .conversation.decision_arbiter import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
