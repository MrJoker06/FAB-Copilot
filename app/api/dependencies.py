from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class AuthenticationDependencies:
    get_settings: Callable
    current_principal: Callable
    http_problem: Callable
    compare_digest: Callable[[str, str], bool] = secrets.compare_digest


def current_personal_user(authorization: Annotated[str | None, Header()] = None, *, deps: AuthenticationDependencies) -> str:
    configured_token = deps.get_settings().personal_knowledge_api_token
    if configured_token:
        scheme, _, provided_token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not deps.compare_digest(provided_token, configured_token):
            raise HTTPException(status_code=401, detail={"error_code": "AUTHENTICATION_REQUIRED", "message": "个人知识库访问令牌无效", "retryable": False}, headers={"WWW-Authenticate": "Bearer"})
    return deps.current_principal().knowledge_owner_id


def current_admin(authorization: Annotated[str | None, Header()] = None, *, deps: AuthenticationDependencies) -> str:
    configured_token = deps.get_settings().admin_api_token
    if not configured_token:
        raise deps.http_problem(503, "ADMIN_NOT_CONFIGURED", "管理端访问令牌尚未配置", False)
    scheme, _, provided_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not deps.compare_digest(provided_token, configured_token):
        raise HTTPException(status_code=401, detail={"error_code": "ADMIN_AUTHENTICATION_REQUIRED", "message": "管理端访问令牌无效", "retryable": False}, headers={"WWW-Authenticate": "Bearer"})
    return "administrator"
