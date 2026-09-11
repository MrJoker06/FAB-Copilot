"""Compatibility facade for :mod:`app.manufacturing.processes`."""
from __future__ import annotations

from .manufacturing import processes as _canonical
from .manufacturing.processes import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
