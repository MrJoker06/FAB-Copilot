"""Compatibility facade for :mod:`app.conversation.sessions`."""
from __future__ import annotations

from .conversation import sessions as _canonical
from .conversation.sessions import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
