"""Strict JSON decoding and dependency checking for declarative Skills."""

from __future__ import annotations

import json
from typing import Any

from .contracts import (
    ComponentReference,
    DependencyInventory,
    ResourceDeclaration,
    SkillManifest,
    SkillPackageError,
    ToolRequirement,
)
from .versions import parse_version_requirement

_FIELDS = frozenset(
    {
        "schema_version",
        "skill_id",
        "version",
        "title",
        "description",
        "status",
        "process_steps",
        "required_inputs",
        "tools",
        "execution_modes",
        "workflow",
        "evidence_policy",
        "resources",
    }
)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SkillPackageError("invalid_json", "JSON contains duplicate keys")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise SkillPackageError("invalid_json", "JSON contains a non-finite number")


def _tuple_strings(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SkillPackageError(
            "invalid_manifest", f"{field_name} must be a string list"
        )
    return tuple(value)


def _object(value: object, field_name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise SkillPackageError(
            "invalid_manifest", f"{field_name} has missing or unknown fields"
        )
    return value


def parse_json_document(text: object) -> object:
    if not isinstance(text, str):
        raise SkillPackageError("invalid_json", "manifest must be UTF-8 text")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except SkillPackageError:
        raise
    except (RecursionError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SkillPackageError("invalid_json", "manifest is not valid JSON") from error
    return value


def parse_manifest(text: object) -> SkillManifest:
    value = parse_json_document(text)
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise SkillPackageError(
            "invalid_manifest", "manifest has missing or unknown fields"
        )
    tools_value = value["tools"]
    resources_value = value["resources"]
    if not isinstance(tools_value, list) or not isinstance(resources_value, list):
        raise SkillPackageError("invalid_manifest", "tools and resources must be lists")
    tools = tuple(
        ToolRequirement(**_object(item, "tool", {"name", "version"}))
        for item in tools_value
    )
    resources = tuple(
        ResourceDeclaration(**_object(item, "resource", {"path", "kind"}))
        for item in resources_value
    )
    workflow = ComponentReference(
        **_object(value["workflow"], "workflow", {"component_id", "version"})
    )
    evidence = ComponentReference(
        **_object(
            value["evidence_policy"], "evidence policy", {"component_id", "version"}
        )
    )
    scalar_fields = (
        "schema_version",
        "skill_id",
        "version",
        "title",
        "description",
        "status",
    )
    if any(not isinstance(value[field], str) for field in scalar_fields):
        raise SkillPackageError(
            "invalid_manifest", "manifest scalar fields must be strings"
        )
    return SkillManifest(
        **{field: value[field] for field in scalar_fields},
        process_steps=_tuple_strings(value["process_steps"], "process steps"),
        required_inputs=_tuple_strings(value["required_inputs"], "required inputs"),
        tools=tools,
        execution_modes=_tuple_strings(value["execution_modes"], "execution modes"),
        workflow=workflow,
        evidence_policy=evidence,
        resources=resources,
    )


def validate_dependencies(
    manifest: SkillManifest,
    inventory: DependencyInventory,
    *,
    require_published: bool = True,
) -> None:
    if require_published and manifest.status != "published":
        raise SkillPackageError(
            "ineligible_status", "skill status is not eligible for runtime use"
        )
    for tool in manifest.tools:
        actual = inventory.tools.get(tool.name)
        if actual is None:
            raise SkillPackageError(
                "missing_dependency", "declared tool is missing from inventory"
            )
        if not parse_version_requirement(tool.version).matches(actual):
            raise SkillPackageError(
                "incompatible_dependency", "declared tool version is incompatible"
            )
    for reference, values, label in (
        (manifest.workflow, inventory.workflows, "workflow"),
        (manifest.evidence_policy, inventory.evidence_policies, "evidence policy"),
    ):
        actual = values.get(reference.component_id)
        if actual is None:
            raise SkillPackageError(
                "missing_dependency", f"declared {label} is missing from inventory"
            )
        if actual != reference.version:
            raise SkillPackageError(
                "incompatible_dependency", f"declared {label} version is incompatible"
            )
