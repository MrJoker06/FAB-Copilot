"""Compatibility facade for :mod:`app.conversation.turn_decision`."""
from __future__ import annotations

from .conversation import turn_decision as _canonical
from .conversation.turn_decision import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
