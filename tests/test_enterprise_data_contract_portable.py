from __future__ import annotations

import unittest

from app.manufacturing.data_contracts import DataPrincipal, EnterpriseDataProvider


class FakePrincipal:
    tenant_id = "contract-tenant"


class FakeProvider:
    def manifest(self, principal: DataPrincipal) -> dict:
        return {"tenant_id": principal.tenant_id, "provider": "fake"}

    def summary(self, principal: DataPrincipal, filters: dict) -> dict:
        return {"tenant_id": principal.tenant_id, "filters": filters}

    def page(
        self,
        entity: str,
        principal: DataPrincipal,
        limit: int,
        cursor: str | None,
        filters: dict,
    ) -> dict:
        return {"entity": entity, "tenant_id": principal.tenant_id, "limit": limit, "filters": filters}


class EnterpriseDataContractPortableTests(unittest.TestCase):
    def test_fake_provider_satisfies_the_offline_tenant_contract(self):
        principal = FakePrincipal()
        provider: EnterpriseDataProvider = FakeProvider()
        self.assertEqual(provider.manifest(principal)["tenant_id"], "contract-tenant")
        self.assertEqual(provider.summary(principal, {"step": "ETCH"})["filters"], {"step": "ETCH"})
        self.assertEqual(
            provider.page("lots", principal, 10, None, {})["tenant_id"],
            "contract-tenant",
        )


if __name__ == "__main__":
    unittest.main()
