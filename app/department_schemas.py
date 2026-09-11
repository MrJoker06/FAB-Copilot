"""Compatibility facade for :mod:`app.persistence.department_schemas`."""
from __future__ import annotations

from .persistence import department_schemas as _canonical
from .persistence.department_schemas import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
