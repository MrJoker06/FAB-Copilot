"""Compatibility facade for :mod:`app.manufacturing.enterprise_data`."""
from __future__ import annotations

from .manufacturing import enterprise_data as _canonical
from .manufacturing.enterprise_data import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
