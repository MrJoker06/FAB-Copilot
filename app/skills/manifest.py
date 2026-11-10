"""Strict JSON decoding and dependency checking for declarative Skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    SCHEMA_V2,
    ComponentReference,
    DependencyInventory,
    ResourceDeclaration,
    SkillManifest,
    SkillPackageError,
    ToolRequirement,
)
from .frontmatter import SkillDocument, parse_skill_document
from .resources import MANIFEST_LIMIT, RESOURCE_LIMIT, read_resource_text
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
_V2_REQUIRED = frozenset({"schema_version", "version", "status"})
_V2_OPTIONAL = frozenset(
    {
        "title",
        "process_steps",
        "required_inputs",
        "tools",
        "execution_modes",
        "workflow",
        "evidence_policy",
        "resources",
    }
)
_REFERENCE_FIELDS = {"component_id", "version"}


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


def _tools(value: object) -> tuple[ToolRequirement, ...]:
    if not isinstance(value, list):
        raise SkillPackageError("invalid_manifest", "tools and resources must be lists")
    return tuple(
        ToolRequirement(**_object(item, "tool", {"name", "version"})) for item in value
    )


def _resources(value: object) -> tuple[ResourceDeclaration, ...]:
    if not isinstance(value, list):
        raise SkillPackageError("invalid_manifest", "tools and resources must be lists")
    return tuple(
        ResourceDeclaration(**_object(item, "resource", {"path", "kind"}))
        for item in value
    )


def _evidence_policy(value: object) -> ComponentReference:
    # A declared policy that cannot be parsed is a distinct failure: callers
    # must not mistake it for "no policy configured".
    try:
        return ComponentReference(
            **_object(value, "evidence policy", _REFERENCE_FIELDS)
        )
    except SkillPackageError as error:
        raise SkillPackageError(
            "invalid_evidence_policy", "declared evidence policy is invalid"
        ) from error


def _parse_v1(value: dict[str, Any]) -> SkillManifest:
    if set(value) != _FIELDS:
        raise SkillPackageError(
            "invalid_manifest", "manifest has missing or unknown fields"
        )
    tools = _tools(value["tools"])
    resources = _resources(value["resources"])
    workflow = ComponentReference(
        **_object(value["workflow"], "workflow", _REFERENCE_FIELDS)
    )
    evidence = _evidence_policy(value["evidence_policy"])
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


def _parse_v2(value: dict[str, Any], document: SkillDocument | None) -> SkillManifest:
    keys = set(value)
    if not _V2_REQUIRED <= keys or not keys <= _V2_REQUIRED | _V2_OPTIONAL:
        raise SkillPackageError(
            "invalid_manifest", "manifest has missing or unknown fields"
        )
    if not isinstance(document, SkillDocument):
        raise SkillPackageError(
            "invalid_manifest", "schema 2.0.0 requires SKILL.md frontmatter"
        )
    scalars = [value["version"], value["status"], value.get("title", document.name)]
    if any(not isinstance(item, str) for item in scalars):
        raise SkillPackageError(
            "invalid_manifest", "manifest scalar fields must be strings"
        )
    resources = _resources(value.get("resources", []))
    if not any(item.path == "SKILL.md" for item in resources):
        resources = (ResourceDeclaration("SKILL.md", "instructions"), *resources)
    workflow = None
    if "workflow" in value:
        workflow = ComponentReference(
            **_object(value["workflow"], "workflow", _REFERENCE_FIELDS)
        )
    evidence = None
    if "evidence_policy" in value:
        evidence = _evidence_policy(value["evidence_policy"])
    return SkillManifest(
        schema_version=SCHEMA_V2,
        skill_id=document.name,
        version=value["version"],
        title=value.get("title", document.name),
        description=document.description,
        status=value["status"],
        process_steps=_tuple_strings(value.get("process_steps", []), "process steps"),
        required_inputs=_tuple_strings(
            value.get("required_inputs", []), "required inputs"
        ),
        tools=_tools(value.get("tools", [])),
        execution_modes=_tuple_strings(
            value.get("execution_modes", []), "execution modes"
        ),
        workflow=workflow,
        evidence_policy=evidence,
        resources=resources,
    )


def parse_manifest(
    text: object, *, document: SkillDocument | None = None
) -> SkillManifest:
    """Parse ``manifest.json``; schema 2.0.0 also needs the parsed SKILL.md."""
    value = parse_json_document(text)
    if not isinstance(value, dict):
        raise SkillPackageError(
            "invalid_manifest", "manifest has missing or unknown fields"
        )
    if value.get("schema_version") == SCHEMA_V2:
        return _parse_v2(value, document)
    return _parse_v1(value)


def read_skill_document(root: Path) -> SkillDocument:
    """Read and validate standard SKILL.md metadata for one package directory."""
    document = parse_skill_document(
        read_resource_text(root, "SKILL.md", limit=RESOURCE_LIMIT)
    )
    if document.name != Path(root).name:
        raise SkillPackageError(
            "invalid_skill_document", "skill name must match its directory name"
        )
    return document


def load_manifest(root: Path) -> SkillManifest:
    """Read the project execution extension of one package directory."""
    text = read_resource_text(root, "manifest.json", limit=MANIFEST_LIMIT)
    value = parse_json_document(text)
    document = None
    if isinstance(value, dict) and value.get("schema_version") == SCHEMA_V2:
        document = read_skill_document(root)
    return parse_manifest(text, document=document)


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
        if reference is None:
            continue
        actual = values.get(reference.component_id)
        if actual is None:
            raise SkillPackageError(
                "missing_dependency", f"declared {label} is missing from inventory"
            )
        if actual != reference.version:
            raise SkillPackageError(
                "incompatible_dependency", f"declared {label} version is incompatible"
            )
