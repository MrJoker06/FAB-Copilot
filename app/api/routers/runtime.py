from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fastapi import APIRouter


NamespaceProvider = Callable[[], Mapping[str, Any]]


@dataclass(frozen=True)
class RouterBundle:
    """A router and its compatibility exports for ``app.main``."""

    router: APIRouter
    exports: Mapping[str, Any]
