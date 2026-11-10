"""Dependency-free contracts for manufacturing data providers.

These contracts travel with the portable data-contract unit.  Provider
implementations stay outside this module so an intranet adapter need not
import application settings, HTTP, database, or identity infrastructure.
"""
from __future__ import annotations

from typing import Protocol


class DataPrincipal(Protocol):
    """The identity information required by a manufacturing data provider."""

    @property
    def tenant_id(self) -> str: ...


class EnterpriseDataProvider(Protocol):
    """Read-only manufacturing data operations exposed to the application."""

    def manifest(self, principal: DataPrincipal) -> dict: ...

    def summary(self, principal: DataPrincipal, filters: dict) -> dict: ...

    def page(
        self,
        entity: str,
        principal: DataPrincipal,
        limit: int,
        cursor: str | None,
        filters: dict,
    ) -> dict: ...
