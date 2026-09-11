"""Compatibility facade for :mod:`app.persistence.database`."""
from __future__ import annotations

from .persistence import database as _canonical
from .persistence.database import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
