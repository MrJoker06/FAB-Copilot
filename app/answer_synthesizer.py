"""Compatibility facade for :mod:`app.evidence.answer_synthesizer`."""
from __future__ import annotations

from .evidence import answer_synthesizer as _canonical
from .evidence.answer_synthesizer import *  # noqa: F403


def __getattr__(name: str):
    return getattr(_canonical, name)
