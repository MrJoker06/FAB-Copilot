from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolSourceKind
from app.core.identity import Principal
from app.integrations.manufacturing.fake_enterprise_tools import (
    FakeEnterpriseToolsAdapter,
)
from app.integrations.manufacturing.provider_enterprise_tools import (
    ProviderEnterpriseToolsAdapter,
)
from app.manufacturing import enterprise_data
from app.manufacturing.enterprise_tools.contracts import (
    EnterpriseDataError,
    EnterpriseManifestInput,
    EnterpriseQuery,
    EnterpriseSampleInput,
    EnterpriseSummaryInput,
    EnterpriseTimeoutError,
    EnterpriseWindow,
)
from app.manufacturing.enterprise_tools.handler import (
    EnterpriseToolsDependencies,
    enterprise_manifest_handler,
    enterprise_sample_handler,
    enterprise_summary_handler,
)


class FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(2026, 10, 24)


class RecordingProvider:
    provider_id = "recording-v1"

    def __init__(self, response: dict[str, object] | None = None) -> None:
        self.response = response or {
            "provider": self.provider_id,
            "tenant_id": "demo-tenant",
            "nested": {"items": ["original"]},
        }
        self.calls: list[tuple[object, ...]] = []

    def manifest(self, principal: Principal) -> dict:
        self.calls.append(("manifest", principal))
        return deepcopy(self.response)

    def summary(self, principal: Principal, filters: dict) -> dict:
        self.calls.append(("summary", principal, filters))
        return deepcopy(self.response)

    def page(
        self,
        entity: str,
        principal: Principal,
        limit: int,
        cursor: str | None,
        filters: dict,
    ) -> dict:
        self.calls.append(("page", entity, principal, limit, cursor, filters))
        return deepcopy(self.response)


class EnterpriseToolsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = Principal("demo-tenant", "demo-user")
        self.other_principal = Principal("other-tenant", "demo-user")

    def test_provider_dispatches_fixed_calls_without_defaults_for_samples(self) -> None:
        provider = RecordingProvider()
        adapter = ProviderEnterpriseToolsAdapter(
            provider,
            demo_tenant_id="demo-tenant",
            expected_provider_id="recording-v1",
        )
        window = EnterpriseWindow(date(2026, 10, 24))
        manifest = EnterpriseManifestInput().resolve(window)
        summary = EnterpriseSummaryInput(process_step="ETCH").resolve(window)
        sample = EnterpriseSampleInput("lots", limit=50, product="Nova-P1").resolve(
            window
        )

        for query in (manifest, summary, sample):
            adapter.fetch(query, self.principal)

        self.assertEqual(provider.calls[0], ("manifest", self.principal))
        self.assertEqual(
            provider.calls[1],
            (
                "summary",
                self.principal,
                {
                    "start": None,
                    "end": None,
                    "process_step": "ETCH",
                    "equipment_id": None,
                },
            ),
        )
        self.assertEqual(
            provider.calls[2],
            ("page", "lots", self.principal, 50, None, {"product": "Nova-P1"}),
        )

    def test_provider_rejects_tenant_and_bad_metadata_without_fallback(self) -> None:
        provider = RecordingProvider()
        adapter = ProviderEnterpriseToolsAdapter(
            provider,
            demo_tenant_id="demo-tenant",
            expected_provider_id="recording-v1",
        )
        query = EnterpriseQuery("manifest", as_of=date(2026, 10, 24))
        with self.assertRaises(EnterpriseDataError):
            adapter.fetch(query, self.other_principal)
        self.assertEqual(provider.calls, [])

        for key, value in (("tenant_id", "other-tenant"), ("provider", "other-v1")):
            provider.response[key] = value
            with self.subTest(key=key), self.assertRaises(EnterpriseDataError):
                adapter.fetch(query, self.principal)
            provider.response[key] = (
                "demo-tenant" if key == "tenant_id" else "recording-v1"
            )

    def test_provider_errors_and_timeouts_are_sanitized(self) -> None:
        query = EnterpriseQuery("manifest", as_of=date(2026, 10, 24))

        class FailingProvider(RecordingProvider):
            def manifest(self, principal: Principal) -> dict:
                self.calls.append(("manifest", principal))
                raise RuntimeError("secret details")

        failing = FailingProvider()
        adapter = ProviderEnterpriseToolsAdapter(
            failing,
            demo_tenant_id="demo-tenant",
            expected_provider_id="recording-v1",
        )
        with self.assertRaisesRegex(EnterpriseDataError, "source is unavailable"):
            adapter.fetch(query, self.principal)
        self.assertEqual(len(failing.calls), 1)

        class TimeoutProvider(FailingProvider):
            def manifest(self, principal: Principal) -> dict:
                self.calls.append(("manifest", principal))
                raise EnterpriseTimeoutError("private typed timeout")

        timed = TimeoutProvider()
        adapter = ProviderEnterpriseToolsAdapter(
            timed,
            demo_tenant_id="demo-tenant",
            expected_provider_id="recording-v1",
        )
        with self.assertRaisesRegex(
            EnterpriseTimeoutError, "enterprise-tools source timed out"
        ):
            adapter.fetch(query, self.principal)

        class BuiltinTimeoutProvider(FailingProvider):
            def manifest(self, principal: Principal) -> dict:
                self.calls.append(("manifest", principal))
                raise TimeoutError("private builtin timeout")

        builtin_timeout = BuiltinTimeoutProvider()
        adapter = ProviderEnterpriseToolsAdapter(
            builtin_timeout,
            demo_tenant_id="demo-tenant",
            expected_provider_id="recording-v1",
        )
        with self.assertRaisesRegex(
            EnterpriseTimeoutError, "enterprise-tools source timed out"
        ):
            adapter.fetch(query, self.principal)

    def test_constructor_refuses_missing_provider_method_and_results_are_copied(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            ProviderEnterpriseToolsAdapter(
                object(),
                demo_tenant_id="demo-tenant",
                expected_provider_id="recording-v1",
            )
        provider = RecordingProvider()
        for arguments in (
            {"demo_tenant_id": ""},
            {"expected_provider_id": ""},
            {"source_ref": ""},
            {"adapter_id": ""},
            {"source_kind": "fake"},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises((ValueError, TypeError)),
            ):
                config = {
                    "demo_tenant_id": "demo-tenant",
                    "expected_provider_id": "recording-v1",
                }
                config.update(arguments)
                ProviderEnterpriseToolsAdapter(
                    provider,
                    **config,
                )
        self.assertEqual(provider.calls, [])
        provider = RecordingProvider()
        adapter = ProviderEnterpriseToolsAdapter(
            provider,
            demo_tenant_id="demo-tenant",
            expected_provider_id="recording-v1",
            source_kind=ToolSourceKind.FAKE,
        )
        snapshot = adapter.fetch(
            EnterpriseQuery("manifest", as_of=date(2026, 10, 24)), self.principal
        )
        snapshot.data["nested"]["items"].append("changed")
        self.assertEqual(provider.response["nested"], {"items": ["original"]})

    def test_fake_fixture_is_exact_and_deeply_isolated(self) -> None:
        query = EnterpriseQuery("manifest", as_of=date(2026, 10, 24))
        fixtures = {
            query: {
                "provider": "fixture",
                "tenant_id": "demo-tenant",
                "nested": {"items": ["original"]},
            }
        }
        adapter = FakeEnterpriseToolsAdapter("demo-tenant", fixtures)
        fixtures[query]["nested"]["items"].append("constructor-change")
        snapshot = adapter.fetch(query, self.principal)
        snapshot.data["nested"]["items"].append("fetch-change")
        second = adapter.fetch(query, self.principal)
        self.assertEqual(second.data["nested"], {"items": ["original"]})
        self.assertEqual(len(adapter.calls), 2)
        with self.assertRaises(EnterpriseDataError):
            adapter.fetch(
                EnterpriseQuery(
                    "summary",
                    effective_start=date(2026, 7, 27),
                    effective_end=date(2026, 10, 24),
                    as_of=date(2026, 10, 24),
                ),
                self.principal,
            )
        with self.assertRaises(EnterpriseDataError):
            adapter.fetch(query, self.other_principal)

    def test_legacy_synthetic_outputs_match_native_handlers(self) -> None:
        settings = SimpleNamespace(
            enterprise_mock_seed=17,
            enterprise_mock_virtual_lots=120,
            enterprise_mock_cursor_secret="test-cursor-secret",
        )
        with (
            patch.object(enterprise_data, "get_settings", return_value=settings),
            patch.object(enterprise_data, "date", FixedDate),
        ):
            provider = enterprise_data.SyntheticFabProvider()
            adapter = ProviderEnterpriseToolsAdapter(
                provider,
                demo_tenant_id="demo-tenant",
                expected_provider_id=provider.provider_id,
            )
            window = EnterpriseWindow(FixedDate.today())
            dependencies = EnterpriseToolsDependencies(adapter, window)

            def native(input_value, handler):
                return handler(
                    input_value,
                    ToolExecutionContext(
                        self.principal,
                        "enterprise-adapter-test",
                        "call-1",
                        dependencies,
                    ),
                ).data

            with (
                patch.object(
                    enterprise_data, "get_enterprise_provider", return_value=provider
                ),
                patch.object(
                    enterprise_data, "current_principal", return_value=self.principal
                ),
            ):
                self.assertEqual(
                    native(EnterpriseManifestInput(), enterprise_manifest_handler),
                    enterprise_data.enterprise_data_manifest(),
                )
                self.assertEqual(
                    native(EnterpriseSummaryInput(), enterprise_summary_handler),
                    enterprise_data.enterprise_fab_summary(),
                )
                self.assertEqual(
                    native(
                        EnterpriseSummaryInput("2024-01-01", "2026-10-24"),
                        enterprise_summary_handler,
                    ),
                    enterprise_data.enterprise_fab_summary("2024-01-01", "2026-10-24"),
                )
                for entity, filters in (
                    ("lots", {"product": "Nova-P1"}),
                    (
                        "process-runs",
                        {"process_step": "ETCH", "equipment_id": "ETCH-01"},
                    ),
                    ("sensor-events", {"signal_name": "RF power"}),
                ):
                    with self.subTest(entity=entity):
                        self.assertEqual(
                            native(
                                EnterpriseSampleInput(entity), enterprise_sample_handler
                            ),
                            enterprise_data.query_enterprise_data(entity),
                        )
                        self.assertEqual(
                            native(
                                EnterpriseSampleInput(entity, limit=50, **filters),
                                enterprise_sample_handler,
                            ),
                            enterprise_data.query_enterprise_data(
                                entity, limit=50, **filters
                            ),
                        )


if __name__ == "__main__":
    unittest.main()
