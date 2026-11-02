"""Explicit adapter from the legacy enterprise provider protocol."""

from __future__ import annotations

from copy import deepcopy

from ...agent_runtime.tools.contracts import ToolPrincipal, ToolSource, ToolSourceKind
from ...manufacturing.data_contracts import EnterpriseDataProvider
from ...manufacturing.enterprise_tools.contracts import (
    EnterpriseDataError,
    EnterpriseQuery,
    EnterpriseSnapshot,
    EnterpriseTimeoutError,
    enterprise_scope,
)


class ProviderEnterpriseToolsAdapter:
    """Use one injected legacy provider without global provider selection or fallback."""

    def __init__(
        self,
        provider: EnterpriseDataProvider,
        *,
        demo_tenant_id: str,
        expected_provider_id: str,
        source_kind: ToolSourceKind = ToolSourceKind.FAKE,
        source_ref: str = "provider:enterprise-tools",
        adapter_id: str = "enterprise-provider",
    ) -> None:
        for name, value in (
            ("demo_tenant_id", demo_tenant_id),
            ("expected_provider_id", expected_provider_id),
            ("source_ref", source_ref),
            ("adapter_id", adapter_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(source_kind, ToolSourceKind):
            raise TypeError("source_kind must be a ToolSourceKind")
        if not all(
            callable(getattr(provider, method, None))
            for method in ("manifest", "summary", "page")
        ):
            raise ValueError(
                "enterprise provider must implement manifest, summary, and page"
            )
        self.provider = provider
        self.demo_tenant_id = demo_tenant_id
        self.expected_provider_id = expected_provider_id
        self.source_kind = source_kind
        self.source_ref = source_ref
        self.adapter_id = adapter_id

    def _dispatch(self, query: EnterpriseQuery, principal: ToolPrincipal) -> dict:
        if query.kind == "manifest":
            return self.provider.manifest(principal)
        filters = {
            "start": None,
            "end": None,
            "process_step": None,
            "equipment_id": None,
        }
        filters.update(query.filter_dict())
        if query.kind == "summary":
            return self.provider.summary(principal, filters)
        return self.provider.page(
            query.entity,
            principal,
            query.limit,
            None,
            deepcopy(query.filter_dict()),
        )

    def fetch(
        self, query: EnterpriseQuery, principal: ToolPrincipal
    ) -> EnterpriseSnapshot:
        if principal.tenant_id != self.demo_tenant_id:
            raise EnterpriseDataError("enterprise-tools source is unavailable")
        try:
            data = self._dispatch(query, principal)
            if (
                not isinstance(data, dict)
                or data.get("tenant_id") != self.demo_tenant_id
                or data.get("provider") != self.expected_provider_id
            ):
                raise EnterpriseDataError("enterprise-tools source is unavailable")
            return EnterpriseSnapshot(
                query,
                deepcopy(data),
                ToolSource(
                    self.source_ref,
                    self.adapter_id,
                    self.source_kind,
                    enterprise_scope(query, principal),
                ),
            )
        except (TimeoutError, EnterpriseTimeoutError):
            raise EnterpriseTimeoutError("enterprise-tools source timed out") from None
        except Exception:  # noqa: BLE001 - source boundary must not leak provider failures.
            raise EnterpriseDataError(
                "enterprise-tools source is unavailable"
            ) from None
