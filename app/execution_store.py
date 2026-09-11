"""Compatibility facade for :mod:`app.persistence.execution_store`."""
from __future__ import annotations

from .persistence import execution_store as _canonical
from .persistence.execution_store import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
