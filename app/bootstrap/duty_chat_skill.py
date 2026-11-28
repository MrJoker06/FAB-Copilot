"""Bind one optional, catalog-authorized Skill to a duty chat turn."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.intent_runtime.contracts import IntentRoute
from app.intent_runtime.routing import route_question
from app.planning_runtime.contracts import PlanBudget
from app.skills.contracts import SkillPackageError
from app.skills.standard import StandardSkill
from app.skills.versions import parse_version_requirement

from . import capability_catalog as catalog
from .litho_cpk_workflow import LithoCpkWorkflow, LithoCpkWorkflowError
from .skill_assembly import (
    SkillAssemblyConfiguration,
    SkillAssemblyError,
    SkillBinding,
    SkillExecutionRequest,
    resolve_skill_binding,
)

_SKILL = "litho-cpk-diagnostic"
_WORKFLOW = LithoCpkWorkflow()
_TITLE = "光刻 Cpk 排查"
_SHIFT = re.compile(r"昨晚|昨班|当班|本班|上班次|夜班|白班|早班|晚班|班次")
_DATE_REPLY = re.compile(
    r"(?:(?:就查|改查|查|看|用|范围是)\s*)?"
    r"(?:今天|昨天|前天|(?:最|过|之)?近[ \d]+天|过去[ \d]+天|"
    r"\d{4}-\d{2}-\d{2}(?:\s*(?:到|至|~|～)\s*\d{4}-\d{2}-\d{2})?)"
    r"[。！!]?\Z"
)
_SCOPE_REPLY = re.compile(
    r"(?:就查|改查|查|看)?\s*(?:整个|全)?(?:光刻|LITHO)(?:制程|站点)?[。！!]?\Z", re.I
)
_active: ContextVar[ChatSkillRequest | None] = ContextVar(
    "duty_chat_skill", default=None
)


class DutySkillError(ValueError):
    def __init__(self, code, message, status=403):
        super().__init__(message)
        self.code = code
        self.status = status


def _installed(principal, name, *, required):
    rules = catalog.policies()
    if (
        name != _SKILL
        or "analyst" not in getattr(principal, "roles", ())
        or principal.tenant_id != catalog.get_settings().enterprise_default_tenant_id
        or not catalog.skill_allowed(name, principal, rules)
    ):
        if required:
            raise DutySkillError("CAPABILITY_DENIED", "当前身份无法使用所选技能。")
        return None
    try:
        root = catalog.skills_root() / name
        skill = None if root.is_symlink() else catalog.inspect_skill(root)
    except (OSError, SkillPackageError):
        skill = None
    manifest = skill.manifest if skill else None
    if not (
        manifest
        and manifest.skill_id == name
        and manifest.status == "published"
        and manifest.workflow is not None
        and manifest.workflow.component_id == _WORKFLOW.workflow_id
        and manifest.workflow.version == _WORKFLOW.version
        and manifest.evidence_policy == _WORKFLOW.required_evidence_policy
        and "ready" in manifest.execution_modes
    ):
        if required:
            raise DutySkillError(
                "SKILL_UNAVAILABLE", "所选技能的已发布工作流不可用。", 409
            )
        return None
    definitions = {
        definition.name: definition for definition in catalog.BUSINESS_TOOL_DEFINITIONS
    }
    definitions.update(
        (name, provider.definition) for name, provider in catalog.plugin_tools().items()
    )
    if not all(
        item.name in definitions
        and parse_version_requirement(item.version).matches(
            definitions[item.name].version
        )
        and catalog.tool_allowed(item.name, principal, rules)
        for item in manifest.tools
    ):
        if required:
            raise DutySkillError(
                "SKILL_DEPENDENCY_UNAVAILABLE",
                "所选技能的依赖工具不可用或未获授权。",
                409,
            )
        return None
    return skill


def require_skill(principal, name):
    """Validate an explicit selection or a cached Skill response."""
    return _installed(principal, name, required=True)


def allowed_history(history, principal):
    """Keep revoked Skill answers out of the model history."""
    allowed = []
    checked = {}
    for message in history or ():
        metadata = message.get("metadata")
        skill = metadata.get("skill_execution") if isinstance(metadata, dict) else None
        if message.get("role") == "assistant" and isinstance(skill, dict):
            name = skill.get("id")
            if not isinstance(name, str):
                continue
            if name not in checked:
                checked[name] = _installed(principal, name, required=False) is not None
            if not checked[name]:
                continue
        allowed.append(message)
    return allowed


@dataclass(slots=True)
class DutyChatSkill:
    principal: object
    package: StandardSkill
    origin: str
    question: str
    route: IntentRoute
    binding: SkillBinding | None = None
    missing: tuple[str, ...] = ()

    @property
    def tools(self):
        return frozenset(item.name for item in self.package.manifest.tools)

    def authorized(self):
        rules = catalog.policies()
        return catalog.skill_allowed(_SKILL, self.principal, rules) and all(
            catalog.tool_allowed(name, self.principal, rules) for name in self.tools
        )

    def require_current(self):
        if not self.authorized():
            raise DutySkillError(
                "CAPABILITY_DENIED", "技能或依赖已停用，或当前身份的权限已撤销。"
            )

    def planning(self, route, default_plan):
        self.require_current()
        questions = {}
        if (
            route.scope_resolution.scope_type != "process"
            or route.scope_resolution.resolved_ids != ("LITHO",)
        ):
            questions["process_step"] = (
                "此技能按光刻制程汇总。请确认是否分析整个光刻站点。"
            )
        if _SHIFT.search(self.question):
            questions["time_range"] = (
                "此技能按日期查询。请提供需要核对的日期或起止日期。"
            )
        elif route.time_range.assumed:
            questions["time_range"] = "请提供要分析的日期或起止日期。"
        if questions:
            self.missing = tuple(questions)
            return replace(
                default_plan,
                status="clarification_required",
                steps=(),
                budget=PlanBudget(0, 0, 0, 0, {}, 0, 0),
                required_evidence_ids=(),
                missing_inputs=self.missing,
                clarification_questions=tuple(questions.values()),
                reason="Skill 运行范围尚未确认。",
            )
        try:
            plan, _ = _WORKFLOW.build(self.question, route)
        except LithoCpkWorkflowError as error:
            raise DutySkillError(
                "SKILL_UNAVAILABLE", "当前请求无法生成技能执行计划。", 409
            ) from error
        self.route = route
        return plan

    def bind(self, planned, registry):
        self.require_current()
        bindings = tuple(registry.resolve(name) for name in sorted(self.tools))
        manifest = self.package.manifest
        host = ComponentReference("duty-chat", "1.0.0")
        definition = AgentDefinition(
            "duty-chat",
            "1.0.0",
            "analyst",
            _TITLE,
            tuple(
                ComponentReference(binding.definition.name, binding.definition.version)
                for binding in bindings
            ),
            host,
            host,
            (ComponentReference(_SKILL, manifest.version),),
        )
        try:
            self.binding = resolve_skill_binding(
                definition,
                SkillAssemblyConfiguration((self.package.root,), (_WORKFLOW,)),
                SkillExecutionRequest(self.question, self.route, "ready"),
                bindings,
                self.tools,
            )
            if (
                self.binding.plan != planned
                or self.binding.snapshot.manifest != manifest
            ):
                raise SkillAssemblyError("skill changed during preparation")
        except SkillAssemblyError as error:
            raise DutySkillError(
                "SKILL_UNAVAILABLE", "所选技能无法装配，请检查发布版本和工具依赖。", 409
            ) from error

    def metadata(self):
        self.require_current()
        return {
            "id": _SKILL,
            "title": _TITLE,
            "version": self.package.manifest.version,
            "workflow_version": _WORKFLOW.version,
            "selection": self.origin,
            "status": "clarification" if self.missing else "executed",
            **(
                {
                    "missing_inputs": list(self.missing),
                    "confirmed_time_range": None
                    if "time_range" in self.missing
                    else self.route.time_range.__dict__,
                }
                if self.missing
                else {}
            ),
        }


@dataclass(slots=True)
class ChatSkillRequest:
    principal: object
    selected: DutyChatSkill | None

    def resolve_automatic(self, routing):
        if self.selected is not None:
            return
        route = routing.intent_route
        if (
            route.intent == "capability_excursion"
            and route.request_type == "diagnosis"
            and route.process_steps == ("LITHO",)
            and route.scope_resolution.scope_type == "process"
        ):
            package = _installed(self.principal, _SKILL, required=False)
            if package is not None:
                self.selected = DutyChatSkill(
                    self.principal,
                    package,
                    "automatic",
                    routing.analysis_question,
                    route,
                )

    @contextmanager
    def activate(self):
        token = _active.set(self)
        try:
            yield
        finally:
            _active.reset(token)


def is_chat_skill(name):
    return name == _SKILL


def current_chat_skill_request():
    return _active.get()


def current_chat_skill():
    request = current_chat_skill_request()
    return request.selected if request is not None else None


def choose_chat_skill(question, selected, principal, history):
    """Honor explicit or narrowly recognized clarification replies."""
    origin = "manual"
    pending = (
        history[-1].get("metadata", {})
        if history and history[-1].get("role") == "assistant"
        else {}
    )
    prior = pending.get("skill_execution") if isinstance(pending, dict) else None
    if not selected:
        if not (
            isinstance(prior, dict)
            and prior.get("id") == _SKILL
            and prior.get("status") == "clarification"
        ):
            return None
        missing = prior.get("missing_inputs") or ()
        is_date = "time_range" in missing and _DATE_REPLY.fullmatch(question.strip())
        is_scope = "process_step" in missing and _SCOPE_REPLY.fullmatch(
            question.strip()
        )
        if not is_date and not is_scope:
            return None
        selected, origin = _SKILL, "followup"
        dates = prior.get("confirmed_time_range")
        if is_scope and isinstance(dates, dict):
            question += f" {dates['start']} 至 {dates['end']}"
        if is_date and "process_step" in missing:
            # Preserve the unresolved scope rather than widening a machine request.
            route = route_question("光刻 Cpk 异常排查。 " + question)
            route = replace(
                route,
                scope_resolution=replace(
                    route.scope_resolution, scope_type="unknown", resolved_ids=()
                ),
            )
            return DutyChatSkill(
                principal, require_skill(principal, selected), origin, question, route
            )
    package = require_skill(principal, selected)
    route = route_question(question)
    if route.intent != "capability_excursion":
        question = "光刻 Cpk 异常排查。 " + question
        route = route_question(question)
    return DutyChatSkill(principal, package, origin, question, route)
