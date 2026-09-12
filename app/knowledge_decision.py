"""Compatibility facade for :mod:`app.knowledge.decision`."""
from __future__ import annotations

from .knowledge import decision as _canonical
from .knowledge.decision import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
