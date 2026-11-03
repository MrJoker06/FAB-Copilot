"""Deterministic metadata-only Skill selection."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import CatalogEntry, SkillCatalog, SkillReference
from .contracts import SkillPackageError, require_identifier


@dataclass(frozen=True, slots=True)
class DiscoveryQuery:
    workflow_id: str | None = None
    process_step: str | None = None
    execution_mode: str | None = None
    available_inputs: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name, value in (
            ("workflow id", self.workflow_id),
            ("process step", self.process_step),
        ):
            if value is not None:
                require_identifier(value, name)
        if self.execution_mode is not None and (
            not isinstance(self.execution_mode, str)
            or self.execution_mode not in {"ready", "loop"}
        ):
            raise SkillPackageError(
                "invalid_discovery_query", "execution mode is invalid"
            )
        if not isinstance(self.available_inputs, frozenset) or any(
            not isinstance(value, str) for value in self.available_inputs
        ):
            raise SkillPackageError(
                "invalid_discovery_query", "available inputs must be immutable names"
            )
        for value in self.available_inputs:
            require_identifier(value, "available input")


@dataclass(frozen=True, slots=True)
class DiscoveryRejection:
    reference: SkillReference
    reason: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    candidates: tuple[CatalogEntry, ...]
    rejections: tuple[DiscoveryRejection, ...]

    @property
    def execution_authorized(self) -> bool:
        return False


def discover(catalog: SkillCatalog, query: DiscoveryQuery) -> DiscoveryResult:
    if not isinstance(catalog, SkillCatalog) or not isinstance(query, DiscoveryQuery):
        raise SkillPackageError(
            "invalid_discovery_query", "catalog and query are required"
        )
    candidates: list[CatalogEntry] = []
    rejected: list[DiscoveryRejection] = []
    for entry in catalog.entries:
        manifest = entry.manifest
        reason = entry.unavailable_reason
        if (
            reason is None
            and query.workflow_id is not None
            and manifest.workflow.component_id != query.workflow_id
        ):
            reason = "workflow_mismatch"
        if (
            reason is None
            and query.process_step is not None
            and query.process_step not in manifest.process_steps
        ):
            reason = "process_step_mismatch"
        if (
            reason is None
            and query.execution_mode is not None
            and query.execution_mode not in manifest.execution_modes
        ):
            reason = "execution_mode_mismatch"
        if (
            reason is None
            and not set(manifest.required_inputs) <= query.available_inputs
        ):
            reason = "missing_required_input"
        if reason is None:
            candidates.append(entry)
        else:
            rejected.append(DiscoveryRejection(entry.reference, reason))
    return DiscoveryResult(tuple(candidates), tuple(rejected))
