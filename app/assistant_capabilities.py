"""Compatibility facade for :mod:`app.agent_runtime.assistant_capabilities`."""
from __future__ import annotations

from .agent_runtime import assistant_capabilities as _canonical
from .agent_runtime.assistant_capabilities import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
