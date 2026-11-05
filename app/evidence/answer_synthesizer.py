from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from .semantics import (
    EvidenceDescriptor,
    EvidenceScope,
    compatible_for_composite_inference,
    supports_claim,
)
from .serialization import json_dataclass_payload
from .validator import EvidenceValidation


SynthesisStatus = Literal["structured", "repaired", "not_applicable"]
PresentationMode = Literal["brief", "table", "report", "compact"]

PRESENTATION_MODES = ("brief", "compact", "report", "table")

# Server-side caps per mode.  The model chooses the mode; the server still bounds
# how much a mode may render, so a wrong "report" choice cannot produce a novel.
_MODE_BUDGETS: dict[str, dict[str, int]] = {
    "compact": {
        "facts": 8, "inferences": 5, "hypotheses": 5, "recommendations": 4,
        "limitations": 6, "item_chars": 240,
    },
    "report": {
        "facts": 8, "inferences": 8, "hypotheses": 8, "recommendations": 8,
        "limitations": 8, "item_chars": 240,
    },
    "table": {
        "facts": 8, "inferences": 8, "hypotheses": 8, "recommendations": 8,
        "limitations": 8, "item_chars": 200,
    },
}


def presentation_mode() -> str:
    """Deployment switch: ``model`` lets submit_analysis choose, ``rule`` keeps heuristics."""
    return (os.getenv("FAB_PRESENTATION_MODE", "model").strip().lower() or "model")


def resolve_presentation(payload: dict[str, Any], contract: "AnswerContract") -> tuple[str, str]:
    """Return ``(mode, source)`` where source is ``model``, ``rule`` or ``fallback``."""
    if presentation_mode() != "model":
        return contract.presentation, "rule"
    value = payload.get("presentation") if isinstance(payload, dict) else None
    if isinstance(value, str) and value.strip().lower() in PRESENTATION_MODES:
        return value.strip().lower(), "model"
    return contract.presentation, "fallback"

REQUIRED_SECTIONS = (
    "结论",
    "已确认事实",
    "分析推断",
    "待验证假设",
    "建议",
    "证据限制",
)
MODEL_KNOWLEDGE_SECTIONS = ("结论", "模型通用知识", "待验证内容", "建议", "使用限制")

MODEL_KNOWLEDGE_REF = "MODEL_GENERAL_KNOWLEDGE"
ANALYSIS_PROTOCOL_VERSION = "2.0"
MODEL_KNOWLEDGE_DISCLOSURE = (
    "知识库未检索到相关内容。以下回答使用模型通用知识，仅供参考，"
    "不代表厂内 SOP、规格或当前生产事实。"
)

SUBMIT_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_analysis",
        "description": "提交最终结构化分析。它不是数据工具，不得包含隐藏思维链；只提交面向用户的事实、推断、假设、建议、限制和引用。",
        "parameters": {
            "type": "object",
            "properties": {
                "analysis_protocol_version": {
                    "type": "string",
                    "enum": [ANALYSIS_PROTOCOL_VERSION],
                    "description": "可选。2.0 采用调用级直接事实和基于事实索引的综合推断；省略时按旧协议兼容处理。",
                },
                "presentation": {
                    "type": "string",
                    "enum": ["brief", "compact", "report", "table"],
                    "description": (
                        "可选。输出格式：brief=只给结论；compact=默认分条；"
                        "table=横向对比表；report=完整分节报告。按用户意图与证据量选择。"
                    ),
                },
                "conclusion": {"type": "string", "maxLength": 600},
                "conclusion_evidence_refs": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "conclusion_claim": {"type": "object", "properties": {"claim_kind": {"type": "string", "enum": ["metric", "record", "event", "document", "sample"]}, "semantic_id": {"type": "string"}, "scope": {"type": "object"}, "grain": {"type": "string"}, "time_range": {"type": "object"}, "claim_role": {"type": "string", "enum": ["primary", "background"]}, "inference_indices": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "integer", "minimum": 0}}}, "additionalProperties": False},
                "facts": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            "claim_kind": {"type": "string", "enum": ["metric", "record", "event", "document", "sample"]},
                            "semantic_id": {"type": "string"},
                            "scope": {"type": "object"},
                            "time_range": {"type": "object"},
                            "grain": {"type": "string"},
                            "claim_role": {"type": "string", "enum": ["primary", "background"]},
                        },
                        "required": ["statement", "evidence_refs"],
                        "additionalProperties": False,
                    },
                },
                "inferences": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            "fact_indices": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "integer", "minimum": 0}},
                            "basis": {"type": "string", "maxLength": 500, "description": "面向用户的简短依据，不得包含隐藏思维链。"},
                            "uncertainty": {"type": "string", "maxLength": 500},
                            "claim_kind": {"type": "string", "enum": ["metric", "record", "event", "document", "sample"]},
                            "semantic_id": {"type": "string"},
                            "scope": {"type": "object"},
                            "time_range": {"type": "object"},
                            "grain": {"type": "string"},
                            "claim_role": {"type": "string", "enum": ["primary", "background"]},
                        },
                        "required": ["statement"],
                        "additionalProperties": False,
                    },
                },
                "hypotheses": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            "verification": {"type": "string"},
                            "claim_kind": {"type": "string", "enum": ["metric", "record", "event", "document", "sample"]},
                            "semantic_id": {"type": "string"},
                            "scope": {"type": "object"},
                            "time_range": {"type": "object"},
                            "grain": {"type": "string"},
                            "claim_role": {"type": "string", "enum": ["primary", "background"]},
                        },
                        "required": ["statement", "evidence_refs", "verification"],
                        "additionalProperties": False,
                    },
                },
                "recommendations": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "rationale": {"type": "string"},
                            "requires_review": {"type": "boolean"},
                        },
                        "required": ["action", "rationale", "requires_review"],
                        "additionalProperties": False,
                    },
                },
                "limitations": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
                "source_refs": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
            },
            "required": [
                "conclusion",
                "conclusion_evidence_refs",
                "conclusion_claim",
                "facts",
                "inferences",
                "hypotheses",
                "recommendations",
                "limitations",
                "source_refs",
            ],
            "additionalProperties": False,
        },
    },
}

_SOURCE_PATTERN = re.compile(r"\[来源\s+([^\]]+)\]", re.IGNORECASE)
# These expressions identify candidates only.  `_speech_act` below decides whether a
# clause actually asserts the candidate, rather than merely asking, qualifying, or
# explaining it.
_CAUSAL_PATTERN = re.compile(r"导致|引起|造成|源于|归因于|问题出在|(?:根本)?根因")
_DEFINITIVE_PATTERN = re.compile(r"主要原因(?:为|是)|可以确定|已经证实|确定无疑|(?:根本)?根因(?:为|是|在)")
_CLAUSE_BOUNDARY_PATTERN = re.compile(r"[。！？!?；;,，]+|(?:但是|然而|不过|但)")
_QUESTION_PATTERN = re.compile(r"(?:是否|是不是|能否|会不会|为何|为什么|如何)|[？?]$")
_QUALIFIER_PATTERN = re.compile(
    r"(?:不能|无法|未能|尚未|没有|缺乏|不足以).{0,10}(?:证明|证实|确认|表明)"
    r"|(?:可能|或许|疑似|假设|待验证|尚待|不排除|倾向于|需要验证)"
)
_CAUSAL_ASSERTION_PATTERN = re.compile(
    r".+(?:导致|引起|造成).+|(?:由|因).+(?:导致|引起|造成)|(?:源于|归因于).+"
    r"|问题出在.+|(?:根本)?根因(?:为|是|在).+|.+是(?:.+?的)?(?:根本)?根因"
)
_GENERIC_MECHANISM_PATTERN = re.compile(
    r"(?:通常|一般(?:而言|情况下)?|机理|原理|材料特性|物理|化学|在.+?条件下).{0,80}"
    r"(?:导致|引起|造成|加速|影响)"
)
_PRODUCTION_SCOPE_PATTERN = re.compile(
    r"当前|本次|该(?:厂|线|机台|设备)|(?:CMP|EQ)-\d+|(?:批次|批号|LOT)\s*[A-Z0-9-]+",
    re.IGNORECASE,
)
_DIAGNOSTIC_TARGET_PATTERN = re.compile(r"原因|根因|问题|失效|故障")
_HIGH_RISK_PATTERN = re.compile(r"停机|报废|放行|返工|配方(?:修改|变更)|恢复量产")


@dataclass(frozen=True)
class AnswerContract:
    schema_version: str
    synthesizer_version: str
    plan_id: str
    status: Literal["required", "not_applicable"]
    allowed_conclusion_strength: str
    causal_claims_allowed: bool
    required_sections: tuple[str, ...]
    permitted_source_refs: tuple[str, ...]
    mandatory_limitations: tuple[str, ...]
    model_knowledge_fallback: bool
    primary_scope_type: str
    primary_scope_ids: tuple[str, ...]
    primary_scope_labels: tuple[str, ...]
    source_scope_roles: dict[str, str]
    source_semantics: dict[str, dict[str, Any]]
    presentation: PresentationMode = "compact"
    submission_tool: str = "submit_analysis"
    reference_evidence: dict[str, dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_dataclass_payload(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class AnswerSynthesisReport:
    schema_version: str
    synthesizer_version: str
    plan_id: str
    status: SynthesisStatus
    allowed_conclusion_strength: str
    sections: tuple[str, ...]
    source_refs: tuple[str, ...]
    invalid_source_refs: tuple[str, ...]
    moved_claims: int
    wording_adjustments: tuple[str, ...]
    claim_support: tuple[dict[str, Any], ...] = ()
    # Additive default keeps persisted 1.0/1.1 report dictionaries readable.
    analysis_protocol_version: str = "1.1"
    # Public, auditable repair metadata.  This deliberately describes only
    # parser/service actions, never model reasoning.
    repair_events: tuple[dict[str, Any], ...] = ()
    # Which layout was actually rendered and who chose it (model/rule/fallback).
    presentation: str = "compact"
    presentation_source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return json_dataclass_payload(self)


@dataclass(frozen=True)
class SynthesizedAnswer:
    answer: str
    report: AnswerSynthesisReport


@dataclass(frozen=True)
class _Claim:
    statement: str
    evidence_refs: tuple[str, ...]
    verification: str = ""
    claim_kind: str = ""
    semantic_id: str = ""
    scope: dict[str, Any] | None = None
    time_range: dict[str, Any] | None = None
    grain: str = ""
    claim_role: str = "primary"
    invalid_refs: tuple[str, ...] = ()
    fact_indices: tuple[int, ...] = ()
    basis: str = ""
    uncertainty: str = ""
    explicit_fields: frozenset[str] = frozenset()
    invalid_fact_indices: bool = False


@dataclass(frozen=True)
class _Recommendation:
    action: str
    rationale: str
    requires_review: bool


def _clean_text(value: Any, limit: int = 3000, *, preserve_layout: bool = False) -> str:
    text = str(value or "").strip()
    if preserve_layout:
        # User-facing legacy content can contain paragraphs, Markdown lists,
        # tables and inline citations.  Normalize only horizontal whitespace
        # within each physical line; collapsing all whitespace used to turn a
        # complete answer into one un-auditable pseudo claim.
        lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", text)
        text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _legacy_blocks(answer: str) -> list[str]:
    """Split display-oriented legacy content without destroying its layout."""
    cleaned = _clean_text(answer, preserve_layout=True)
    if not cleaned:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    # Avoid an oversized opaque assertion while still retaining tables and
    # multi-line lists as coherent display blocks.
    return [block[:3000] for block in blocks]


def _validation_limitations(validation: EvidenceValidation) -> tuple[str, ...]:
    limitations: list[str] = []
    for check in validation.evidence_checks:
        if check.status in {"missing", "partial"}:
            missing = f"，缺少字段：{', '.join(check.missing_fields)}" if check.missing_fields else ""
            limitations.append(f"{check.evidence_id} {check.name} 为{check.status}{missing}。")
    limitations.extend(item.message for item in validation.risks)
    limitations.extend(item.message for item in validation.conflicts)
    if validation.allowed_conclusion_strength in {"insufficient", "hypothesis_only"}:
        limitations.append(validation.conclusion_guidance)
    return tuple(dict.fromkeys(limitations))


def create_answer_contract(
    validation: EvidenceValidation,
    sources: list[dict[str, Any]] | None = None,
    *,
    allow_model_knowledge_fallback: bool = False,
    question: str = "",
    resolved_question: str = "",
    extra_limitations: Sequence[str] = (),
) -> AnswerContract:
    matched_tools = {
        tool
        for check in validation.evidence_checks
        if check.status in {"covered", "partial"} and check.row_count > 0
        for tool in check.matched_tools
    }
    source_refs = {
        str(source.get("reference_id"))
        for source in sources or []
        if source.get("reference_id")
    }
    permitted_items = {*(f"TOOL:{tool}" for tool in matched_tools), *source_refs}
    permitted_items.update(validation.observed_source_refs)
    if allow_model_knowledge_fallback:
        permitted_items.add(MODEL_KNOWLEDGE_REF)
    permitted = tuple(sorted(permitted_items))
    if allow_model_knowledge_fallback:
        limitations = [
            "知识库检索未获得可用内容，未找到可引用的厂内知识或历史案例。",
            MODEL_KNOWLEDGE_DISCLOSURE,
            "模型通用知识不能替代厂内 SOP、配方、规格或生产数据。",
        ]
    else:
        limitations = list(_validation_limitations(validation))
    limitations.extend(item for item in extra_limitations if item)
    required = validation.status == "validated"
    return AnswerContract(
        schema_version="1.2",
        synthesizer_version="1.2.0",
        plan_id=validation.plan_id,
        status="required" if required else "not_applicable",
        allowed_conclusion_strength=validation.allowed_conclusion_strength,
        causal_claims_allowed=validation.causal_claims_allowed,
        required_sections=(
            MODEL_KNOWLEDGE_SECTIONS
            if required and allow_model_knowledge_fallback
            else REQUIRED_SECTIONS
            if required
            else ()
        ),
        permitted_source_refs=permitted,
        mandatory_limitations=tuple(dict.fromkeys(limitations)),
        model_knowledge_fallback=allow_model_knowledge_fallback,
        primary_scope_type=validation.primary_scope_type,
        primary_scope_ids=validation.primary_scope_ids,
        primary_scope_labels=validation.primary_scope_labels,
        source_scope_roles=validation.source_scope_roles,
        source_semantics=validation.source_semantics,
        presentation=_select_presentation(question, resolved_question),
        reference_evidence=validation.reference_evidence,
    )


def _explicit_presentation(question: str) -> PresentationMode | None:
    normalized = _clean_text(question, 400).lower()
    if any(token in normalized for token in ("表格", "列表比较", "对比表")):
        return "table"
    if any(token in normalized for token in ("完整报告", "详细报告", "诊断报告", "完整分析报告")):
        return "report"
    if any(token in normalized for token in ("一句话", "简短", "简要", "简洁", "直接回答")):
        return "brief"
    return None


def _select_presentation(question: str, resolved_question: str = "") -> PresentationMode:
    """Use this turn's explicit format first, then the resolved task's format.

    Brief is reserved for an explicit short-answer request.  A question that only
    mentions a metric (for example "光刻机台的良率情况") still needs its evidence,
    hypotheses and limitations, so it keeps the structured compact layout.
    """
    explicit = _explicit_presentation(question) or _explicit_presentation(resolved_question)
    if explicit:
        return explicit
    return "compact"


def synthesizer_system_message(contract: AnswerContract) -> str:
    if contract.status == "not_applicable":
        return (
            "当前 answer_contract.status=not_applicable，可按通用规则直接回答；"
            "不得伪造来源或展示隐藏思维链。\n"
            f"answer_contract={contract.to_prompt()}"
        )
    protocol_guidance = (
        "这是模型通用知识回退路径：省略 analysis_protocol_version，不要提交 TOOL:Sxx、fact_indices 或 inference_indices；"
        f"使用 {MODEL_KNOWLEDGE_REF} 并遵循既有模型通用知识提交约定。"
        if contract.model_knowledge_fallback
        else (
            f"使用 analysis_protocol_version={ANALYSIS_PROTOCOL_VERSION}：facts 是调用级直接事实，只写 statement 与 TOOL:Sxx 引用即可；"
            "claim_kind、semantic_id、scope、time_range、grain、claim_role 由服务端从被引用证据推导，"
            "如果你显式填写则必须与证据一致，否则该声明会被判为不支持。"
            "inferences 用已验证 facts 的从零开始 fact_indices（1 条为单源推断，最多给出受限结论；2 条及以上为复合推断），并填写简短 basis 和 uncertainty；其引用由服务端从事实推导，不要重复填报来源元数据。"
            "conclusion_claim 必须引用已验证综合推断的 inference_indices；其目标 scope、time_range、claim_role 由服务端从所引用的推断推导，不得把综合结论伪装成某一个原始指标。"
            "不得把背景来源混入综合推断，范围或时间不兼容时改为 hypotheses。"
        )
    )
    legacy_guidance = (
        "仅当省略 analysis_protocol_version、使用旧协议时，制造域的 facts、inferences 和 conclusion_claim 才必须从 answer_contract.source_semantics 逐项复制 claim_kind、semantic_id、scope、grain 和 time_range；不得根据用户目标范围猜测证据范围。"
        if not contract.model_knowledge_fallback
        else ""
    )
    return (
        "最终回答必须通过 submit_analysis 提交，不要直接输出最终正文。"
        f"服务端会按 presentation={contract.presentation} 呈现已验证声明；"
        "facts 只放工具结果直接支持的事实且必须填写 permitted_source_refs；"
        "inferences 是基于事实的解释，hypotheses 必须包含验证方法，recommendations 必须说明依据与复核要求。"
        "保持精炼：只保留对决策最重要的条目，不要逐行复述工具结果或穷举全部设备。"
        + (
            "presentation=brief 时必须极简：conclusion 不超过 60 字；facts 最多 2 条且每条不超过 80 字；"
            "不要提交 inferences、hypotheses、recommendations；limitations 最多 3 条。"
            if contract.presentation == "brief"
            else ""
        )
        + (
            f"知识库检索没有返回可用内容，允许使用 {MODEL_KNOWLEDGE_REF} 作为模型通用知识标识。"
            "应直接回答用户的一般性技术问题，将通用知识放入 inferences；"
            "conclusion 直接概括技术回答，不要重复知识库无结果声明，服务端会统一添加；"
            "不得把它写成厂内 SOP、配方、规格或当前生产事实，并必须明确披露知识库无结果。"
            if contract.model_knowledge_fallback
            else ""
        )
        + protocol_guidance
        + legacy_guidance
        + "不得提交隐藏思维链、逐 token 推理或未在 permitted_source_refs 中的来源。"
        "conclusion_evidence_refs 必须列出结论依据；仅由 context_only 来源支持的整厂背景不得表述为主范围自身指标。"
        "allowed_conclusion_strength 约束任务级诊断和根因；逐声明验证的直接观测可保留。"
        "causal_claims_allowed=false 时不得声称已证明因果。\n"
        # Fixed guidance sits before the per-request contract so the shared prompt
        # prefix (role, protocol, guidance) stays stable for slot-level caching.
        "输出格式：在 submit_analysis 的 presentation 字段选择 brief（只给结论）、"
        "compact（默认分条）、table（横向对比）、report（完整分节）；"
        "按用户意图与证据量选择，服务端会按所选模式裁剪条目。\n"
        f"answer_contract={contract.to_prompt()}"
    )


def _normalize_ref(value: Any, allowed: dict[str, str]) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    return allowed.get(candidate.upper())


def _embedded_refs(statement: str) -> list[str]:
    return [
        item
        for block in _SOURCE_PATTERN.findall(statement)
        for item in re.split(r"[,，、\s]+", block)
        if item
    ]


def _parse_claims(value: Any, allowed: dict[str, str]) -> tuple[list[_Claim], set[str]]:
    claims: list[_Claim] = []
    invalid: set[str] = set()
    if not isinstance(value, list):
        return claims, invalid
    for item in value:
        payload = item if isinstance(item, dict) else {"statement": item, "evidence_refs": []}
        statement = _clean_text(payload.get("statement"))
        if not statement:
            continue
        supplied_refs = list(payload.get("evidence_refs") or [])
        supplied_refs.extend(_embedded_refs(statement))
        statement = _SOURCE_PATTERN.sub("", statement).strip()
        refs: list[str] = []
        claim_invalid: list[str] = []
        for supplied in supplied_refs:
            normalized = _normalize_ref(supplied, allowed)
            if normalized:
                refs.append(normalized)
            elif str(supplied or "").strip():
                invalid_ref = str(supplied).strip()
                invalid.add(invalid_ref)
                claim_invalid.append(invalid_ref)
        claims.append(_Claim(
            statement=statement,
            evidence_refs=tuple(dict.fromkeys(refs)),
            verification=_clean_text(payload.get("verification"), 1200),
            claim_kind=_clean_text(payload.get("claim_kind"), 80),
            semantic_id=_clean_text(payload.get("semantic_id"), 120),
            scope=payload.get("scope") if isinstance(payload.get("scope"), dict) else None,
            time_range=payload.get("time_range") if isinstance(payload.get("time_range"), dict) else None,
            grain=_clean_text(payload.get("grain"), 80),
            claim_role=_clean_text(payload.get("claim_role"), 20) or "primary",
            invalid_refs=tuple(dict.fromkeys(claim_invalid)),
            fact_indices=tuple(payload.get("fact_indices", ())) if isinstance(payload.get("fact_indices"), list) else (),
            basis=_clean_text(payload.get("basis"), 500),
            uncertainty=_clean_text(payload.get("uncertainty"), 500),
            explicit_fields=frozenset(payload),
            invalid_fact_indices=(
                "fact_indices" in payload
                and (
                    not isinstance(payload.get("fact_indices"), list)
                    or any(not isinstance(item, int) or isinstance(item, bool) for item in payload.get("fact_indices", ()))
                )
            ),
        ))
    return claims, invalid


def _parse_recommendations(value: Any) -> list[_Recommendation]:
    recommendations: list[_Recommendation] = []
    if not isinstance(value, list):
        return recommendations
    for item in value:
        payload = item if isinstance(item, dict) else {"action": item}
        action = _clean_text(payload.get("action"))
        if not action:
            continue
        rationale = _clean_text(payload.get("rationale"), 1200)
        requires_review = bool(payload.get("requires_review")) or bool(_HIGH_RISK_PATTERN.search(action))
        recommendations.append(_Recommendation(action, rationale, requires_review))
    return recommendations


def _speech_act(statement: str) -> tuple[bool, bool, bool, bool]:
    """Return asserted causal, definitive, non-assertive, generic-mechanism flags.

    This is deliberately clause-level and rule-auditable: keywords nominate a
    clause for review, but a negation of proof, question, or hypothesis cannot
    turn that clause into an asserted causal conclusion.  Contrast boundaries
    keep a cautious sentence from masking a separate affirmative assertion.
    """
    asserted_causal = asserted_definitive = non_assertive_risk = False
    # A generic cue cannot launder a claim about a current or named production
    # scope.  Bare technical domain nouns remain valid in generic explanations.
    generic_mechanism = bool(_GENERIC_MECHANISM_PATTERN.search(statement)) and not bool(
        _PRODUCTION_SCOPE_PATTERN.search(statement)
    )
    for raw_clause in _CLAUSE_BOUNDARY_PATTERN.split(statement):
        clause = raw_clause.strip()
        if not clause:
            continue
        causal_candidate = bool(_CAUSAL_PATTERN.search(clause))
        definitive_candidate = bool(_DEFINITIVE_PATTERN.search(clause))
        if _QUESTION_PATTERN.search(clause) or _QUALIFIER_PATTERN.search(clause):
            non_assertive_risk = True
            continue
        if not (causal_candidate or definitive_candidate):
            continue
        # A generic mechanism is not an assertion about the current fab.  It is
        # only exempted from causal suppression for disclosed model knowledge;
        # direct-fact validation still rejects it as a misclassified observation.
        if generic_mechanism:
            continue
        if causal_candidate and _CAUSAL_ASSERTION_PATTERN.search(clause):
            asserted_causal = True
        # "数据已经证实良率下降" can be a direct observation.  Definitive
        # wording is restricted here only when it declares a diagnosis/root
        # cause, rather than the measured event itself.
        if definitive_candidate and (causal_candidate or _DIAGNOSTIC_TARGET_PATTERN.search(clause)):
            asserted_definitive = True
    return asserted_causal, asserted_definitive, non_assertive_risk, generic_mechanism


def _overclaim(
    statement: str, strength: str, causal_allowed: bool, *, model_knowledge: bool = False,
) -> bool:
    asserted_causal, asserted_definitive, _, generic_mechanism = _speech_act(statement)
    if not causal_allowed and (asserted_causal or (generic_mechanism and not model_knowledge)):
        return True
    return strength in {"insufficient", "hypothesis_only"} and asserted_definitive


def _fact_wording_mismatch(statement: str) -> bool:
    """Facts must be direct observations, not causal analysis or a speech act."""
    asserted_causal, asserted_definitive, non_assertive_risk, generic_mechanism = _speech_act(statement)
    return asserted_causal or asserted_definitive or non_assertive_risk or generic_mechanism


def _inference_wording_mismatch(statement: str, *, model_knowledge: bool) -> bool:
    """Questions and hypotheses belong in the verification bucket, not inferences."""
    _, _, non_assertive_risk, generic_mechanism = _speech_act(statement)
    return non_assertive_risk or (generic_mechanism and not model_knowledge)


def _scope_mismatch(statement: str, references: tuple[str, ...], contract: AnswerContract) -> bool:
    if contract.primary_scope_type not in {"process", "equipment", "product"}:
        return False
    normalized = statement.lower()
    if not any(label.lower() in normalized for label in contract.primary_scope_labels if label):
        return False
    if not references:
        return True
    return all(contract.source_scope_roles.get(reference, "unknown") != "primary" for reference in references)


def _descriptor_for_reference(reference: str, contract: AnswerContract) -> EvidenceDescriptor | None:
    metadata = contract.source_semantics.get(reference)
    if not metadata:
        return None
    try:
        return EvidenceDescriptor(
            source_ref=reference,
            kind=metadata.get("kind", "unknown"),
            semantic_id=metadata.get("semantic_id", "unknown"),
            scope=EvidenceScope(**metadata.get("scope", {})),
            grain=metadata.get("grain", "unknown"),
            start=metadata.get("start"), end=metadata.get("end"),
            filter_provenance=metadata.get("filter_provenance", "unknown"),
            scope_role=metadata.get("scope_role", "primary"),
        )
    except (TypeError, ValueError):
        return None


def _claim_scope(claim: _Claim) -> EvidenceScope | None:
    if not isinstance(claim.scope, dict):
        return None
    try:
        return EvidenceScope(**{
            key: tuple(str(value).upper() for value in values)
            for key, values in claim.scope.items()
            if key in EvidenceScope.__dataclass_fields__
            and isinstance(values, (list, tuple))
        })
    except (TypeError, ValueError):
        return None


def _structured_claim_mismatch(claim: _Claim, contract: AnswerContract) -> bool:
    """Validate structured manufacturing claims without inspecting claim prose."""
    manufacturing = contract.primary_scope_type in {"fab", "process", "equipment", "product", "lot"}
    if claim.claim_role not in {"primary", "background"}:
        return True
    if not (claim.claim_kind or claim.semantic_id or claim.scope or claim.time_range or claim.grain):
        return manufacturing
    if not claim.claim_kind or not claim.semantic_id or claim.scope is None or not claim.grain or claim.time_range is None or not claim.evidence_refs:
        return True
    claim_scope = _claim_scope(claim)
    if claim_scope is None:
        return True
    for reference in claim.evidence_refs:
        descriptor = _descriptor_for_reference(reference, contract)
        if not descriptor:
            continue
        if (descriptor.start or descriptor.end) and not (claim.time_range or {}).get("start"):
            continue
        if not (descriptor.start or descriptor.end) and claim.time_range:
            continue
        if supports_claim(
            descriptor, kind=claim.claim_kind, semantic_id=claim.semantic_id, scope=claim_scope, grain=claim.grain,
            start=str((claim.time_range or {}).get("start") or "") or None,
            end=str((claim.time_range or {}).get("end") or "") or None,
            claim_role=claim.claim_role,
        ):
            return False
    return True


def _agree(values: list[Any]) -> Any | None:
    """Return the single shared value, or None when the references disagree."""
    distinct = {value for value in values}
    return next(iter(distinct)) if len(distinct) == 1 else None


def _scope_payload(scope: EvidenceScope) -> dict[str, list[str]]:
    return {
        name: list(getattr(scope, name))
        for name in EvidenceScope.__dataclass_fields__
        if getattr(scope, name)
    }


def _shared_time_range(claims: list[_Claim]) -> dict[str, Any] | None:
    """Return the single time range shared by every claim, or None."""
    serialized = {
        json.dumps(claim.time_range or {}, sort_keys=True, ensure_ascii=False)
        for claim in claims
    }
    if len(serialized) != 1:
        return None
    return json.loads(next(iter(serialized)))


def _v2_conclusion_claim(
    claim: _Claim, payload: dict[str, Any], dependencies: list[_Claim],
) -> tuple[_Claim, tuple[str, ...]]:
    """Derive a v2 conclusion's target metadata from its verified inferences.

    Scope, time range and role default to the inferences the conclusion cites;
    an explicitly supplied value must agree with them.
    """
    scope = _claim_scope(claim) if claim.scope else None
    if scope is None:
        shared_scope = _agree([_claim_scope(item) for item in dependencies if item.scope])
        if shared_scope is None:
            return claim, ("v2 结论的依赖推断范围不一致。",)
        scope = shared_scope
    time_range = claim.time_range if claim.time_range else _shared_time_range(dependencies)
    if time_range is None:
        return claim, ("v2 结论的依赖推断时间范围不一致。",)
    if "claim_role" in payload:
        claim_role = claim.claim_role
    else:
        claim_role = (
            "background"
            if all(item.claim_role == "background" for item in dependencies)
            else "primary"
        )
    if claim_role not in {"primary", "background"}:
        return claim, ("v2 结论的角色无效。",)
    for item in dependencies:
        if (
            _claim_scope(item) != scope
            or (item.time_range or {}) != (time_range or {})
            or (claim_role == "primary" and item.claim_role != "primary")
        ):
            return claim, ("v2 结论声明的范围、时间或角色与综合推断不一致。",)
    return _Claim(
        **{
            **claim.__dict__,
            "scope": _scope_payload(scope),
            "time_range": time_range,
            "claim_role": claim_role,
        }
    ), ()


def _v2_direct_fact(claim: _Claim, contract: AnswerContract) -> tuple[_Claim, tuple[str, ...]]:
    """Derive the semantic metadata of a v2 direct observation from its sources.

    The model only writes the statement and the references: kind, grain,
    semantic id, scope, time range and role are copied from the referenced
    call-level sources when every reference agrees.  Values the model does
    supply are still validated, so an explicit contradiction stays unsupported.
    """
    if not claim.evidence_refs or any(not ref.startswith("TOOL:S") for ref in claim.evidence_refs):
        return claim, ("直接事实只能引用调用级 TOOL:Sxx 证据。",)
    descriptors = [_descriptor_for_reference(ref, contract) for ref in claim.evidence_refs]
    if any(item is None for item in descriptors):
        return claim, ("直接事实引用缺少可用来源描述。",)
    resolved = [item for item in descriptors if item is not None]
    kind = _agree([item.kind for item in resolved])
    grain = _agree([item.grain for item in resolved])
    if kind in (None, "unknown") or grain in (None, "unknown"):
        return claim, ("直接事实的调用级来源元数据不一致或未知。",)
    if claim.claim_kind and claim.claim_kind != kind:
        return claim, ("模型提供的 kind 与调用级来源描述矛盾。",)
    if claim.grain and claim.grain != grain:
        return claim, ("模型提供的 grain 与调用级来源描述矛盾。",)

    semantic_id = claim.semantic_id or _agree([item.semantic_id for item in resolved])
    if not semantic_id:
        return claim, ("直接事实的调用级来源语义不一致。",)

    scope = claim.scope if claim.scope else None
    if scope is None:
        shared_scope = _agree([item.scope for item in resolved])
        if shared_scope is None:
            return claim, ("直接事实的调用级来源范围不一致。",)
        scope = _scope_payload(shared_scope)

    shared_start = _agree([item.start for item in resolved])
    shared_end = _agree([item.end for item in resolved])
    time_range = claim.time_range if claim.time_range else None
    if time_range is None:
        if (shared_start is None) != (shared_end is None):
            return claim, ("直接事实的调用级来源时间范围不一致。",)
        time_range = {"start": shared_start, "end": shared_end} if shared_start and shared_end else {}
    elif shared_start is None and shared_end is None:
        # Some sources have no time dimension at all (knowledge documents).  A
        # time range supplied for those is unverifiable, not a contradiction.
        time_range = {}

    if "claim_role" in claim.explicit_fields:
        claim_role = claim.claim_role
    else:
        shared_role = _agree([item.scope_role for item in resolved])
        if shared_role is None:
            return claim, ("直接事实的调用级来源角色不一致。",)
        claim_role = "background" if shared_role == "context_only" else "primary"

    return _Claim(
        **{
            **claim.__dict__,
            "claim_kind": kind,
            "grain": grain,
            "semantic_id": semantic_id,
            "scope": scope,
            "time_range": time_range,
            "claim_role": claim_role,
        }
    ), ()


def _v2_direct_fact_status(claim: _Claim, contract: AnswerContract) -> tuple[str, tuple[str, ...]]:
    resolved, reasons = _v2_direct_fact(claim, contract)
    if reasons:
        return "unsupported", reasons
    scope = _claim_scope(resolved)
    if scope is None:
        return "unsupported", ("直接事实的 scope 无法解析。",)
    for reference in resolved.evidence_refs:
        descriptor = _descriptor_for_reference(reference, contract)
        if not descriptor or not supports_claim(
            descriptor, kind=resolved.claim_kind, semantic_id=resolved.semantic_id,
            scope=scope, grain=resolved.grain,
            start=str((resolved.time_range or {}).get("start") or "") or None,
            end=str((resolved.time_range or {}).get("end") or "") or None,
            claim_role=resolved.claim_role,
        ):
            return "unsupported", ("直接事实的调用级来源不支持其声明范围、时间或语义。",)
    return _final_claim_status(resolved, contract)


def _v2_composite_inference(
    claim: _Claim, facts: dict[int, _Claim], contract: AnswerContract,
) -> tuple[_Claim, tuple[str, ...]]:
    if claim.invalid_fact_indices:
        return claim, ("综合推断的 fact_indices 必须是整数数组。",)
    if not claim.fact_indices:
        return claim, ("综合推断必须关联至少一个已验证事实索引。",)
    if len(set(claim.fact_indices)) != len(claim.fact_indices):
        return claim, ("综合推断的 fact_indices 不能重复。",)
    if not claim.basis or not claim.uncertainty:
        return claim, ("综合推断必须提供面向用户的依据和不确定性说明。",)
    dependencies = [facts.get(index) for index in claim.fact_indices]
    if any(item is None for item in dependencies):
        return claim, ("综合推断引用了未验证或不存在的事实索引。",)
    resolved_dependencies = [item for item in dependencies if item is not None]
    refs = tuple(dict.fromkeys(ref for item in resolved_dependencies for ref in item.evidence_refs))
    if claim.evidence_refs and set(claim.evidence_refs) != set(refs):
        return claim, ("综合推断的引用必须等于其依赖事实的调用级引用并由服务端推导。",)
    descriptors = [_descriptor_for_reference(ref, contract) for ref in refs]
    if any(item is None for item in descriptors):
        return claim, ("综合推断的依赖事实存在不兼容的范围、时间或背景来源。",)
    if len(resolved_dependencies) >= 2 and not compatible_for_composite_inference(
        [item for item in descriptors if item is not None]
    ):
        return claim, ("综合推断的依赖事实存在不兼容的范围、时间或背景来源。",)

    # Target scope, time range and role default to the dependency facts; an
    # explicitly supplied value is still checked against them below.
    target_scope = _claim_scope(claim) if claim.scope else None
    if target_scope is None:
        shared_scope = _agree([_claim_scope(item) for item in resolved_dependencies if item.scope])
        if shared_scope is None:
            return claim, ("综合推断的依赖事实范围不一致。",)
        target_scope = shared_scope
    if claim.time_range:
        target_range = claim.time_range
    else:
        target_range = _shared_time_range(resolved_dependencies)
        if target_range is None:
            return claim, ("综合推断的依赖事实时间范围不一致。",)
    if "claim_role" in claim.explicit_fields:
        claim_role = claim.claim_role
    else:
        claim_role = (
            "background"
            if all(item.claim_role == "background" for item in resolved_dependencies)
            else "primary"
        )
    if claim_role not in {"primary", "background"}:
        return claim, ("综合推断的目标范围或角色无效。",)
    if len(resolved_dependencies) == 1:
        single = descriptors[0] if descriptors else None
        if single is None or single.filter_provenance == "unknown":
            return claim, ("综合推断的依赖事实来源不可用。",)

    target_start = str((target_range or {}).get("start") or "") or None
    target_end = str((target_range or {}).get("end") or "") or None
    for descriptor in (item for item in descriptors if item is not None):
        if (
            descriptor.scope != target_scope
            or descriptor.start != target_start
            or descriptor.end != target_end
            or (claim_role == "primary" and descriptor.scope_role != "primary")
        ):
            return claim, ("综合推断声明的目标范围、时间或角色与依赖事实不一致。",)
    return _Claim(
        **{
            **claim.__dict__,
            "scope": _scope_payload(target_scope),
            "time_range": target_range,
            "claim_role": claim_role,
            "evidence_refs": refs,
        }
    ), ()


def _v2_composite_status(claim: _Claim, contract: AnswerContract) -> tuple[str, tuple[str, ...]]:
    """Apply evidence, primary-scope and wording guards to a composite."""
    support, reasons = _claim_support(claim, contract)
    if _scope_mismatch(claim.statement, claim.evidence_refs, contract):
        return "unsupported", (*reasons, "引用未支持主范围声明。")
    if _overclaim(
        claim.statement, contract.allowed_conclusion_strength, contract.causal_claims_allowed,
        model_knowledge=contract.model_knowledge_fallback,
    ):
        return "unsupported", (*reasons, "声明包含不允许的因果或确定性措辞。")
    if support == "supported" and 0 < len(set(claim.fact_indices)) < 2:
        # A single observation can explain itself but cannot cross-validate a
        # conclusion the way two independent observations can.
        return "limited", (*reasons, "仅由单条事实支撑的推断，只能给出受限结论。")
    return support, reasons


def _claim_support(claim: _Claim, contract: AnswerContract) -> tuple[str, tuple[str, ...]]:
    """Return fail-closed support status for one submitted declaration."""
    if claim.invalid_refs:
        return "unsupported", (f"含未许可引用：{', '.join(claim.invalid_refs)}。",)
    if contract.model_knowledge_fallback and (
        not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
    ):
        return "supported", ()
    if not claim.evidence_refs:
        return "unsupported", ("未提供可验证引用。",)

    evidence = contract.reference_evidence or {}
    reasons: list[str] = []
    limited = False
    for reference in claim.evidence_refs:
        item = evidence.get(reference)
        if not item:
            return "unsupported", (f"引用 {reference} 没有可追溯的证据检查。",)
        statuses = item.get("statuses") if isinstance(item.get("statuses"), dict) else {}
        if not statuses:
            return "unsupported", (f"引用 {reference} 未关联已检查证据。",)
        missing = [evidence_id for evidence_id, state in statuses.items() if state in {"missing", "optional_missing"}]
        if missing:
            return "unsupported", (f"引用 {reference} 关联证据未覆盖：{', '.join(missing)}。",)
        critical = tuple(item.get("critical_risk_codes") or ())
        conflicts = tuple(item.get("conflict_codes") or ())
        if critical or conflicts:
            codes = ", ".join((*critical, *conflicts))
            return "unsupported", (f"引用 {reference} 存在关键风险或冲突：{codes}。",)
        partial = [evidence_id for evidence_id, state in statuses.items() if state == "partial"]
        if partial:
            return "unsupported", (f"引用 {reference} 关联证据字段不完整：{', '.join(partial)}。",)
        warning_codes = tuple(item.get("risk_codes") or ())
        if warning_codes:
            limited = True
            reasons.append(f"引用 {reference} 存在限制：{', '.join(warning_codes)}。")
    return ("limited", tuple(dict.fromkeys(reasons))) if limited else ("supported", ())


def _final_claim_status(claim: _Claim, contract: AnswerContract) -> tuple[str, tuple[str, ...]]:
    """Combine evidence support with semantic, scope, and wording guards."""
    support, reasons = _claim_support(claim, contract)
    if _structured_claim_mismatch(claim, contract):
        return "unsupported", (*reasons, "结构化语义、范围、时间或粒度与引用不一致。")
    if _scope_mismatch(claim.statement, claim.evidence_refs, contract):
        return "unsupported", (*reasons, "引用未支持主范围声明。")
    if _overclaim(
        claim.statement, contract.allowed_conclusion_strength, contract.causal_claims_allowed,
        model_knowledge=contract.model_knowledge_fallback,
    ):
        return "unsupported", (*reasons, "声明包含不允许的因果或确定性措辞。")
    return support, reasons


def _claim_line(claim: _Claim) -> str:
    references = " ".join(
        "[模型通用知识]"
        if item == MODEL_KNOWLEDGE_REF
        else f"[数据 {item[5:]}]"
        if item.startswith("TOOL:")
        else f"[来源 {item}]"
        for item in claim.evidence_refs
    )
    details = []
    if claim.basis:
        details.append(f"依据：{claim.basis}")
    if claim.uncertainty:
        details.append(f"不确定性：{claim.uncertainty}")
    suffix = "；".join(details)
    return f"{claim.statement}{(' ' + references) if references else ''}{('；' + suffix) if suffix else ''}"


def _render_section(title: str, items: list[str], empty: str) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items) if items else lines.append(empty)
    return "\n".join(lines)


def _render_populated_sections(items: list[tuple[str, list[str]]]) -> tuple[str, tuple[str, ...]]:
    rendered = [(title, lines) for title, lines in items if lines]
    return "\n\n".join(
        "\n".join([f"## {title}", *(f"- {line}" for line in lines)])
        for title, lines in rendered
    ), tuple(title for title, _ in rendered)


def _clip_brief(value: str, limit: int) -> str:
    """Collapse whitespace and cap one brief-mode line at a sentence boundary."""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    for separator in ("。", "；", "，", " "):
        index = window.rfind(separator)
        if index >= limit // 2:
            return window[: index + 1].rstrip()
    return window[: limit - 1].rstrip() + "…"


_BUDGET_GROUP_KEYS = {
    "fact_lines": "facts",
    "inference_lines": "inferences",
    "hypothesis_lines": "hypotheses",
    "recommendation_lines": "recommendations",
    "limitation_lines": "limitations",
}


def _apply_mode_budget(mode: str, **groups: list[str]) -> tuple[dict[str, list[str]], int]:
    """Clip every claim group to the mode budget; returns (groups, dropped count)."""
    budget = _MODE_BUDGETS.get(mode)
    if budget is None:
        return {key: list(value) for key, value in groups.items()}, 0
    bounded: dict[str, list[str]] = {}
    dropped = 0
    for key, lines in groups.items():
        values = list(lines)
        if key == "limitation_lines":
            # Limitations carry compliance disclosures; clip but never drop them.
            bounded[key] = [_clip_brief(line, budget["item_chars"]) for line in values]
            continue
        cap = budget.get(_BUDGET_GROUP_KEYS.get(key, key))
        if cap is None:
            bounded[key] = values
            continue
        bounded[key] = [_clip_brief(line, budget["item_chars"]) for line in values[:cap]]
        dropped += max(0, len(values) - cap)
    return bounded, dropped


def _render_presentation(
    contract: AnswerContract, conclusion: str, fact_lines: list[str], inference_lines: list[str],
    hypothesis_lines: list[str], recommendation_lines: list[str], limitations: list[str],
) -> tuple[str, tuple[str, ...]]:
    limitation_lines = limitations
    labeled = [
        ("事实", fact_lines), ("推断", inference_lines), ("待验证", hypothesis_lines),
        ("建议", recommendation_lines), ("证据限制", limitation_lines),
    ]
    if contract.presentation == "brief":
        # Brief means brief: one short conclusion, at most two facts and three
        # limitations.  Long category joins were the reason "一句话总结" answers
        # still ran to thousands of characters.
        parts = [_clip_brief(conclusion, 160)]
        brief_facts = [_clip_brief(line, 90) for line in fact_lines[:2]]
        if brief_facts:
            parts.append("事实：" + "；".join(brief_facts))
        else:
            brief_hypotheses = [_clip_brief(line, 90) for line in hypothesis_lines[:2]]
            if brief_hypotheses:
                parts.append("待验证：" + "；".join(brief_hypotheses))
        if limitation_lines:
            parts.append("证据限制：" + "；".join(_clip_brief(line, 120) for line in limitation_lines[:3]))
        sections = ("结论",) + (("事实",) if brief_facts else ("待验证",) if hypothesis_lines else ())
        if limitation_lines:
            sections = sections + ("证据限制",)
        return "\n\n".join(parts), sections
    if contract.presentation == "table":
        rows = [("结论", conclusion)]
        rows.extend(("事实", line) for line in fact_lines)
        rows.extend(("推断", line) for line in inference_lines)
        rows.extend(("待验证", line) for line in hypothesis_lines)
        rows.extend(("建议", line) for line in recommendation_lines)
        def cell(value: str) -> str:
            return value.replace("|", "\\|").replace("\n", "<br>")
        table = "\n".join(["| 类型 | 内容 |", "| --- | --- |", *(f"| {cell(kind)} | {cell(line)} |" for kind, line in rows)])
        if limitation_lines:
            return table + "\n\n## 证据限制\n" + "\n".join(f"- {line}" for line in limitation_lines), ("表格", "证据限制")
        return table, ("表格",)
    if contract.presentation == "compact":
        blocks = [f"**结论**\n{conclusion}"]
        for title, values in labeled:
            if not values:
                continue
            blocks.append("\n".join([f"**{title}**", *(f"- {line}" for line in values)]))
        return "\n\n".join(blocks), ("结论", *(title for title, values in labeled if values))
    body, sections = _render_populated_sections([
        ("结论", [conclusion]), ("已确认事实", fact_lines), ("分析推断", inference_lines),
        ("待验证假设", hypothesis_lines), ("建议", recommendation_lines), ("证据限制", limitation_lines),
    ])
    return body, sections


def synthesize_submission(
    payload: dict[str, Any],
    contract: AnswerContract,
    sources: list[dict[str, Any]] | None = None,
    *,
    status: SynthesisStatus = "structured",
    repair_events: tuple[dict[str, Any], ...] = (),
) -> SynthesizedAnswer:
    repair_events = [item for item in repair_events if isinstance(item, dict)]
    # Missing collection fields have an unambiguous, evidence-neutral meaning.
    # We repair their shape locally rather than asking the model to regenerate
    # prose or invent support.  Values are not silently promoted to facts.
    for field in ("facts", "inferences", "hypotheses", "recommendations", "limitations"):
        if field not in payload:
            repair_events.append({
                "reason": "missing_structured_field",
                "affected_field": field,
                "outcome": "treated_as_empty",
            })
    if contract.status == "not_applicable":
        answer = _clean_text(payload.get("conclusion"), preserve_layout=True) or "分析完成。"
        return SynthesizedAnswer(answer, AnswerSynthesisReport(
            schema_version="1.0",
            synthesizer_version=contract.synthesizer_version,
            plan_id=contract.plan_id,
            status="not_applicable",
            allowed_conclusion_strength=contract.allowed_conclusion_strength,
            sections=(),
            source_refs=(),
            invalid_source_refs=(),
            moved_claims=0,
            wording_adjustments=(),
            repair_events=tuple(repair_events),
        ))

    allowed = {item.upper(): item for item in contract.permitted_source_refs}
    presentation, presentation_source = resolve_presentation(payload, contract)
    contract = replace(contract, presentation=presentation)
    protocol_version = payload.get("analysis_protocol_version")
    v2_protocol = protocol_version == ANALYSIS_PROTOCOL_VERSION
    unsupported_protocol = protocol_version is not None and not v2_protocol
    facts, invalid_facts = _parse_claims(payload.get("facts"), allowed)
    inferences, invalid_inferences = _parse_claims(payload.get("inferences"), allowed)
    hypotheses, invalid_hypotheses = _parse_claims(payload.get("hypotheses"), allowed)
    invalid = invalid_facts | invalid_inferences | invalid_hypotheses
    recommendations = _parse_recommendations(payload.get("recommendations"))
    adjustments: list[str] = []
    claim_support: list[dict[str, Any]] = []
    moved = 0

    def record_support(category: str, claim: _Claim, support: str, reasons: tuple[str, ...]) -> None:
        claim_support.append({
            "category": category,
            "statement": claim.statement,
            "evidence_refs": claim.evidence_refs,
            "support": support,
            "reasons": reasons,
        })

    verified_facts: list[_Claim] = []
    verified_fact_indices: dict[int, _Claim] = {}
    for fact_index, claim in enumerate(facts):
        uses_model_knowledge = not claim.invalid_refs and contract.model_knowledge_fallback and (
            not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
        )
        if uses_model_knowledge and not _overclaim(
            claim.statement, contract.allowed_conclusion_strength, contract.causal_claims_allowed,
            model_knowledge=True,
        ):
            record_support("fact", claim, "unsupported", (
                "模型通用知识不能确认厂内事实，已降级为模型通用知识推断。",
            ))
            inferences.append(_Claim(claim.statement, (MODEL_KNOWLEDGE_REF,)))
            moved += 1
        else:
            resolved_claim, protocol_reasons = (
                (claim, (f"不支持的 analysis_protocol_version：{protocol_version}。",))
                if unsupported_protocol
                else _v2_direct_fact(claim, contract)
                if v2_protocol
                else (claim, ())
            )
            support, reasons = (
                _v2_direct_fact_status(resolved_claim, contract)
                if v2_protocol and not protocol_reasons
                else ("unsupported", protocol_reasons)
                if protocol_reasons
                else _final_claim_status(resolved_claim, contract)
            )
            if support != "unsupported" and _fact_wording_mismatch(resolved_claim.statement):
                support, reasons = "unsupported", (*reasons, "直接事实不能使用因果、确定性、疑问或假设性措辞。")
            record_support("fact", resolved_claim, support, reasons)
            if support == "unsupported":
                hypotheses.append(_Claim(
                    resolved_claim.statement, resolved_claim.evidence_refs,
                    "；".join(reasons) or "复核原始工具记录与同口径对照数据。",
                    invalid_refs=resolved_claim.invalid_refs,
                ))
                moved += 1
                adjustments.append("将范围证据不匹配或未获声明级证据支持的事实降级为待验证假设。")
            else:
                verified_facts.append(resolved_claim)
                verified_fact_indices[fact_index] = resolved_claim
    facts = verified_facts

    if contract.model_knowledge_fallback:
        retained_hypotheses: list[_Claim] = []
        for claim in hypotheses:
            uses_model_knowledge = not claim.invalid_refs and (
                not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
            )
            if uses_model_knowledge and not _overclaim(
                claim.statement,
                contract.allowed_conclusion_strength,
                contract.causal_claims_allowed,
                model_knowledge=True,
            ):
                inferences.append(_Claim(claim.statement, (MODEL_KNOWLEDGE_REF,)))
                moved += 1
            else:
                retained_hypotheses.append(claim)
        hypotheses = retained_hypotheses

    retained_inferences: list[_Claim] = []
    verified_inference_indices: dict[int, _Claim] = {}
    for inference_index, claim in enumerate(inferences):
        uses_model_knowledge = not claim.invalid_refs and contract.model_knowledge_fallback and (
            not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
        )
        if uses_model_knowledge and not _overclaim(
            claim.statement,
            contract.allowed_conclusion_strength,
            contract.causal_claims_allowed,
            model_knowledge=True,
        ) and not _inference_wording_mismatch(claim.statement, model_knowledge=True):
            support, reasons = _claim_support(claim, contract)
            record_support("inference", claim, support, reasons)
            retained_inferences.append(_Claim(claim.statement, (MODEL_KNOWLEDGE_REF,)))
        else:
            composite_claim, protocol_reasons = (
                (claim, (f"不支持的 analysis_protocol_version：{protocol_version}。",))
                if unsupported_protocol
                else _v2_composite_inference(claim, verified_fact_indices, contract)
                if v2_protocol
                else (claim, ())
            )
            support, reasons = (
                _v2_composite_status(composite_claim, contract)
                if not protocol_reasons
                else ("unsupported", protocol_reasons)
            )
            if support != "unsupported" and _inference_wording_mismatch(
                composite_claim.statement, model_knowledge=contract.model_knowledge_fallback,
            ):
                support, reasons = "unsupported", (*reasons, "疑问或假设性因果表述必须归入待验证内容。")
            record_support("inference", composite_claim, support, reasons)
            if support == "unsupported":
                hypotheses.append(_Claim(
                    composite_claim.statement, composite_claim.evidence_refs,
                    composite_claim.verification or "；".join(reasons) or "补充同时间、同产品或同设备对照后验证。",
                    invalid_refs=composite_claim.invalid_refs,
                ))
                moved += 1
                adjustments.append("将范围证据不匹配或未获声明级证据支持的推断降级为待验证假设。")
            else:
                retained_inferences.append(composite_claim)
                verified_inference_indices[inference_index] = composite_claim
    inferences = retained_inferences
    if moved:
        adjustments.append(
            f"将 {moved} 条模型声明归类为模型通用知识或待验证内容。"
            if contract.model_knowledge_fallback
            else f"将 {moved} 条超出证据等级或缺少引用的声明降级为待验证假设。"
        )

    submitted_conclusion = _clean_text(payload.get("conclusion"))
    conclusion_refs: list[str] = []
    invalid_conclusion_refs: set[str] = set()
    for supplied in payload.get("conclusion_evidence_refs", []) if isinstance(payload.get("conclusion_evidence_refs"), list) else []:
        normalized = _normalize_ref(supplied, allowed)
        if normalized:
            conclusion_refs.append(normalized)
        elif str(supplied or "").strip():
            invalid_conclusion_refs.add(str(supplied).strip())
    invalid.update(invalid_conclusion_refs)
    conclusion_scope_mismatch = _scope_mismatch(
        submitted_conclusion,
        tuple(dict.fromkeys(conclusion_refs)),
        contract,
    )
    conclusion_claim_payload = payload.get("conclusion_claim") if isinstance(payload.get("conclusion_claim"), dict) else {}
    conclusion_claim = _Claim(
        statement=submitted_conclusion, evidence_refs=tuple(dict.fromkeys(conclusion_refs)),
        claim_kind=_clean_text(conclusion_claim_payload.get("claim_kind"), 80),
        semantic_id=_clean_text(conclusion_claim_payload.get("semantic_id"), 120),
        scope=conclusion_claim_payload.get("scope") if isinstance(conclusion_claim_payload.get("scope"), dict) else None,
        time_range=conclusion_claim_payload.get("time_range") if isinstance(conclusion_claim_payload.get("time_range"), dict) else None,
        grain=_clean_text(conclusion_claim_payload.get("grain"), 80),
        claim_role=_clean_text(conclusion_claim_payload.get("claim_role"), 20) or "primary",
        invalid_refs=tuple(sorted(invalid_conclusion_refs)),
    )
    if unsupported_protocol:
        conclusion_support, conclusion_reasons = "unsupported", (f"不支持的 analysis_protocol_version：{protocol_version}。",)
    elif v2_protocol:
        indices = conclusion_claim_payload.get("inference_indices")
        invalid_indices = (
            not isinstance(indices, list)
            or not indices
            or any(not isinstance(index, int) or isinstance(index, bool) for index in indices)
            or len(set(indices)) != len(indices)
        )
        dependencies = [] if invalid_indices else [verified_inference_indices.get(index) for index in indices]
        if invalid_indices or any(item is None for item in dependencies):
            conclusion_support, conclusion_reasons = "unsupported", ("v2 结论必须引用已验证综合推断的 inference_indices。",)
        else:
            resolved_dependencies = [item for item in dependencies if item is not None]
            conclusion_claim, derivation_reasons = _v2_conclusion_claim(
                conclusion_claim, conclusion_claim_payload, resolved_dependencies
            )
            if derivation_reasons:
                conclusion_support, conclusion_reasons = "unsupported", derivation_reasons
            elif invalid_conclusion_refs:
                conclusion_support, conclusion_reasons = "unsupported", ("v2 结论含未许可引用。",)
            else:
                derived_refs = tuple(dict.fromkeys(ref for item in resolved_dependencies for ref in item.evidence_refs))
                if conclusion_refs and set(conclusion_refs) != set(derived_refs):
                    conclusion_support, conclusion_reasons = "unsupported", ("v2 结论引用必须由已验证综合推断服务端推导。",)
                else:
                    conclusion_claim = _Claim(**{**conclusion_claim.__dict__, "evidence_refs": derived_refs})
                    conclusion_refs = list(derived_refs)
                    conclusion_scope_mismatch = _scope_mismatch(
                        submitted_conclusion, conclusion_claim.evidence_refs, contract,
                    )
                    if conclusion_scope_mismatch:
                        conclusion_support, conclusion_reasons = "unsupported", ("引用未支持主范围声明。",)
                    else:
                        conclusion_support, conclusion_reasons = _v2_composite_status(conclusion_claim, contract)
    else:
        conclusion_scope_mismatch = conclusion_scope_mismatch or _structured_claim_mismatch(conclusion_claim, contract)
        if contract.model_knowledge_fallback:
            conclusion_support, conclusion_reasons = _claim_support(conclusion_claim, contract)
            if _overclaim(
                submitted_conclusion, contract.allowed_conclusion_strength, contract.causal_claims_allowed,
                model_knowledge=True,
            ):
                conclusion_support = "unsupported"
                conclusion_reasons = (*conclusion_reasons, "声明包含不允许的因果或确定性措辞。")
        else:
            conclusion_support, conclusion_reasons = _final_claim_status(conclusion_claim, contract)
    record_support("conclusion", conclusion_claim, conclusion_support, conclusion_reasons)
    if contract.model_knowledge_fallback:
        safe_conclusion = (
            submitted_conclusion
            if submitted_conclusion and conclusion_support != "unsupported"
            else "可以提供一般性技术说明，但不能据此确认厂内实际情况。"
        )
        conclusion = f"> {MODEL_KNOWLEDGE_DISCLOSURE}\n\n{safe_conclusion}"
        if submitted_conclusion and safe_conclusion != submitted_conclusion:
            hypotheses.append(_Claim(
                submitted_conclusion, tuple(dict.fromkeys(conclusion_refs)),
                "；".join(conclusion_reasons) or "使用厂内文档或制造数据复核。",
                invalid_refs=tuple(sorted(invalid_conclusion_refs)),
            ))
            moved += 1
            adjustments.append("将模型通用知识中的确定性结论降级为待验证假设。")
    elif contract.allowed_conclusion_strength == "insufficient" and conclusion_support == "unsupported":
        conclusion = "当前必需证据不足，不能形成诊断性结论。"
        if submitted_conclusion:
            hypotheses.append(_Claim(
                submitted_conclusion, tuple(dict.fromkeys(conclusion_refs)),
                "；".join(conclusion_reasons) or "补齐必需证据后重新评估。",
                invalid_refs=tuple(sorted(invalid_conclusion_refs)),
            ))
            moved += 1
            adjustments.append("将范围证据不匹配或未获声明级证据支持的结论降级为待验证假设。")
    elif conclusion_scope_mismatch or conclusion_support == "unsupported":
        conclusion = "当前证据未能验证模型提交的结论。"
        if submitted_conclusion:
            hypotheses.append(_Claim(
                submitted_conclusion,
                tuple(dict.fromkeys(conclusion_refs)),
                "；".join(conclusion_reasons) or "补充与主范围一致的工具证据后重新评估。",
                invalid_refs=tuple(sorted(invalid_conclusion_refs)),
            ))
            moved += 1
            adjustments.append("将范围证据不匹配或未获声明级证据支持的结论降级为待验证假设。")
    elif submitted_conclusion and not _overclaim(
        submitted_conclusion,
        contract.allowed_conclusion_strength,
        contract.causal_claims_allowed,
        model_knowledge=contract.model_knowledge_fallback,
    ):
        conclusion = submitted_conclusion
    else:
        conclusion = "当前证据支持方向性判断，但尚未证明因果关系。"
        if submitted_conclusion:
            hypotheses.append(_Claim(submitted_conclusion, (), "通过受控对照或补充时序证据验证。"))
            moved += 1
            adjustments.append("移除结论中的因果性措辞并转入待验证假设。")

    submitted_limitations = (
        []
        if contract.model_knowledge_fallback
        else [
            _clean_text(item, 1600) for item in payload.get("limitations", [])
            if _clean_text(item, 1600)
        ]
        if isinstance(payload.get("limitations"), list)
        else []
    )
    limitations = list(dict.fromkeys([*contract.mandatory_limitations, *submitted_limitations]))
    supplied_sources = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []
    used_refs = {
        reference
        for claim in (*facts, *inferences, *hypotheses)
        for reference in claim.evidence_refs
    }
    used_refs.update(conclusion_refs)
    for supplied in supplied_sources:
        normalized = _normalize_ref(supplied, allowed)
        if normalized:
            used_refs.add(normalized)
        elif str(supplied or "").strip():
            invalid.add(str(supplied).strip())
    ordered_refs = tuple(item for item in contract.permitted_source_refs if item in used_refs)

    fact_lines = [_claim_line(item) for item in facts]
    inference_lines = [_claim_line(item) for item in inferences]
    hypothesis_lines = [
        f"{_claim_line(item)} 验证：{item.verification or '补充同口径对照数据。'}"
        for item in hypotheses
    ]
    recommendation_lines = [
        f"{item.action.rstrip('。；;')}{('；依据：' + item.rationale) if item.rationale else ''}"
        f"{'；需工程与制造人员复核' if item.requires_review else ''}"
        for item in recommendations
    ]
    if contract.model_knowledge_fallback:
        model_limitations = limitations or [MODEL_KNOWLEDGE_DISCLOSURE]
        bounded, _truncated_model = _apply_mode_budget(
            contract.presentation,
            inference_lines=inference_lines,
            hypothesis_lines=hypothesis_lines,
            recommendation_lines=recommendation_lines,
            limitation_lines=model_limitations,
        )
        inference_lines = bounded.get("inference_lines", inference_lines)
        hypothesis_lines = bounded.get("hypothesis_lines", hypothesis_lines)
        recommendation_lines = bounded.get("recommendation_lines", recommendation_lines)
        model_limitations = bounded.get("limitation_lines", model_limitations)
        if contract.presentation == "brief":
            # Model-knowledge answers keep every retained category: dropping a
            # disclosure or a verification step would hide that the answer is not
            # plant evidence.
            parts = [conclusion]
            for title, lines in (
                ("模型通用知识", inference_lines), ("待验证内容", hypothesis_lines),
                ("建议", recommendation_lines), ("使用限制", model_limitations),
            ):
                if lines:
                    parts.append(f"{title}：{'；'.join(lines)}")
            answer = "\n".join(parts)
            sections = tuple(title for title, lines in (
                ("结论", [conclusion]), ("模型通用知识", inference_lines),
                ("待验证内容", hypothesis_lines), ("建议", recommendation_lines),
                ("使用限制", model_limitations),
            ) if lines)
        elif contract.presentation == "table":
            rows = [("结论", conclusion)]
            rows.extend(("模型通用知识", line) for line in inference_lines)
            rows.extend(("待验证内容", line) for line in hypothesis_lines)
            rows.extend(("建议", line) for line in recommendation_lines)
            rows.extend(("使用限制", line) for line in model_limitations)
            def cell(value: str) -> str:
                return value.replace("|", "\\|").replace("\n", "<br>")
            table = "\n".join(["| 类型 | 内容 |", "| --- | --- |", *(f"| {cell(kind)} | {cell(line)} |" for kind, line in rows)])
            answer = table
            sections = ("表格",)
        elif contract.presentation == "compact":
            blocks = [f"**结论**\n{conclusion}"]
            for title, values in (
                ("模型通用知识", inference_lines),
                ("待验证内容", hypothesis_lines),
                ("建议", recommendation_lines),
                ("使用限制", model_limitations),
            ):
                if values:
                    blocks.append("\n".join([f"**{title}**", *(f"- {line}" for line in values)]))
            answer = "\n\n".join(blocks)
            sections = ("结论", "模型通用知识", "待验证内容", "建议", "使用限制")
            sections = tuple(title for title in sections if title == "结论" or {
                "模型通用知识": inference_lines, "待验证内容": hypothesis_lines,
                "建议": recommendation_lines, "使用限制": model_limitations,
            }[title])
        else:
            answer, sections = _render_populated_sections([
                ("结论", [conclusion]), ("模型通用知识", inference_lines),
                ("待验证内容", hypothesis_lines), ("建议", recommendation_lines),
                ("使用限制", model_limitations),
            ])
    else:
        bounded, truncated_items = _apply_mode_budget(
            contract.presentation,
            fact_lines=fact_lines,
            inference_lines=inference_lines,
            hypothesis_lines=hypothesis_lines,
            recommendation_lines=recommendation_lines,
            limitation_lines=limitations,
        )
        fact_lines = bounded.get("fact_lines", fact_lines)
        inference_lines = bounded.get("inference_lines", inference_lines)
        hypothesis_lines = bounded.get("hypothesis_lines", hypothesis_lines)
        recommendation_lines = bounded.get("recommendation_lines", recommendation_lines)
        limitations = bounded.get("limitation_lines", limitations)
        if truncated_items:
            limitations = limitations + [f"为控制篇幅，已省略 {truncated_items} 条声明。"]
        answer, sections = _render_presentation(
            contract, conclusion, fact_lines, inference_lines, hypothesis_lines,
            recommendation_lines, limitations,
        )
    report = AnswerSynthesisReport(
        schema_version="1.2",
        synthesizer_version=contract.synthesizer_version,
        plan_id=contract.plan_id,
        status=status,
        allowed_conclusion_strength=contract.allowed_conclusion_strength,
        sections=sections,
        source_refs=ordered_refs,
        invalid_source_refs=tuple(sorted(invalid)),
        moved_claims=moved,
        wording_adjustments=tuple(dict.fromkeys(adjustments)),
        claim_support=tuple(claim_support),
        analysis_protocol_version=(ANALYSIS_PROTOCOL_VERSION if v2_protocol else "1.1"),
        repair_events=tuple(repair_events),
        presentation=contract.presentation,
        presentation_source=presentation_source,
    )
    return SynthesizedAnswer(answer, report)


def synthesize_legacy_answer(
    answer: str,
    contract: AnswerContract,
    sources: list[dict[str, Any]] | None = None,
    *,
    repair_events: tuple[dict[str, Any], ...] = (),
) -> SynthesizedAnswer:
    if contract.status == "not_applicable":
        permitted = {item.upper() for item in contract.permitted_source_refs}
        refs = tuple(dict.fromkeys(
            item for item in _embedded_refs(answer) if item.upper() in permitted
        ))
        return SynthesizedAnswer(answer, AnswerSynthesisReport(
            schema_version="1.0",
            synthesizer_version=contract.synthesizer_version,
            plan_id=contract.plan_id,
            status="not_applicable",
            allowed_conclusion_strength=contract.allowed_conclusion_strength,
            sections=(),
            source_refs=refs,
            invalid_source_refs=(),
            moved_claims=0,
            wording_adjustments=(),
        ))
    blocks = _legacy_blocks(answer)
    refs = [item for item in _embedded_refs(answer) if item.upper() in {
        allowed.upper() for allowed in contract.permitted_source_refs
    }]
    if contract.model_knowledge_fallback:
        refs = [MODEL_KNOWLEDGE_REF]
    # A legacy body lacks the schema data needed to confirm manufacturing facts.
    # Preserve each natural-language block as a separately labelled item and
    # keep it in the verification bucket.  Even a valid embedded source ID is
    # not enough to turn an arbitrary legacy assertion into a verified fact.
    claims = [
        {
            "statement": _SOURCE_PATTERN.sub("", block).strip(),
            # Keep every supplied ID for the normal claim parser: permitted
            # IDs are normalized, while invalid ones remain in the report and
            # cannot be laundered into a supported fact.
            "evidence_refs": _embedded_refs(block),
            "verification": "按证据限制补充验证。",
        }
        for block in blocks
        if _SOURCE_PATTERN.sub("", block).strip()
    ]
    payload = {
        "conclusion": "基于模型通用知识提供一般性技术说明。" if contract.model_knowledge_fallback else "",
        "conclusion_evidence_refs": [MODEL_KNOWLEDGE_REF] if contract.model_knowledge_fallback else [],
        "facts": [],
        "inferences": claims if contract.model_knowledge_fallback else [],
        "hypotheses": [] if contract.model_knowledge_fallback else claims,
        "recommendations": [],
        "limitations": ["模型未使用结构化提交，服务端已执行安全降级；保留的原文均未作为已确认生产事实。"],
        "source_refs": refs,
    }
    synthesized = synthesize_submission(payload, contract, sources, status="repaired", repair_events=(
        *repair_events,
        {"reason": "legacy_unstructured_answer", "affected_field": "display_blocks",
         "outcome": "preserved_as_unverified_blocks"},
    ))
    if contract.model_knowledge_fallback:
        # General technical knowledge is still display-oriented prose.  Keep
        # its layout while retaining the mandatory non-factory disclosure.
        permitted = {item.upper() for item in contract.permitted_source_refs}
        def mark_invalid_refs(block: str) -> str:
            return _SOURCE_PATTERN.sub(
                lambda match: match.group(0) if all(
                    item.upper() in permitted
                    for item in re.split(r"[,，、\s]+", match.group(1)) if item
                ) else "[无效来源：" + match.group(1) + "]",
                block,
            )
        disclosure = MODEL_KNOWLEDGE_DISCLOSURE
        rendered = disclosure + "\n\n## 模型通用知识：[模型通用知识]\n\n" + "\n\n".join(mark_invalid_refs(block) for block in blocks)
        limits = list(contract.mandatory_limitations)
        if limits:
            rendered += "\n\n## 使用限制\n" + "\n".join(f"- {item}" for item in limits)
        return SynthesizedAnswer(rendered, replace(
            synthesized.report,
            sections=("模型通用知识", "使用限制") if limits else ("模型通用知识",),
        ))
    # Do not route display-oriented fallback prose through claim rendering:
    # it would flatten lists/tables and make a tentative block resemble a
    # verified bullet.  The whole block remains explicitly unverified.
    invalid = synthesized.report.invalid_source_refs
    permitted = {item.upper() for item in contract.permitted_source_refs}
    def mark_invalid_refs(block: str) -> str:
        def replace_ref(match: re.Match[str]) -> str:
            refs = [item for item in re.split(r"[,，、\s]+", match.group(1)) if item]
            if refs and all(item.upper() in permitted for item in refs):
                return match.group(0)
            return "[无效来源：" + match.group(1) + "]"
        return _SOURCE_PATTERN.sub(replace_ref, block)
    rendered = "## 待验证原文（未经结构化验证）\n\n" + "\n\n".join(
        mark_invalid_refs(block) for block in blocks
    )
    limitations = ["证据限制：以下原文仅保留其展示结构，未作为已确认生产事实。"]
    limitations.extend(contract.mandatory_limitations)
    if invalid:
        limitations.append("未接受的引用仍保留在原文中，仅作审计记录：" + ", ".join(invalid) + "。")
    rendered += "\n\n## 证据限制\n" + "\n".join(f"- {item}" for item in limitations)
    return SynthesizedAnswer(rendered, replace(
        synthesized.report,
        sections=("待验证原文（未经结构化验证）", "证据限制"),
    ))





