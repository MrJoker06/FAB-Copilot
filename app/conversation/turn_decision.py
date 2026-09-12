"""Small, validated turn-level orchestration decisions.

This intentionally sits above the manufacturing planner: it can hand a task
to the existing route, but never contains a tool name, SQL, or free arguments.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ActionType = Literal["answer_meta", "acknowledge", "route_task", "recall_history", "clarify"]
MetaSubject = Literal["identity", "capabilities", "usage_help", "limitations_policy", "runtime_status", "response_review", "social", "other"]
Detail = Literal["brief", "standard", "detailed"]

_TYPES = {"answer_meta", "acknowledge", "route_task", "recall_history", "clarify"}
_SUBJECTS = {"identity", "capabilities", "usage_help", "limitations_policy", "runtime_status", "response_review", "social", "other"}
_DETAILS = {"brief", "standard", "detailed"}
_PRIMARY = {"answer_meta", "route_task", "recall_history", "clarify"}


class TurnDecisionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TurnAction:
    type: ActionType
    subject: MetaSubject | None = None
    detail: Detail = "standard"
    target_intent: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TurnDecision:
    schema_version: Literal["1.0"]
    route: str
    relation: str
    actions: tuple[TurnAction, ...]
    confidence: float
    source: Literal["deterministic", "model", "derived", "fallback"]
    failure_reason: str = ""
    # Additive arbitration metadata. Values are constrained by DecisionArbiter;
    # no source text, tools, SQL, URLs, or model reasoning is persisted here.
    active_flow: str | None = None
    selected_origin: str = "deterministic"
    policy_reason: str = ""
    candidates: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "actions": [item.to_dict() for item in self.actions],
            "candidates": [dict(item) for item in self.candidates],
        }


def validate_turn_actions(value: object, *, allowed_route_intents: set[str] | None = None) -> tuple[TurnAction, ...]:
    if not isinstance(value, list) or not value or len(value) > 3:
        raise TurnDecisionValidationError("turn_actions must contain one to three actions")
    actions: list[TurnAction] = []
    primary = 0
    for raw in value:
        if not isinstance(raw, dict) or set(raw) - {"type", "subject", "detail", "target_intent"}:
            raise TurnDecisionValidationError("turn_action contains unsupported fields")
        kind, subject = raw.get("type"), raw.get("subject")
        detail = raw.get("detail", "standard")
        target = raw.get("target_intent")
        if kind not in _TYPES or detail not in _DETAILS:
            raise TurnDecisionValidationError("turn_action enum invalid")
        if kind == "answer_meta":
            if subject not in _SUBJECTS or target is not None:
                raise TurnDecisionValidationError("answer_meta requires a known subject only")
        elif kind == "route_task":
            if subject is not None or not isinstance(target, str) or not target or (allowed_route_intents is not None and target not in allowed_route_intents):
                raise TurnDecisionValidationError("route_task must target an existing route")
        elif subject is not None or target is not None:
            raise TurnDecisionValidationError("action does not accept subject or target")
        primary += kind in _PRIMARY
        actions.append(TurnAction(kind, subject, detail, target))
    if primary > 1:
        raise TurnDecisionValidationError("at most one primary action is allowed")
    if len({(item.type, item.subject, item.detail, item.target_intent) for item in actions}) != len(actions):
        raise TurnDecisionValidationError("duplicate turn_action")
    return tuple(actions)


def canonical_meta_subject(question: str) -> tuple[MetaSubject, Detail] | None:
    normalized = question.strip().rstrip("。！!？?").lower()
    if normalized in {"你好", "您好", "嗨", "hi", "hello"}:
        return "social", "brief"
    if normalized in {"你是谁", "介绍一下你自己", "自我介绍", "自我介绍一下"}:
        return "identity", "brief"
    if normalized in {"你能做什么", "你可以做什么", "你有哪些能力", "你有什么功能"}:
        return "capabilities", "standard"
    if normalized.startswith(("你能", "你可以", "你会")) and any(word in normalized for word in ("修改", "变更", "写入", "删除", "下发", "执行")):
        return "limitations_policy", "standard"
    if normalized.startswith(("你能", "你可以", "你会")):
        return "capabilities", "standard"
    if "为什么刚才" in normalized and ("答错" in normalized or "异常" in normalized):
        return "response_review", "standard"
    if "thinking" in normalized or "思考" in normalized:
        return "runtime_status", "standard"
    return None


def build_turn_decision(*, route: str, relation: str, confidence: float, question: str, model_actions: object = None, context_failure_reason: str = "", valid_route_intents: set[str] | None = None) -> TurnDecision:
    canonical = canonical_meta_subject(question) if route == "conversation" else None
    if canonical:
        return TurnDecision("1.0", route, relation, (TurnAction("answer_meta", *canonical),), 1.0, "deterministic")
    if model_actions is not None:
        try:
            actions = validate_turn_actions(model_actions, allowed_route_intents=valid_route_intents)
            # A semantic action is advisory; it cannot turn an explicit manufacturing route into conversation.
            if route == "conversation":
                actions = tuple(item for item in actions if item.type != "route_task")
                if actions and any(item.type == "answer_meta" for item in actions):
                    return TurnDecision("1.0", route, relation, actions, confidence, "model")
                context_failure_reason = "invalid_turn_actions:conversation_route_task"
            elif any(item.type == "route_task" and item.target_intent == route for item in actions):
                return TurnDecision("1.0", route, relation, actions, confidence, "model")
            elif actions and all(item.type == "acknowledge" for item in actions):
                return TurnDecision("1.0", route, relation, actions + (TurnAction("route_task", target_intent=route),), confidence, "derived")
        except TurnDecisionValidationError as exc:
            context_failure_reason = f"invalid_turn_actions:{exc}"
    if route not in {"conversation", "unknown", "ambiguous"}:
        return TurnDecision("1.0", route, relation, (TurnAction("route_task", target_intent=route),), confidence, "derived", context_failure_reason)
    if route == "conversation" and relation == "recall":
        return TurnDecision("1.0", route, relation, (TurnAction("recall_history"),), confidence, "derived", context_failure_reason)
    return TurnDecision("1.0", route, relation, (TurnAction("clarify"),), confidence, "fallback", context_failure_reason or "no_reliable_meta_action")
