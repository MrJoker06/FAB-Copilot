"""Explicit, immutable catalog construction for declarative Skill packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .contracts import DependencyInventory, SkillManifest, SkillPackageError
from .manifest import parse_manifest, validate_dependencies
from .resources import MANIFEST_LIMIT, read_resource_text
from .versions import parse_version


@dataclass(frozen=True, slots=True)
class SkillReference:
    """An exact Skill identifier; it intentionally has no ``latest`` form."""

    skill_id: str
    version: str

    def __post_init__(self) -> None:
        from .contracts import require_identifier

        require_identifier(self.skill_id, "skill id")
        parse_version(self.version)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    reference: SkillReference
    root: Path = field(repr=False)
    manifest: SkillManifest
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reference, SkillReference)
            or not isinstance(self.root, Path)
            or not isinstance(self.manifest, SkillManifest)
        ):
            raise SkillPackageError("invalid_catalog", "catalog entry is invalid")
        if not self.root.is_absolute():
            raise SkillPackageError("invalid_catalog", "catalog root must be absolute")
        if (
            self.reference.skill_id != self.manifest.skill_id
            or self.reference.version != self.manifest.version
        ):
            raise SkillPackageError(
                "invalid_catalog", "catalog entry reference differs from manifest"
            )
        if self.unavailable_reason is not None and not isinstance(
            self.unavailable_reason, str
        ):
            raise SkillPackageError(
                "invalid_catalog", "catalog availability is invalid"
            )

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


def _catalog_root(value: Path | str) -> Path:
    if not isinstance(value, (Path, str)):
        raise SkillPackageError("invalid_package", "package root is invalid")
    # ``absolute`` deliberately does not resolve links; MOD-016 validates them
    # during every actual resource open.
    return Path(value).absolute()


def _manifest(root: Path) -> SkillManifest:
    return parse_manifest(
        read_resource_text(root, "manifest.json", limit=MANIFEST_LIMIT)
    )


def _entry(root: Path, inventory: DependencyInventory) -> CatalogEntry:
    manifest = _manifest(root)
    reference = SkillReference(manifest.skill_id, manifest.version)
    try:
        validate_dependencies(manifest, inventory)
    except SkillPackageError as error:
        if error.code not in {
            "ineligible_status",
            "missing_dependency",
            "incompatible_dependency",
        }:
            raise
        return CatalogEntry(reference, root, manifest, error.code)
    return CatalogEntry(reference, root, manifest)


@dataclass(frozen=True, slots=True)
class SkillCatalog:
    """A caller-built snapshot. It neither searches directories nor mutates state."""

    inventory: DependencyInventory
    entries: tuple[CatalogEntry, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.inventory, DependencyInventory)
            or not isinstance(self.entries, tuple)
            or any(not isinstance(entry, CatalogEntry) for entry in self.entries)
        ):
            raise SkillPackageError(
                "invalid_catalog", "catalog declarations are invalid"
            )
        references = tuple(entry.reference for entry in self.entries)
        if len(references) != len(set(references)):
            raise SkillPackageError(
                "duplicate_skill", "catalog repeats an exact skill version"
            )
        for entry in self.entries:
            reason: str | None = None
            try:
                validate_dependencies(entry.manifest, self.inventory)
            except SkillPackageError as error:
                if error.code not in {
                    "ineligible_status",
                    "missing_dependency",
                    "incompatible_dependency",
                }:
                    raise
                reason = error.code
            if entry.unavailable_reason != reason:
                raise SkillPackageError(
                    "invalid_catalog", "catalog availability differs from dependencies"
                )
        object.__setattr__(
            self,
            "entries",
            tuple(
                sorted(
                    self.entries,
                    key=lambda entry: (
                        entry.reference.skill_id,
                        parse_version(entry.reference.version),
                    ),
                )
            ),
        )

    @classmethod
    def build(
        cls,
        roots: tuple[Path | str, ...] | list[Path | str],
        inventory: DependencyInventory,
    ) -> SkillCatalog:
        if not isinstance(roots, (tuple, list)) or not roots:
            raise SkillPackageError(
                "invalid_catalog", "catalog roots must be a non-empty list"
            )
        if not isinstance(inventory, DependencyInventory):
            raise SkillPackageError("invalid_inventory", "catalog inventory is invalid")
        entries = tuple(_entry(_catalog_root(root), inventory) for root in roots)
        return cls(inventory, entries)

    def find(self, reference: SkillReference) -> CatalogEntry:
        if not isinstance(reference, SkillReference):
            raise SkillPackageError(
                "invalid_skill_reference", "skill reference must be exact"
            )
        for entry in self.entries:
            if entry.reference == reference:
                return entry
        raise SkillPackageError(
            "unknown_skill", "exact skill version is absent from catalog"
        )

    def current_entry(self, reference: SkillReference) -> CatalogEntry:
        """Read only the current manifest and reject stale catalog declarations."""
        entry = self.find(reference)
        current = _entry(entry.root, self.inventory)
        if current != entry:
            raise SkillPackageError(
                "stale_catalog", "skill declaration changed; rebuild catalog"
            )
        return entry
