from __future__ import annotations

import secrets

from fab_contracts import IdentityContext
from fab_core import DomainError

from .settings import APISettings


class DevelopmentIdentityProvider:
    def __init__(self, settings: APISettings) -> None:
        self.settings = settings

    def resolve(self, authorization: str | None, request_id: str) -> IdentityContext:
        scheme, _, token = (authorization or "").partition(" ")
        if (
            self.settings.admin_api_token
            and scheme.lower() == "bearer"
            and secrets.compare_digest(token, self.settings.admin_api_token)
        ):
            return IdentityContext(
                user_id="local-admin",
                roles=("admin", "analyst"),
                scopes=("analytics:adhoc", "knowledge:personal", "settings:write", "monitor:read"),
                site_ids=("DEMO-FAB",),
                request_id=request_id,
            )
        if self.settings.dev_api_token and (
            scheme.lower() != "bearer" or not secrets.compare_digest(token, self.settings.dev_api_token)
        ):
            raise DomainError(
                "AUTHENTICATION_REQUIRED",
                "a valid development bearer token is required",
                status_code=401,
            )
        return IdentityContext(
            user_id=self.settings.dev_user_id,
            roles=("analyst",),
            scopes=("analytics:adhoc", "knowledge:personal"),
            site_ids=("DEMO-FAB",),
            request_id=request_id,
        )
