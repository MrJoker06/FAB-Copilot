"""Compatibility facade for :mod:`app.model_gateway.registry`."""
from __future__ import annotations

from .model_gateway import registry as _canonical
from .model_gateway.registry import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
