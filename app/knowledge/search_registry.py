"""Explicit composition registry for factory knowledge-search backends."""
from __future__ import annotations

import re
from collections.abc import Callable

from .search_contracts import FactoryCatalogBackend, FactorySearchBackend
from .sqlite_backend import SqliteFactorySearchBackend


class FactorySearchBackendError(ValueError):
    """Raised when configured factory search cannot be safely composed."""


class FactoryCatalogBackendError(RuntimeError):
    """Raised when a selected search backend cannot safely serve a catalogue."""


_BACKEND_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESERVED_BACKENDS = frozenset({"sqlite"})
_FACTORIES: dict[str, Callable[[], FactorySearchBackend]] = {}
_REQUIRED_METHODS = ("defect_aliases", "search")
_CATALOG_METHODS = (
    "list_knowledge_documents",
    "get_knowledge_document",
    "list_historical_cases",
    "get_historical_case",
)


def register_factory_search_backend(name: str, factory: Callable[[], FactorySearchBackend]) -> None:
    """Register a non-SQLite backend at application startup.

    Discovery is deliberately absent: setting ``FAB_FACTORY_SEARCH_BACKEND``
    to a company adapter requires the composition root to register it first.
    """
    if not isinstance(name, str) or not _BACKEND_NAME.fullmatch(name):
        raise ValueError("factory search backend name must be lowercase and use letters, digits, '-' or '_'")
    if name in _RESERVED_BACKENDS:
        raise ValueError(f"factory search backend name is reserved: {name}")
    if not callable(factory):
        raise TypeError("factory search backend factory must be callable")
    if name in _FACTORIES:
        raise ValueError(f"factory search backend is already registered: {name}")
    _FACTORIES[name] = factory


def _configuration_error(name: str) -> FactorySearchBackendError:
    return FactorySearchBackendError(f"factory search backend is not configured: {name}")


def _catalog_configuration_error(name: str) -> FactoryCatalogBackendError:
    return FactoryCatalogBackendError(f"factory catalog backend is not configured: {name}")


def _from_factory(name: str, factory: Callable[[], FactorySearchBackend]) -> FactorySearchBackend:
    try:
        backend = factory()
    except Exception as exc:
        raise _configuration_error(name) from exc
    if not all(callable(getattr(backend, method, None)) for method in _REQUIRED_METHODS):
        raise _configuration_error(name)
    return backend


def get_factory_search_backend(name: str) -> FactorySearchBackend:
    """Resolve an explicitly selected backend without reading application settings."""
    if name == "sqlite":
        return SqliteFactorySearchBackend()
    factory = _FACTORIES.get(name)
    if factory is None:
        raise _configuration_error(name)
    return _from_factory(name, factory)


def get_factory_catalog_backend(name: str) -> FactoryCatalogBackend:
    """Resolve the selected backend only when it implements catalogue access.

    Search-only adapters remain valid for the hot path.  Catalogue browsing
    never substitutes the local SQLite adapter when these methods are absent.
    """
    try:
        backend = get_factory_search_backend(name)
    except FactorySearchBackendError as exc:
        raise _catalog_configuration_error(name) from exc
    if not all(callable(getattr(backend, method, None)) for method in _CATALOG_METHODS):
        raise _catalog_configuration_error(name)
    return backend  # type: ignore[return-value]
