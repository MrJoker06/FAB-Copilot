"""Compatibility facade for :mod:`app.telemetry.runtime_status`."""

from __future__ import annotations

from .telemetry import runtime_status as _canonical
from .telemetry.runtime_status import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
