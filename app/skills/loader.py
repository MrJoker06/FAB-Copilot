"""Explicit, incremental Skill resource loading from a verified catalog entry."""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import CatalogEntry, SkillCatalog, SkillReference
from .contracts import SkillManifest, SkillPackageError
from .package import LoadedResource
from .resources import AGGREGATE_LIMIT, RESOURCE_LIMIT, read_resource_text


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    reference: SkillReference
    manifest: SkillManifest
    loaded_resources: tuple[LoadedResource, ...]
    _catalog_token: object = field(repr=False, compare=False)

    @property
    def execution_authorized(self) -> bool:
        return False


class SkillLoader:
    """Loads only an explicitly selected exact reference from one catalog snapshot."""

    def __init__(self, catalog: SkillCatalog) -> None:
        if not isinstance(catalog, SkillCatalog):
            raise SkillPackageError(
                "invalid_catalog", "loader requires a skill catalog"
            )
        self._catalog = catalog
        self._token = object()

    def _eligible(self, reference: SkillReference) -> CatalogEntry:
        entry = self._catalog.current_entry(reference)
        if not entry.available:
            raise SkillPackageError(
                entry.unavailable_reason or "unavailable_skill", "skill is unavailable"
            )
        return entry

    @staticmethod
    def _resource(
        entry: CatalogEntry, path: str, *, limit: int = RESOURCE_LIMIT
    ) -> LoadedResource:
        declared = {item.path: item for item in entry.manifest.resources}
        if path not in declared:
            raise SkillPackageError(
                "undeclared_resource",
                "requested resource is not declared by the manifest",
            )
        text = read_resource_text(entry.root, path, limit=limit)
        return LoadedResource(path, declared[path].kind, text)

    @staticmethod
    def _budget(resources: tuple[LoadedResource, ...]) -> None:
        if (
            len(resources) > 64
            or sum(len(item.text.encode("utf-8")) for item in resources)
            > AGGREGATE_LIMIT
        ):
            raise SkillPackageError(
                "resource_budget", "resource request exceeds aggregate budget"
            )

    def load(self, reference: SkillReference) -> SkillSnapshot:
        entry = self._eligible(reference)
        loaded = (self._resource(entry, "SKILL.md"),)
        self._budget(loaded)
        return SkillSnapshot(reference, entry.manifest, loaded, self._token)

    def expand(
        self, snapshot: SkillSnapshot, paths: tuple[str, ...] | list[str]
    ) -> SkillSnapshot:
        if (
            not isinstance(snapshot, SkillSnapshot)
            or snapshot._catalog_token is not self._token
        ):
            raise SkillPackageError(
                "invalid_snapshot", "snapshot belongs to a different loader"
            )
        if not isinstance(paths, (tuple, list)) or any(
            not isinstance(path, str) for path in paths
        ):
            raise SkillPackageError(
                "invalid_resource_request", "resource request must contain string paths"
            )
        if len(paths) != len(set(paths)):
            raise SkillPackageError(
                "invalid_resource_request", "resource request must contain unique paths"
            )
        entry = self._eligible(snapshot.reference)
        if entry.manifest != snapshot.manifest:
            raise SkillPackageError(
                "stale_catalog", "skill declaration changed; rebuild catalog"
            )
        existing = {item.path for item in snapshot.loaded_resources}
        additions = tuple(path for path in paths if path not in existing)
        declared = {item.path for item in entry.manifest.resources}
        if any(path not in declared for path in additions):
            raise SkillPackageError(
                "undeclared_resource",
                "requested resource is not declared by the manifest",
            )
        # Validate the complete request before opening any new content.
        if len(snapshot.loaded_resources) + len(additions) > 64:
            raise SkillPackageError(
                "resource_budget", "resource request exceeds aggregate budget"
            )
        resources = list(snapshot.loaded_resources)
        used = sum(len(item.text.encode("utf-8")) for item in resources)
        for path in additions:
            if used >= AGGREGATE_LIMIT:
                raise SkillPackageError(
                    "resource_budget", "resource request exceeds aggregate budget"
                )
            resource = self._resource(
                entry, path, limit=min(RESOURCE_LIMIT, AGGREGATE_LIMIT - used)
            )
            resources.append(resource)
            used += len(resource.text.encode("utf-8"))
        resources = tuple(resources)
        self._budget(resources)
        return SkillSnapshot(
            snapshot.reference, snapshot.manifest, resources, self._token
        )
