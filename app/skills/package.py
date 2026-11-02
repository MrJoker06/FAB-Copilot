"""Explicit package opening and explicit declared-resource loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import DependencyInventory, SkillManifest, SkillPackageError
from .manifest import parse_manifest, validate_dependencies
from .resources import (
    AGGREGATE_LIMIT,
    MANIFEST_LIMIT,
    RESOURCE_LIMIT,
    read_resource_text,
)


@dataclass(frozen=True, slots=True)
class LoadedResource:
    path: str
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class SkillPackage:
    root: Path
    manifest: SkillManifest
    inventory: DependencyInventory

    @classmethod
    def open(
        cls,
        root: Path | str,
        inventory: DependencyInventory,
        *,
        require_published: bool = True,
    ) -> SkillPackage:
        package_root = Path(root)
        manifest = parse_manifest(
            read_resource_text(package_root, "manifest.json", limit=MANIFEST_LIMIT)
        )
        validate_dependencies(manifest, inventory, require_published=require_published)
        return cls(package_root, manifest, inventory)

    def read_resources(
        self, paths: tuple[str, ...] | list[str]
    ) -> tuple[LoadedResource, ...]:
        if not isinstance(paths, (tuple, list)):
            raise SkillPackageError(
                "invalid_resource_request", "resource request must contain unique paths"
            )
        try:
            unique = len(paths) == len(set(paths))
        except TypeError as error:
            raise SkillPackageError(
                "invalid_resource_request", "resource request must contain string paths"
            ) from error
        if not unique:
            raise SkillPackageError(
                "invalid_resource_request", "resource request must contain unique paths"
            )
        declared = {resource.path: resource for resource in self.manifest.resources}
        if any(not isinstance(path, str) or path not in declared for path in paths):
            raise SkillPackageError(
                "undeclared_resource",
                "requested resource is not declared by the manifest",
            )
        if len(paths) > 64:
            raise SkillPackageError(
                "resource_budget", "resource request exceeds aggregate budget"
            )
        loaded: list[LoadedResource] = []
        used = 0
        for path in paths:
            if used >= AGGREGATE_LIMIT:
                raise SkillPackageError(
                    "resource_budget", "resource request exceeds aggregate budget"
                )
            remaining = AGGREGATE_LIMIT - used
            text = read_resource_text(
                self.root, path, limit=min(RESOURCE_LIMIT, remaining)
            )
            used += len(text.encode("utf-8"))
            loaded.append(LoadedResource(path, declared[path].kind, text))
        return tuple(loaded)
