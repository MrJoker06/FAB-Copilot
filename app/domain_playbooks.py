"""Compatibility facade for :mod:`app.manufacturing.playbooks`."""
from __future__ import annotations

from .manufacturing import playbooks as _canonical
from .manufacturing.playbooks import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
