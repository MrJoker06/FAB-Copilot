"""Compatibility facade for :mod:`app.knowledge.ocr_quality`."""
from __future__ import annotations

from .knowledge import ocr_quality as _canonical
from .knowledge.ocr_quality import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
