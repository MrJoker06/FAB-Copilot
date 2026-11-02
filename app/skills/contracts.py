"""Immutable declarations used by the Skill manifest boundary."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_STATUS = frozenset({"draft", "published", "disabled", "retired"})
_MODES = frozenset({"ready", "loop"})
_KINDS = frozenset({"instructions", "reference", "scenario"})


class SkillPackageError(ValueError):
    """A stable, host-information-free error for invalid skill packages."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SkillPackageError(
            "invalid_manifest", f"{field_name} must be a bounded identifier"
        )
    return value


def _unique(values: tuple[str, ...], field_name: str) -> None:
    if not values or not all(isinstance(value, str) for value in values):
        raise SkillPackageError(
            "invalid_manifest", f"{field_name} must be a non-empty unique list"
        )
    if len(values) != len(set(values)):
        raise SkillPackageError(
            "invalid_manifest", f"{field_name} must be a non-empty unique list"
        )
    for value in values:
        require_identifier(value, field_name)


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    name: str
    version: str

    def __post_init__(self) -> None:
        require_identifier(self.name, "tool name")
        from .versions import parse_version_requirement

        parse_version_requirement(self.version)


@dataclass(frozen=True, slots=True)
class ComponentReference:
    component_id: str
    version: str

    def __post_init__(self) -> None:
        require_identifier(self.component_id, "component id")
        from .versions import parse_version

        parse_version(self.version)


@dataclass(frozen=True, slots=True)
class ResourceDeclaration:
    path: str
    kind: str

    def __post_init__(self) -> None:
        from .resources import validate_resource_path

        validate_resource_path(self.path)
        if not isinstance(self.kind, str) or self.kind not in _KINDS:
            raise SkillPackageError("invalid_manifest", "resource kind is invalid")


@dataclass(frozen=True, slots=True)
class SkillManifest:
    schema_version: str
    skill_id: str
    version: str
    title: str
    description: str
    status: str
    process_steps: tuple[str, ...]
    required_inputs: tuple[str, ...]
    tools: tuple[ToolRequirement, ...]
    execution_modes: tuple[str, ...]
    workflow: ComponentReference
    evidence_policy: ComponentReference
    resources: tuple[ResourceDeclaration, ...]

    def __post_init__(self) -> None:
        from .versions import parse_version

        if not all(
            isinstance(value, tuple)
            for value in (
                self.process_steps,
                self.required_inputs,
                self.tools,
                self.execution_modes,
                self.resources,
            )
        ):
            raise SkillPackageError(
                "invalid_manifest", "manifest collections must be immutable tuples"
            )
        if (
            not all(isinstance(value, ToolRequirement) for value in self.tools)
            or not all(
                isinstance(value, ResourceDeclaration) for value in self.resources
            )
            or not isinstance(self.workflow, ComponentReference)
            or not isinstance(self.evidence_policy, ComponentReference)
        ):
            raise SkillPackageError(
                "invalid_manifest", "manifest nested declarations have invalid types"
            )
        if self.schema_version != "1.0.0":
            raise SkillPackageError(
                "unsupported_schema", "manifest schema version is unsupported"
            )
        require_identifier(self.skill_id, "skill id")
        parse_version(self.version)
        if not all(
            isinstance(value, str) and value.strip() and len(value) <= 512
            for value in (self.title, self.description)
        ):
            raise SkillPackageError(
                "invalid_manifest",
                "title and description must be bounded non-empty text",
            )
        if not isinstance(self.status, str) or self.status not in _STATUS:
            raise SkillPackageError("invalid_manifest", "manifest status is invalid")
        _unique(self.process_steps, "process steps")
        _unique(self.required_inputs, "required inputs")
        if (
            not self.execution_modes
            or not all(isinstance(value, str) for value in self.execution_modes)
            or len(self.execution_modes) != len(set(self.execution_modes))
            or not set(self.execution_modes) <= _MODES
        ):
            raise SkillPackageError(
                "invalid_manifest",
                "execution modes must be unique ready or loop values",
            )
        if len(self.resources) > 64 or not self.resources:
            raise SkillPackageError(
                "invalid_manifest", "resources must contain between one and 64 entries"
            )
        paths = [
            unicodedata.normalize("NFC", resource.path).casefold()
            for resource in self.resources
        ]
        if len(paths) != len(set(paths)):
            raise SkillPackageError(
                "invalid_manifest", "resource paths must be cross-platform unique"
            )
        instructions = [
            resource for resource in self.resources if resource.kind == "instructions"
        ]
        if len(instructions) != 1 or instructions[0].path != "SKILL.md":
            raise SkillPackageError(
                "invalid_manifest",
                "exactly one instructions resource named SKILL.md is required",
            )
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise SkillPackageError("invalid_manifest", "tool names must be unique")


@dataclass(frozen=True, slots=True)
class DependencyInventory:
    tools: Mapping[str, str] = field(default_factory=dict)
    workflows: Mapping[str, str] = field(default_factory=dict)
    evidence_policies: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, values in (
            ("tools", self.tools),
            ("workflows", self.workflows),
            ("evidence policies", self.evidence_policies),
        ):
            if not isinstance(values, Mapping):
                raise SkillPackageError(
                    "invalid_inventory", f"{name} inventory must be an object"
                )
            copied: dict[str, str] = {}
            for key, value in values.items():
                require_identifier(key, f"{name} identifier")
                if not isinstance(value, str):
                    raise SkillPackageError(
                        "invalid_inventory",
                        f"{name} inventory versions must be strings",
                    )
                from .versions import parse_version

                parse_version(value)
                copied[key] = value
            object.__setattr__(self, name.replace(" ", "_"), MappingProxyType(copied))
