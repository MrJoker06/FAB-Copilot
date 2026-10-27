from __future__ import annotations

import unittest

from app.core.identity_contracts import (
    IdentityClaims,
    IdentityResolutionError,
    resolve_demo_header_claims,
    valid_identifier,
)


class IdentityContractPortableTests(unittest.TestCase):
    def resolve(self, headers=None, *, required=False):
        return resolve_demo_header_claims(
            headers or {},
            default_tenant_id="demo-fab",
            default_user_id="local-user",
            require_identity=required,
        )

    def test_defaults_and_demo_scheme_are_explicit(self):
        claims = self.resolve()
        self.assertEqual((claims.tenant_id, claims.user_id), ("demo-fab", "local-user"))
        self.assertEqual(claims.roles, ("analyst",))
        self.assertEqual(claims.authentication_scheme, "demo")

    def test_supplied_headers_use_headers_scheme_and_filter_roles(self):
        claims = self.resolve({
            "x-tenant-id": "fab-east",
            "x-user-id": "engineer-07",
            "x-roles": " analyst, process-engineer, invalid role, , admin ",
        })
        self.assertEqual((claims.tenant_id, claims.user_id), ("fab-east", "engineer-07"))
        self.assertEqual(claims.roles, ("analyst", "process-engineer", "admin"))
        self.assertEqual(claims.authentication_scheme, "headers")

    def test_required_headers_and_invalid_identifiers_fail_with_stable_codes(self):
        with self.assertRaisesRegex(IdentityResolutionError, "IDENTITY_REQUIRED"):
            self.resolve({"x-tenant-id": "fab-east"}, required=True)
        with self.assertRaisesRegex(IdentityResolutionError, "INVALID_IDENTITY"):
            self.resolve({"x-tenant-id": "invalid tenant", "x-user-id": "engineer-07"})
        self.assertTrue(valid_identifier("a" * 64))
        self.assertFalse(valid_identifier("a" * 65))
        self.assertFalse(valid_identifier("-invalid"))

    def test_all_invalid_roles_fall_back_to_default(self):
        claims = self.resolve({
            "x-tenant-id": "fab-east",
            "x-user-id": "engineer-07",
            "x-roles": "invalid role, ,!",
        })
        self.assertEqual(claims.roles, ("analyst",))

    def test_claims_are_immutable_and_validate_direct_construction(self):
        claims = IdentityClaims("tenant-a", "user-a")
        with self.assertRaises(AttributeError):
            claims.tenant_id = "tenant-b"
        with self.assertRaisesRegex(ValueError, "supported authentication_scheme"):
            IdentityClaims("tenant-a", "user-a", authentication_scheme="jwt")

    def test_claim_roles_are_defensively_copied_to_an_immutable_tuple(self):
        source_roles = ["analyst", "process-engineer"]
        claims = IdentityClaims("tenant-a", "user-a", source_roles)
        source_roles.append("admin")
        self.assertEqual(claims.roles, ("analyst", "process-engineer"))
        self.assertIsInstance(claims.roles, tuple)

    def test_direct_claim_construction_rejects_invalid_role_shapes_and_identifiers(self):
        for roles in ("admin", b"admin", (), ("",), ("invalid role",), (123,)):
            with self.subTest(roles=roles), self.assertRaisesRegex(ValueError, "valid roles"):
                IdentityClaims("tenant-a", "user-a", roles)
        for value in (None, 7, b"tenant-a"):
            with self.subTest(value=value):
                self.assertFalse(valid_identifier(value))
                with self.assertRaisesRegex(ValueError, "valid tenant_id"):
                    IdentityClaims(value, "user-a")


if __name__ == "__main__":
    unittest.main()
