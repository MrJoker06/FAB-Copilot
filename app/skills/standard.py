"""Discovery and loading of standard Agent Skills packages.

A standard package needs only ``SKILL.md``. Reading it never imports code or
grants execution; the optional project ``manifest.json`` decides whether the
package can be assembled into a controlled run, and that is reported
separately from whether the package is well formed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .contracts import SkillManifest, SkillPackageError
from .frontmatter import SkillDocument
from .manifest import load_manifest, read_skill_document

EXECUTION_EXTENSION = "execution_extension"
NO_EXECUTION_EXTENSION = "no_execution_extension"


@dataclass(frozen=True, slots=True)
class StandardSkill:
    root: Path
    document: SkillDocument
    manifest: SkillManifest | None

    @property
    def execution_status(self) -> str:
        return NO_EXECUTION_EXTENSION if self.manifest is None else EXECUTION_EXTENSION

    @property
    def execution_authorized(self) -> bool:
        return False

    @property
    def instructions(self) -> str:
        return self.document.body


def inspect_skill(root: Path | str) -> StandardSkill:
    """Validate one standard package and its optional execution extension."""
    if not isinstance(root, (Path, str)):
        raise SkillPackageError("invalid_package", "package root is invalid")
    package_root = Path(root).absolute()
    document = read_skill_document(package_root)
    manifest = None
    if os.path.lexists(package_root / "manifest.json"):
        manifest = load_manifest(package_root)
        if manifest.skill_id != document.name:
            raise SkillPackageError(
                "invalid_manifest", "manifest skill id differs from SKILL.md name"
            )
    return StandardSkill(package_root, document, manifest)
