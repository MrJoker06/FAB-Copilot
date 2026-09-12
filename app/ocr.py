"""Compatibility facade for :mod:`app.knowledge.ocr`."""
from __future__ import annotations

from .knowledge import ocr as _canonical
from .knowledge.ocr import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
