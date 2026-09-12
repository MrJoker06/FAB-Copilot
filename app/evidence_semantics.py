"""Compatibility facade for :mod:`app.evidence.semantics`."""
from __future__ import annotations

from .evidence import semantics as _canonical
from .evidence.semantics import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
