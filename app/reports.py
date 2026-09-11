"""Compatibility facade for :mod:`app.manufacturing.reports`."""
from __future__ import annotations

from .manufacturing import reports as _canonical
from .manufacturing.reports import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
