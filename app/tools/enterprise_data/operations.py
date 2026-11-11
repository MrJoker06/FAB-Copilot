"""Explicit-context read operations shared by HTTP and legacy Tools."""
from __future__ import annotations

from .provider_contracts import DataPrincipal, EnterpriseDataProvider


def read_enterprise_manifest(provider: EnterpriseDataProvider, principal: DataPrincipal) -> dict:
    return provider.manifest(principal)


def read_enterprise_summary(provider: EnterpriseDataProvider, principal: DataPrincipal, filters: dict) -> dict:
    return provider.summary(principal, filters)


def read_enterprise_page(provider: EnterpriseDataProvider, principal: DataPrincipal, entity: str, limit: int, cursor: str | None, filters: dict) -> dict:
    return provider.page(entity, principal, limit, cursor, filters)
