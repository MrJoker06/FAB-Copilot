"""Explicit provider selection and legacy Tool context binding."""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from app.core.settings import get_settings
from app.core.identity import current_principal
from app.tools.enterprise_data.provider_contracts import EnterpriseDataProvider, EnterpriseDataError
from app.tools.enterprise_data import operations

_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESERVED_PROVIDER_NAMES = frozenset({"synthetic"})
_ENTERPRISE_PROVIDER_FACTORIES: dict[str, Callable[[], EnterpriseDataProvider]] = {}
_REQUIRED_PROVIDER_METHODS = ("manifest", "summary", "page")


def register_enterprise_provider(
    name: str,
    factory: Callable[[], EnterpriseDataProvider],
) -> None:
    """Register a startup-time factory for an explicitly configured provider.

    Registration deliberately does not discover adapters or open connections.
    Production composition code must register an adapter before setting
    ``FAB_DATA_PROVIDER`` to its name.
    """
    if not isinstance(name, str) or not _PROVIDER_NAME_PATTERN.fullmatch(name):
        raise ValueError("enterprise provider name must be lowercase and use letters, digits, '-' or '_'")
    if name in _RESERVED_PROVIDER_NAMES:
        raise ValueError(f"enterprise provider name is reserved: {name}")
    if not callable(factory):
        raise TypeError("enterprise provider factory must be callable")
    if name in _ENTERPRISE_PROVIDER_FACTORIES:
        raise ValueError(f"enterprise provider is already registered: {name}")
    _ENTERPRISE_PROVIDER_FACTORIES[name] = factory


def _configured_provider_error(name: str) -> EnterpriseDataError:
    return EnterpriseDataError(
        "PROVIDER_NOT_CONFIGURED",
        f"企业数据提供器未配置: {name}",
    )


def _provider_from_factory(name: str, factory: Callable[[], EnterpriseDataProvider]) -> EnterpriseDataProvider:
    try:
        provider = factory()
    except Exception as exc:
        raise _configured_provider_error(name) from exc
    if not all(callable(getattr(provider, method, None)) for method in _REQUIRED_PROVIDER_METHODS):
        raise _configured_provider_error(name)
    return provider


def get_enterprise_provider(settings=None, today: date | None = None) -> EnterpriseDataProvider:
    settings = get_settings() if settings is None else settings
    name = settings.enterprise_data_provider
    if name == "synthetic":
        from app.demo_data.synthetic_fab import SyntheticFabProvider
        return SyntheticFabProvider(settings=settings, today=today)
    factory = _ENTERPRISE_PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise _configured_provider_error(name)
    return _provider_from_factory(name, factory)



def enterprise_data_manifest() -> dict:
    return operations.read_enterprise_manifest(get_enterprise_provider(), current_principal())


def enterprise_fab_summary(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
) -> dict:
    return operations.read_enterprise_summary(
        get_enterprise_provider(), current_principal(),
        {
            "start": start,
            "end": end,
            "process_step": process_step,
            "equipment_id": equipment_id,
        },
    )


def query_enterprise_data(
    entity: str,
    limit: int = 20,
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
    product: str | None = None,
    status: str | None = None,
    signal_name: str | None = None,
) -> dict:
    allowed_filters = {
        "lots": {"start", "end", "product", "status"},
        "process-runs": {"start", "end", "process_step", "equipment_id"},
        "sensor-events": {"start", "end", "process_step", "equipment_id", "signal_name"},
    }
    if entity not in allowed_filters:
        raise EnterpriseDataError("UNKNOWN_ENTITY", "不支持的数据实体")
    values = locals()
    filters = {key: values[key] for key in allowed_filters[entity] if values.get(key) not in (None, "")}
    return operations.read_enterprise_page(get_enterprise_provider(), current_principal(), entity, min(max(limit, 1), 50), None, filters)
