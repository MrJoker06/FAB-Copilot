"""Compatibility facade for :mod:`app.telemetry.http`."""

from __future__ import annotations

from .telemetry import http as _canonical
from .telemetry.http import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
