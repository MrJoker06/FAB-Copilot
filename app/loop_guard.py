"""Compatibility facade for :mod:`app.agent_runtime.execution.loop_guard`."""
from __future__ import annotations

from .agent_runtime.execution import loop_guard as _canonical
from .agent_runtime.execution.loop_guard import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
