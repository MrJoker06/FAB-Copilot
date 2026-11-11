"""Opt-in, controlled Skill composition for the typed Agent pilot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..agent_runtime.definition import AgentDefinition
from ..agent_runtime.execution.runtime_contracts import ModelMessage
from ..agent_runtime.tools.definition import ToolBinding
from ..intent_runtime.contracts import IntentRoute
from ..skills.catalog import SkillCatalog, SkillReference
from ..skills.contracts import (
    SCHEMA_V2,
    ComponentReference,
    DependencyInventory,
    SkillPackageError,
)
from ..skills.discovery import DiscoveryQuery, discover
from ..skills.frontmatter import parse_skill_document
from ..skills.loader import SkillLoader, SkillSnapshot
from .litho_cpk_workflow import LithoCpkWorkflow, LithoCpkWorkflowError

if TYPE_CHECKING:
    from ..evidence.validator import EvidenceObservation, EvidenceValidation
    from app.planning_runtime.playbook_contracts import PlaybookSelection
    from ..planning_runtime.contracts import ExecutionPlan
    from ..skills.releases import SkillReleaseStore


class SkillAssemblyError(ValueError):
    """A non-diagnostic failure at the controlled composition boundary."""

    def __init__(self, message: str, *, reason: str = "invalid_assembly") -> None:
        super().__init__(message)
        self.reason = reason


EVIDENCE_NOT_CONFIGURED = "not_configured"
EVIDENCE_CHECKED = "checked"
EVIDENCE_CHECK_FAILED = "check_failed"
# Strengths that mean the declared policy ran but the evidence cannot support
# a diagnostic conclusion.
_INSUFFICIENT_STRENGTHS = frozenset({"insufficient", "hypothesis_only"})


@dataclass(frozen=True, slots=True)
class SkillEvidenceOutcome:
    """Domain evidence-policy result kept apart from basic tool execution checks.

    A not_configured status never implies a pass. A declared policy that cannot
    be parsed or resolved fails assembly (reason invalid_evidence_policy or a
    dependency reason) instead of reaching this object.
    """

    status: str
    policy: ComponentReference | None
    validation: EvidenceValidation | None = None

    @property
    def evidence_sufficient(self) -> bool | None:
        if self.status != EVIDENCE_CHECKED or self.validation is None:
            return None
        return (
            self.validation.status == "validated"
            and self.validation.allowed_conclusion_strength
            not in _INSUFFICIENT_STRENGTHS
        )


@dataclass(frozen=True, slots=True)
class SkillExecutionRequest:
    question: str
    route: IntentRoute
    mode: str
    resource_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.question, str)
            or not self.question.strip()
            or not isinstance(self.route, IntentRoute)
            or not isinstance(self.mode, str)
            or self.mode not in {"ready", "loop"}
            or not isinstance(self.resource_paths, tuple)
            or any(not isinstance(item, str) for item in self.resource_paths)
        ):
            raise SkillAssemblyError("invalid skill request")
        if not self.route.process_steps or not self.route.time_range:
            raise SkillAssemblyError("skill request lacks confirmed inputs")


@dataclass(frozen=True, slots=True)
class SkillAssemblyConfiguration:
    package_roots: tuple[Path | str, ...]
    workflows: tuple[LithoCpkWorkflow, ...]
    release_store: SkillReleaseStore | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.package_roots, tuple)
            or not isinstance(self.workflows, tuple)
            or (bool(self.package_roots) == (self.release_store is not None))
            or not self.workflows
            or any(not isinstance(item, LithoCpkWorkflow) for item in self.workflows)
        ):
            raise SkillAssemblyError("invalid skill configuration")
        if self.release_store is not None:
            # This stays local so historic source slices with file-backed
            # configuration do not need the publication module.
            from ..skills.releases import SkillReleaseStore

            if not isinstance(self.release_store, SkillReleaseStore):
                raise SkillAssemblyError("invalid skill configuration")
        identities = [(item.workflow_id, item.version) for item in self.workflows]
        if len(identities) != len(set(identities)):
            raise SkillAssemblyError("duplicate controlled workflow")


@dataclass(frozen=True, slots=True)
class SkillBinding:
    catalog: SkillCatalog
    loader: SkillLoader
    snapshot: SkillSnapshot
    workflow: LithoCpkWorkflow
    plan: ExecutionPlan
    selection: PlaybookSelection
    metadata: tuple[tuple[str, str], ...]
    release_store: SkillReleaseStore | None = None
    evidence_policy: ComponentReference | None = None

    def check_evidence(
        self, observations: list[EvidenceObservation]
    ) -> SkillEvidenceOutcome:
        if self.evidence_policy is None:
            return SkillEvidenceOutcome(EVIDENCE_NOT_CONFIGURED, None)
        try:
            validation = self.workflow.evidence_validator(
                self.plan, self.selection.selected_playbook, list(observations)
            )
        except Exception:  # noqa: BLE001 - reported as an unavailable check
            return SkillEvidenceOutcome(EVIDENCE_CHECK_FAILED, self.evidence_policy)
        return SkillEvidenceOutcome(EVIDENCE_CHECKED, self.evidence_policy, validation)

    def revalidate(self) -> None:
        try:
            if self.release_store is not None:
                current_release = self.release_store.require_enabled(
                    self.snapshot.reference
                )
                if (
                    current_release.reference != self.snapshot.reference
                    or current_release.manifest != self.snapshot.manifest
                ):
                    raise SkillAssemblyError("skill declaration is unavailable")
            current = self.catalog.current_entry(self.snapshot.reference)
        except SkillPackageError as error:
            raise SkillAssemblyError("skill declaration is unavailable") from error
        if not current.available or current.manifest != self.snapshot.manifest:
            raise SkillAssemblyError("skill declaration is unavailable")

    @property
    def model_context(self) -> tuple[ModelMessage, ...]:
        messages: list[ModelMessage] = []
        standard = self.snapshot.manifest.schema_version == SCHEMA_V2
        for item in self.snapshot.loaded_resources:
            if item.path == "SKILL.md":
                # Frontmatter is catalog metadata; activation loads the body.
                content = (
                    parse_skill_document(item.text).body if standard else item.text
                )
            else:
                # Resources are declared text context only.  This label keeps
                # their origin visible to the model without granting code or
                # tool authority.
                content = f"Skill resource ({item.path}, {item.kind}):\n{item.text}"
            messages.append(ModelMessage("system", content))
        return tuple(messages)


def _inventory(
    bindings: tuple[ToolBinding[object, object, object], ...],
    workflows: tuple[LithoCpkWorkflow, ...],
) -> DependencyInventory:
    tools = {
        binding.definition.name: binding.definition.version for binding in bindings
    }
    workflow_versions = {item.workflow_id: item.version for item in workflows}
    policies = {
        item.evidence_policy_id: item.evidence_policy_version for item in workflows
    }
    return DependencyInventory(tools, workflow_versions, policies)


def resolve_skill_binding(
    definition: AgentDefinition,
    configuration: SkillAssemblyConfiguration,
    request: SkillExecutionRequest,
    bindings: tuple[ToolBinding[object, object, object], ...],
    server_capabilities: frozenset[str],
) -> SkillBinding:
    """Resolve exactly one declared Skill against actual server bindings."""
    try:
        if len(definition.skill_refs) != 1:
            raise SkillAssemblyError("pilot supports exactly one skill")
        requested = definition.skill_refs[0]
        reference = SkillReference(requested.component_id, requested.version)
        inventory = _inventory(bindings, configuration.workflows)
        if configuration.release_store is None:
            catalog = SkillCatalog.build(configuration.package_roots, inventory)
            loader = SkillLoader(catalog)
        else:
            loader = configuration.release_store.loader(reference, inventory)
            catalog = loader.catalog
        entry = catalog.find(reference)
        if not entry.available:
            raise SkillAssemblyError(
                "skill is unavailable", reason=entry.unavailable_reason or "unavailable"
            )
        declared_workflow = entry.manifest.workflow
        declared_policy = entry.manifest.evidence_policy
        if declared_workflow is None:
            raise SkillAssemblyError(
                "skill declares no controlled workflow", reason="no_workflow"
            )
        workflow = next(
            (
                item
                for item in configuration.workflows
                if item.workflow_id == declared_workflow.component_id
                and item.version == declared_workflow.version
                and (
                    declared_policy is None
                    or (
                        item.evidence_policy_id == declared_policy.component_id
                        and item.evidence_policy_version == declared_policy.version
                    )
                )
            ),
            None,
        )
        if workflow is None:
            raise SkillAssemblyError(
                "controlled workflow is unavailable", reason="workflow_unavailable"
            )
        required_inputs = {"process_step", "time_range"}
        query = DiscoveryQuery(
            workflow.workflow_id,
            request.route.process_steps[0] if request.route.process_steps else None,
            request.mode,
            frozenset(required_inputs),
        )
        result = discover(catalog, query)
        if reference not in tuple(item.reference for item in result.candidates):
            raise SkillAssemblyError("skill does not match confirmed request")
        snapshot = loader.load(reference)
        if request.resource_paths:
            snapshot = loader.expand(snapshot, request.resource_paths)
        plan, selection = workflow.build(request.question, request.route)
        manifest_tools = {item.name for item in snapshot.manifest.tools}
        binding_versions = {
            item.definition.name: item.definition.version for item in bindings
        }
        plan_tools = {step.tool for step in plan.steps}
        if (
            not plan_tools <= manifest_tools
            or not manifest_tools <= definition.allowed_tools
            or not manifest_tools <= server_capabilities
            or any(
                binding_versions.get(item.name) is None
                for item in snapshot.manifest.tools
            )
        ):
            raise SkillAssemblyError(
                "skill tools are not authorized by the application"
            )
        resource_metadata = tuple(
            f"{item.path}|{item.kind}|{len(item.text.encode('utf-8'))}"
            for item in snapshot.loaded_resources
        )
        policy_metadata = (
            (
                ("evidence_policy_id", declared_policy.component_id),
                ("evidence_policy_version", declared_policy.version),
                ("evidence_policy_status", "configured"),
            )
            if declared_policy is not None
            else (("evidence_policy_status", EVIDENCE_NOT_CONFIGURED),)
        )
        metadata = (
            ("skill_id", reference.skill_id),
            ("skill_version", reference.version),
            ("workflow_id", workflow.workflow_id),
            ("workflow_version", workflow.version),
            *policy_metadata,
            ("loaded_paths", ",".join(item.path for item in snapshot.loaded_resources)),
            ("loaded_resources", ",".join(resource_metadata)),
        )
        return SkillBinding(
            catalog,
            loader,
            snapshot,
            workflow,
            plan,
            selection,
            metadata,
            configuration.release_store,
            declared_policy,
        )
    except SkillAssemblyError:
        raise
    except SkillPackageError as error:
        raise SkillAssemblyError(
            "skill assembly is invalid", reason=error.code
        ) from error
    except (LithoCpkWorkflowError, IndexError, StopIteration) as error:
        raise SkillAssemblyError("skill assembly is invalid") from error
