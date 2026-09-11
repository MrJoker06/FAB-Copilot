"""Compatibility facade for :mod:`app.telemetry.audit`."""

from __future__ import annotations

from .telemetry import audit as _canonical
from .telemetry.audit import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
