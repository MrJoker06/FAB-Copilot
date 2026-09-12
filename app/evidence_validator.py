"""Compatibility facade for :mod:`app.evidence.validator`."""
from __future__ import annotations

from .evidence import validator as _canonical
from .evidence.validator import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
