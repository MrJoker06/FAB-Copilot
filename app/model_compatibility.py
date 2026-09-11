"""Compatibility facade for :mod:`app.model_gateway.compatibility`."""
from __future__ import annotations

from .model_gateway import compatibility as _canonical
from .model_gateway.compatibility import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
