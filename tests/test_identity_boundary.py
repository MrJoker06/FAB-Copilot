from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.identity import Principal, PrincipalContextMiddleware, current_principal
from app.core.identity_contracts import IdentityClaims


SETTINGS = SimpleNamespace(
    enterprise_default_tenant_id="demo-fab",
    enterprise_default_user_id="local-user",
    enterprise_require_identity=False,
)


def scope(headers=(), path="/api/enterprise/context"):
    return {"type": "http", "path": path, "headers": list(headers)}


class IdentityBoundaryTests(unittest.TestCase):
    def test_principal_mapping_preserves_public_shape(self):
        principal = Principal.from_claims(IdentityClaims("fab-east", "engineer-07", ("analyst",), "headers"))
        self.assertEqual(principal.public_dict(), {
            "tenant_id": "fab-east",
            "user_id": "engineer-07",
            "roles": ["analyst"],
            "authentication_scheme": "headers",
        })

    def test_middleware_resolves_headers_and_resets_context(self):
        observed = []

        async def app(_scope, _receive, _send):
            observed.append(current_principal())

        async def run():
            middleware = PrincipalContextMiddleware(app)
            with patch("app.core.identity.get_settings", return_value=SETTINGS):
                await middleware(
                    scope(((b"x-tenant-id", b"fab-east"), (b"x-user-id", b"engineer-07"), (b"x-roles", b"analyst,process-engineer"))),
                    None,
                    lambda _message: None,
                )
                after = current_principal()
            return after

        after = asyncio.run(run())
        self.assertEqual(observed[0].tenant_id, "fab-east")
        self.assertEqual(observed[0].user_id, "engineer-07")
        self.assertEqual(observed[0].roles, ("analyst", "process-engineer"))
        self.assertEqual(observed[0].authentication_scheme, "headers")
        self.assertEqual((after.tenant_id, after.user_id), ("demo-fab", "local-user"))

    def test_middleware_preserves_required_and_invalid_http_contracts(self):
        messages = []

        async def send(message):
            messages.append(message)

        async def app(_scope, _receive, _send):
            self.fail("identity failures must not call the downstream app")

        async def run(headers, required):
            middleware = PrincipalContextMiddleware(app)
            configured = SimpleNamespace(**{**SETTINGS.__dict__, "enterprise_require_identity": required})
            with patch("app.core.identity.get_settings", return_value=configured), patch(
                "app.core.identity.current_request_id", return_value="request-identity-1"
            ):
                await middleware(scope(headers), None, send)

        asyncio.run(run((), True))
        self.assertEqual(messages[0]["status"], 401)
        required_payload = json.loads(messages[1]["body"])
        self.assertEqual(required_payload["error_code"], "IDENTITY_REQUIRED")
        self.assertEqual(required_payload["request_id"], "request-identity-1")
        messages.clear()
        asyncio.run(run(((b"x-tenant-id", b"bad tenant"), (b"x-user-id", b"engineer-07")), False))
        self.assertEqual(messages[0]["status"], 400)
        self.assertEqual(json.loads(messages[1]["body"])["error_code"], "INVALID_IDENTITY")


if __name__ == "__main__":
    unittest.main()
