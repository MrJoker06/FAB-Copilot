"""Process-local immutable publication and activation for declarative Skills.

Publication captures manifest and declared text resources before visibility. It
requires a quiescent source directory while making its two bounded reads; it
does not claim an operating-system-wide atomic multi-file snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import RLock

from .catalog import CatalogEntry, SkillCatalog, SkillReference
from .contracts import DependencyInventory, SkillManifest, SkillPackageError
from .loader import SkillLoader
from .manifest import validate_dependencies
from .package import LoadedResource, SkillPackage
from .resources import AGGREGATE_LIMIT, RESOURCE_LIMIT
from .versions import parse_version


def _error(code: str, message: str) -> SkillPackageError:
    return SkillPackageError(code, message)


def _validate_resources(
    manifest: SkillManifest, resources: tuple[LoadedResource, ...]
) -> tuple[LoadedResource, ...]:
    if not isinstance(resources, tuple) or any(
        not isinstance(item, LoadedResource) for item in resources
    ):
        raise _error("invalid_release", "release resources are invalid")
    if (
        tuple((item.path, item.kind) for item in resources)
        != tuple((item.path, item.kind) for item in manifest.resources)
        or len(resources) > 64
    ):
        raise _error("invalid_release", "release resources differ from manifest")
    total = 0
    for item in resources:
        if not isinstance(item.text, str):
            raise _error("invalid_release", "release resource text is invalid")
        size = len(item.text.encode("utf-8"))
        if size > RESOURCE_LIMIT:
            raise _error("resource_too_large", "release resource exceeds size limit")
        total += size
    if total > AGGREGATE_LIMIT:
        raise _error("resource_budget", "release resources exceed aggregate budget")
    return resources


@dataclass(frozen=True, slots=True)
class PublishedSkill:
    """A frozen Skill declaration and every declared text resource."""

    reference: SkillReference
    manifest: SkillManifest
    resources: tuple[LoadedResource, ...] = field(repr=False)
    source_root: Path = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reference, SkillReference)
            or not isinstance(self.manifest, SkillManifest)
            or not isinstance(self.source_root, Path)
            or not self.source_root.is_absolute()
            or self.reference.skill_id != self.manifest.skill_id
            or self.reference.version != self.manifest.version
            or self.manifest.status != "published"
        ):
            raise _error("invalid_release", "published skill is invalid")
        _validate_resources(self.manifest, self.resources)

    def resource(self, path: str) -> LoadedResource:
        if isinstance(path, str):
            for item in self.resources:
                if item.path == path:
                    return item
        raise _error("undeclared_resource", "release resource is not declared")


@dataclass(frozen=True, slots=True)
class ReleaseState:
    reference: SkillReference
    enabled: bool
    active: bool


class PublishedSkillCatalog(SkillCatalog):
    """A normal catalog backed by a frozen release rather than author files."""

    def __init__(self, release: PublishedSkill, inventory: DependencyInventory) -> None:
        if not isinstance(release, PublishedSkill) or not isinstance(
            inventory, DependencyInventory
        ):
            raise _error("invalid_release", "release catalog is invalid")
        validate_dependencies(release.manifest, inventory)
        super().__init__(
            inventory,
            (CatalogEntry(release.reference, release.source_root, release.manifest),),
        )
        object.__setattr__(self, "release", release)

    def current_entry(self, reference: SkillReference) -> CatalogEntry:
        return self.find(reference)


class PublishedSkillLoader(SkillLoader):
    """Reuse normal load/expand checks while supplying frozen resource strings."""

    def __init__(self, catalog: PublishedSkillCatalog) -> None:
        if not isinstance(catalog, PublishedSkillCatalog):
            raise _error(
                "invalid_release", "published loader requires a release catalog"
            )
        super().__init__(catalog)
        self._published_catalog = catalog
        self._release = catalog.release

    @property
    def catalog(self) -> PublishedSkillCatalog:
        return self._published_catalog

    @property
    def release(self) -> PublishedSkill:
        return self._release

    def _resource(
        self, entry: CatalogEntry, path: str, *, limit: int = RESOURCE_LIMIT
    ) -> LoadedResource:
        if entry.reference != self.release.reference:
            raise _error("invalid_release", "release entry is invalid")
        item = self.release.resource(path)
        if len(item.text.encode("utf-8")) > limit:
            raise _error(
                "resource_too_large", "resource exceeds the configured size limit"
            )
        return item


class SkillReleaseStore:
    """Explicit process-local release state; it has no global inventory or lookup."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._releases: dict[SkillReference, PublishedSkill] = {}
        self._enabled: set[SkillReference] = set()
        self._active: dict[str, SkillReference] = {}

    @staticmethod
    def _reference(value: SkillReference) -> SkillReference:
        if not isinstance(value, SkillReference):
            raise _error("invalid_skill_reference", "skill reference must be exact")
        return value

    def publish(
        self, root: Path | str, inventory: DependencyInventory
    ) -> PublishedSkill:
        """Capture a complete draft/published package before inserting it."""
        if not isinstance(inventory, DependencyInventory):
            raise _error("invalid_inventory", "release inventory is invalid")
        try:
            first = SkillPackage.open(root, inventory, require_published=False)
            if first.manifest.status not in {"draft", "published"}:
                raise _error("ineligible_status", "skill cannot be published")
            paths = tuple(item.path for item in first.manifest.resources)
            resources = first.read_resources(paths)
            second = SkillPackage.open(root, inventory, require_published=False)
            if (
                second.manifest != first.manifest
                or second.read_resources(paths) != resources
            ):
                raise _error("stale_catalog", "skill changed during publication")
            manifest = replace(first.manifest, status="published")
            release = PublishedSkill(
                SkillReference(manifest.skill_id, manifest.version),
                manifest,
                _validate_resources(manifest, resources),
                Path(root).absolute(),
            )
        except SkillPackageError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise _error(
                "invalid_release", "skill publication is unavailable"
            ) from error
        with self._lock:
            if release.reference in self._releases:
                raise _error(
                    "duplicate_release", "exact skill version is already published"
                )
            self._releases[release.reference] = release
            self._enabled.add(release.reference)
        return release

    def get(self, reference: SkillReference) -> PublishedSkill:
        reference = self._reference(reference)
        with self._lock:
            try:
                return self._releases[reference]
            except KeyError:
                raise _error("unknown_skill", "exact skill version is absent") from None

    def require_enabled(self, reference: SkillReference) -> PublishedSkill:
        release = self.get(reference)
        with self._lock:
            if reference not in self._enabled:
                raise _error("ineligible_status", "skill release is disabled")
        return release

    def is_enabled(self, reference: SkillReference) -> bool:
        reference = self._reference(reference)
        with self._lock:
            return reference in self._enabled

    def activate(self, reference: SkillReference) -> PublishedSkill:
        reference = self._reference(reference)
        with self._lock:
            try:
                release = self._releases[reference]
            except KeyError:
                raise _error("unknown_skill", "exact skill version is absent") from None
            if reference not in self._enabled:
                raise _error("ineligible_status", "skill release is disabled")
            self._active[reference.skill_id] = reference
        return release

    def active_reference(self, skill_id: str) -> SkillReference:
        if not isinstance(skill_id, str):
            raise _error("invalid_skill_reference", "skill id must be a string")
        with self._lock:
            try:
                return self._active[skill_id]
            except KeyError:
                raise _error(
                    "unknown_skill", "skill has no active exact version"
                ) from None

    def disable(self, reference: SkillReference) -> None:
        self.get(reference)
        with self._lock:
            self._enabled.discard(reference)
            if self._active.get(reference.skill_id) == reference:
                del self._active[reference.skill_id]

    def enable(self, reference: SkillReference) -> None:
        self.get(reference)
        with self._lock:
            self._enabled.add(reference)

    def rollback(self, reference: SkillReference) -> PublishedSkill:
        return self.activate(reference)

    def loader(
        self, reference: SkillReference, inventory: DependencyInventory
    ) -> PublishedSkillLoader:
        return PublishedSkillLoader(
            PublishedSkillCatalog(self.require_enabled(reference), inventory)
        )

    def states(self) -> tuple[ReleaseState, ...]:
        with self._lock:
            return tuple(
                ReleaseState(
                    ref, ref in self._enabled, self._active.get(ref.skill_id) == ref
                )
                for ref in sorted(
                    self._releases,
                    key=lambda item: (item.skill_id, parse_version(item.version)),
                )
            )
