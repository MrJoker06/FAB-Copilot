"""Compatibility facade for :mod:`app.model_gateway.streaming`."""
from __future__ import annotations

from .model_gateway import streaming as _canonical
from .model_gateway.streaming import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
