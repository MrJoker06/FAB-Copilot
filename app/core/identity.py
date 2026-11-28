from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from starlette.responses import JSONResponse

from ..telemetry.audit import current_request_id
from .identity_contracts import (
    IDENTITY_PATTERN,
    IdentityClaims,
    IdentityResolutionError,
    resolve_demo_header_claims,
    valid_identifier,
)
from .settings import get_settings


VERIFIED_IDENTITY_SCOPE_KEY = "fab.verified_identity"


_principal: ContextVar["Principal | None"] = ContextVar("fab_principal", default=None)


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...] = ("analyst",)
    authentication_scheme: str = "demo"

    modules: tuple[str, ...] = ()  # Populated only by a trusted identity provider.

    @classmethod
    def from_claims(cls, claims: IdentityClaims) -> "Principal":
        return cls(
            tenant_id=claims.tenant_id,
            user_id=claims.user_id,
            roles=claims.roles,
            authentication_scheme=claims.authentication_scheme,
            modules=claims.modules,
        )

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
    return valid_identifier(value)


class PrincipalContextMiddleware:
    """Resolve demo claims or consume verified claims from a server-side ASGI adapter."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        try:
            if getattr(settings, "require_verified_identity", False):
                claims = scope.get(VERIFIED_IDENTITY_SCOPE_KEY)
                if not isinstance(claims, IdentityClaims) or claims.authentication_scheme != "verified":
                    raise IdentityResolutionError("AUTHENTICATION_REQUIRED")
            else:
                claims = resolve_demo_header_claims(
                    _header_map(scope),
                    default_tenant_id=settings.enterprise_default_tenant_id,
                    default_user_id=settings.enterprise_default_user_id,
                    require_identity=settings.enterprise_require_identity,
                )
        except IdentityResolutionError as error:
            if error.error_code == "AUTHENTICATION_REQUIRED":
                response = JSONResponse(
                    status_code=401,
                    content={
                        "error_code": error.error_code,
                        "detail": "需要通过应用配置的登录方式认证",
                        "request_id": current_request_id() or "",
                        "retryable": False,
                    },
                )
            elif error.error_code == "IDENTITY_REQUIRED":
                response = JSONResponse(
                    status_code=401,
                    content={
                        "error_code": "IDENTITY_REQUIRED",
                        "detail": "缺少 X-Tenant-ID 或 X-User-ID",
                        "request_id": current_request_id() or "",
                        "retryable": False,
                    },
                )
            else:
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

        principal = Principal.from_claims(claims)
        token = set_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_principal(token)
