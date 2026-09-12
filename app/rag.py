"""Compatibility facade for :mod:`app.knowledge.rag`."""
from __future__ import annotations

from .knowledge import rag as _canonical
from .knowledge.rag import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
