"""Immutable declarations for explicitly assembled agent applications."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tools.contracts import TOOL_CONTRACT_VERSION

_EXACT_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _name(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128
        or "*" in value
    ):
        raise ValueError(f"{field} must be a non-empty explicit name")


def _version(value: object, field: str) -> None:
    if not isinstance(value, str) or _EXACT_VERSION.fullmatch(value) is None:
        raise ValueError(f"{field} must be an exact x.y.z version")


@dataclass(frozen=True, slots=True)
class ComponentReference:
    component_id: str
    version: str

    def __post_init__(self) -> None:
        _name(self.component_id, "component_id")
        _version(self.version, "version")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    version: str
    role: str
    instructions: str
    tools: tuple[ComponentReference, ...]
    model_policy: ComponentReference
    default_policy: ComponentReference
    skill_refs: tuple[ComponentReference, ...] = ()
    schema_version: str = "1.0.0"
    runtime_contract_version: str = "1.0.0"
    tool_contract_version: str = TOOL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _name(self.agent_id, "agent_id")
        _version(self.version, "version")
        _name(self.role, "role")
        if not isinstance(self.instructions, str) or not self.instructions.strip():
            raise ValueError("instructions must be a non-empty string")
        for field, value in (("tools", self.tools), ("skill_refs", self.skill_refs)):
            if not isinstance(value, tuple) or any(
                not isinstance(item, ComponentReference) for item in value
            ):
                raise ValueError(f"{field} must be a tuple of ComponentReference")
            identifiers = [item.component_id for item in value]
            if len(set(identifiers)) != len(identifiers):
                raise ValueError(f"{field} must not repeat component ids")
        if not isinstance(self.model_policy, ComponentReference) or not isinstance(
            self.default_policy, ComponentReference
        ):
            raise TypeError("policy references must be ComponentReference")
        if self.schema_version != "1.0.0" or self.runtime_contract_version != "1.0.0":
            raise ValueError("definition contracts must be version 1.0.0")
        if self.tool_contract_version != TOOL_CONTRACT_VERSION:
            raise ValueError("tool_contract_version must match TOOL_CONTRACT_VERSION")

    @property
    def allowed_tools(self) -> frozenset[str]:
        return frozenset(reference.component_id for reference in self.tools)
