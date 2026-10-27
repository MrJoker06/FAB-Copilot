"""Dependency-free claims and demo header identity resolution policy.

This module deliberately models only the transitional header-based identity
contract. It performs no authentication and must be replaced by a trusted
identity adapter before a production deployment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
DEFAULT_ROLE = "analyst"
AUTHENTICATION_SCHEMES = frozenset({"demo", "headers"})


@dataclass(frozen=True)
class IdentityClaims:
    """Portable, immutable claims consumed by the application identity facade."""

    tenant_id: str
    user_id: str
    roles: tuple[str, ...] = (DEFAULT_ROLE,)
    authentication_scheme: str = "demo"

    def __post_init__(self) -> None:
        if not valid_identifier(self.tenant_id) or not valid_identifier(self.user_id):
            raise ValueError("identity claims require valid tenant_id and user_id")
        if isinstance(self.roles, (str, bytes)) or not isinstance(self.roles, Sequence):
            raise ValueError("identity claims require valid roles")
        roles = tuple(self.roles)
        if not roles or any(not valid_identifier(role) for role in roles):
            raise ValueError("identity claims require valid roles")
        if not isinstance(self.authentication_scheme, str) or self.authentication_scheme not in AUTHENTICATION_SCHEMES:
            raise ValueError("identity claims require a supported authentication_scheme")
        object.__setattr__(self, "roles", roles)


class IdentityResolutionError(ValueError):
    """A policy error with the stable HTTP-facing error code."""

    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(error_code)


def valid_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(IDENTITY_PATTERN.fullmatch(value))


def resolve_demo_header_claims(
    headers: Mapping[str, str],
    *,
    default_tenant_id: str,
    default_user_id: str,
    require_identity: bool,
) -> IdentityClaims:
    """Resolve untrusted API header claims using explicit application defaults."""
    supplied_tenant = headers.get("x-tenant-id", "")
    supplied_user = headers.get("x-user-id", "")
    if require_identity and (not supplied_tenant or not supplied_user):
        raise IdentityResolutionError("IDENTITY_REQUIRED")

    tenant_id = supplied_tenant or default_tenant_id
    user_id = supplied_user or default_user_id
    if not valid_identifier(tenant_id) or not valid_identifier(user_id):
        raise IdentityResolutionError("INVALID_IDENTITY")

    roles = tuple(
        role
        for role in (item.strip() for item in headers.get("x-roles", DEFAULT_ROLE).split(","))
        if role and valid_identifier(role)
    ) or (DEFAULT_ROLE,)
    return IdentityClaims(
        tenant_id=tenant_id,
        user_id=user_id,
        roles=roles,
        authentication_scheme="headers" if supplied_tenant or supplied_user else "demo",
    )
