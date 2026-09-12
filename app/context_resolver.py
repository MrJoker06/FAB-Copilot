"""Compatibility facade for :mod:`app.conversation.context_resolver`."""
from __future__ import annotations

from .conversation import context_resolver as _canonical
from .conversation.context_resolver import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
