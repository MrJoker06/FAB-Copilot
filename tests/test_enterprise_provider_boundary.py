from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.identity import Principal, reset_principal, set_principal
from app.manufacturing import enterprise_data
from app.manufacturing.data_contracts import EnterpriseDataProvider


class RegisteredProvider:
    provider_id = "registered-test"

    def manifest(self, principal):
        return {"provider": self.provider_id, "tenant_id": principal.tenant_id}

    def summary(self, principal, filters):
        return {"provider": self.provider_id, "tenant_id": principal.tenant_id, "filters": filters}

    def page(self, entity, principal, limit, cursor, filters):
        return {
            "provider": self.provider_id,
            "entity": entity,
            "tenant_id": principal.tenant_id,
            "limit": limit,
            "cursor": cursor,
            "filters": filters,
        }


class EnterpriseProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.factories = patch.dict(enterprise_data._ENTERPRISE_PROVIDER_FACTORIES, {}, clear=True)
        self.factories.start()
        self.addCleanup(self.factories.stop)

    def _provider_environment(self, value: str):
        return patch.dict(os.environ, {"FAB_DATA_PROVIDER": value}, clear=False)

    def test_default_synthetic_provider_is_unchanged(self):
        self.assertIs(enterprise_data.EnterpriseDataProvider, EnterpriseDataProvider)
        with self._provider_environment("synthetic"):
            provider = enterprise_data.get_enterprise_provider()
        self.assertIsInstance(provider, enterprise_data.SyntheticFabProvider)
        self.assertEqual(provider.provider_id, "synthetic-fab-v1")

    def test_registered_provider_is_selected_and_current_principal_reaches_wrappers(self):
        enterprise_data.register_enterprise_provider("test-provider", RegisteredProvider)
        principal_token = set_principal(Principal("tenant-a", "user-a", ("engineer",)))
        self.addCleanup(reset_principal, principal_token)
        with self._provider_environment("test-provider"):
            self.assertEqual(
                enterprise_data.enterprise_data_manifest()["tenant_id"],
                "tenant-a",
            )
            self.assertEqual(
                enterprise_data.enterprise_fab_summary(process_step="ETCH")["tenant_id"],
                "tenant-a",
            )
            page = enterprise_data.query_enterprise_data("process-runs", limit=99, equipment_id="ETCH-01")
        self.assertEqual(page["tenant_id"], "tenant-a")
        self.assertEqual(page["limit"], 50)
        self.assertEqual(page["filters"], {"equipment_id": "ETCH-01"})

    def test_unknown_provider_fails_closed_without_synthetic_fallback(self):
        with self._provider_environment("not-registered"):
            with self.assertRaisesRegex(enterprise_data.EnterpriseDataError, "未配置") as caught:
                enterprise_data.get_enterprise_provider()
        self.assertEqual(caught.exception.error_code, "PROVIDER_NOT_CONFIGURED")

    def test_factory_failure_or_invalid_provider_fails_closed(self):
        enterprise_data.register_enterprise_provider("bad-factory", lambda: object())
        with self._provider_environment("bad-factory"):
            with self.assertRaises(enterprise_data.EnterpriseDataError) as caught:
                enterprise_data.get_enterprise_provider()
        self.assertEqual(caught.exception.error_code, "PROVIDER_NOT_CONFIGURED")

    def test_factory_exception_fails_closed_without_synthetic_fallback(self):
        def failing_factory():
            raise RuntimeError("adapter unavailable")

        enterprise_data.register_enterprise_provider("failing-factory", failing_factory)
        with (
            self._provider_environment("failing-factory"),
            patch.object(enterprise_data, "SyntheticFabProvider") as synthetic,
            self.assertRaises(enterprise_data.EnterpriseDataError) as caught,
        ):
            enterprise_data.get_enterprise_provider()
        self.assertEqual(caught.exception.error_code, "PROVIDER_NOT_CONFIGURED")
        synthetic.assert_not_called()

    def test_registration_rejects_reserved_invalid_duplicate_and_non_callable_entries(self):
        with self.assertRaises(ValueError):
            enterprise_data.register_enterprise_provider("synthetic", RegisteredProvider)
        with self.assertRaises(ValueError):
            enterprise_data.register_enterprise_provider("Uppercase", RegisteredProvider)
        with self.assertRaises(TypeError):
            enterprise_data.register_enterprise_provider("not-callable", object())
        enterprise_data.register_enterprise_provider("once", RegisteredProvider)
        with self.assertRaises(ValueError):
            enterprise_data.register_enterprise_provider("once", RegisteredProvider)


if __name__ == "__main__":
    unittest.main()
