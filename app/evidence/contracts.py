"""Pure declarations for business evidence; no discovery or execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidencePolicy:
    component_id: str
    version: str
    evidence_requirements: tuple[Any, ...]
    step_matcher: Callable[..., bool]
    risk_checker: Callable[..., list[Any]]
    conflict_checker: Callable[..., list[Any]]
    describe_source: Callable[..., Any]
    row_modes: tuple[tuple[str, str], ...] = ()
