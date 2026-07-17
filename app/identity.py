from __future__ import annotations

import re
from contextvars import ContextVar, Token
from dataclasses import dataclass

from starlette.responses import JSONResponse

from .audit import current_request_id
from .config import get_settings


IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_principal: ContextVar["Principal | None"] = ContextVar("fab_principal", default=None)


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...] = ("analyst",)
    authentication_scheme: str = "demo"

    @property
    def knowledge_owner_id(self) -> str:
        settings = get_settings()
        if self.tenant_id == settings.enterprise_default_tenant_id:
            return self.user_id
        return f"{self.tenant_id}:{self.user_id}"

    def public_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "roles": list(self.roles),
            "authentication_scheme": self.authentication_scheme,
        }


def default_principal() -> Principal:
    settings = get_settings()
    return Principal(
        tenant_id=settings.enterprise_default_tenant_id,
        user_id=settings.enterprise_default_user_id,
    )


def current_principal() -> Principal:
    return _principal.get() or default_principal()


def set_principal(principal: Principal) -> Token:
    return _principal.set(principal)


def reset_principal(token: Token) -> None:
    _principal.reset(token)


def _header_map(scope: dict) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1").strip()
        for key, value in scope.get("headers", [])
    }


def _valid_identifier(value: str) -> bool:
    return bool(IDENTITY_PATTERN.fullmatch(value))


class PrincipalContextMiddleware:
    """Resolve the demo identity now and leave a clean boundary for future SSO/JWT."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        headers = _header_map(scope)
        supplied_tenant = headers.get("x-tenant-id", "")
        supplied_user = headers.get("x-user-id", "")
        if settings.enterprise_require_identity and (not supplied_tenant or not supplied_user):
            response = JSONResponse(
                status_code=401,
                content={
                    "error_code": "IDENTITY_REQUIRED",
                    "detail": "缺少 X-Tenant-ID 或 X-User-ID",
                    "request_id": current_request_id() or "",
                    "retryable": False,
                },
            )
            await response(scope, receive, send)
            return

        tenant_id = supplied_tenant or settings.enterprise_default_tenant_id
        user_id = supplied_user or settings.enterprise_default_user_id
        if not _valid_identifier(tenant_id) or not _valid_identifier(user_id):
            response = JSONResponse(
                status_code=400,
                content={
                    "error_code": "INVALID_IDENTITY",
                    "detail": "租户和用户标识只允许字母、数字、点、冒号、下划线和连字符，最长 64 字符",
                    "request_id": current_request_id() or "",
                    "retryable": False,
                },
            )
            await response(scope, receive, send)
            return

        roles = tuple(
            role for role in (item.strip() for item in headers.get("x-roles", "analyst").split(","))
            if role and _valid_identifier(role)
        ) or ("analyst",)
        principal = Principal(
            tenant_id=tenant_id,
            user_id=user_id,
            roles=roles,
            authentication_scheme="headers" if supplied_tenant or supplied_user else "demo",
        )
        token = set_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_principal(token)
