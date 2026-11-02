"""Standalone, declarative Skill package validation primitives.

This package deliberately does not discover, activate, or execute skills.
"""

from .contracts import DependencyInventory, SkillManifest, SkillPackageError
from .manifest import parse_manifest, validate_dependencies
from .package import SkillPackage

__all__ = [
    "DependencyInventory",
    "SkillManifest",
    "SkillPackage",
    "SkillPackageError",
    "parse_manifest",
    "validate_dependencies",
]
