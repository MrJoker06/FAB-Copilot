from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .evidence_validator import EvidenceValidation
from .evidence_semantics import EvidenceDescriptor, EvidenceScope, supports_claim


SynthesisStatus = Literal["structured", "repaired", "not_applicable"]

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
                "conclusion": {"type": "string", "maxLength": 600},
                "conclusion_evidence_refs": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "conclusion_claim": {"type": "object", "properties": {"claim_kind": {"type": "string", "enum": ["metric", "record", "event", "document", "sample"]}, "semantic_id": {"type": "string"}, "scope": {"type": "object"}, "grain": {"type": "string"}, "time_range": {"type": "object"}, "claim_role": {"type": "string", "enum": ["primary", "background"]}}, "required": ["claim_kind", "semantic_id", "scope", "grain", "time_range", "claim_role"], "additionalProperties": False},
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
                        "required": ["statement", "evidence_refs", "claim_kind", "semantic_id", "scope", "grain", "time_range", "claim_role"],
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
                            "claim_kind": {"type": "string", "enum": ["metric", "record", "event", "document", "sample"]},
                            "semantic_id": {"type": "string"},
                            "scope": {"type": "object"},
                            "time_range": {"type": "object"},
                            "grain": {"type": "string"},
                            "claim_role": {"type": "string", "enum": ["primary", "background"]},
                        },
                        "required": ["statement", "evidence_refs", "claim_kind", "semantic_id", "scope", "grain", "time_range", "claim_role"],
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
_CAUSAL_PATTERN = re.compile(r"(?:直接|已经|必然)?导致|证明.{0,12}(?:根因|原因)|根因(?:为|是)")
_DEFINITIVE_PATTERN = re.compile(r"主要原因(?:为|是)|可以确定|已经证实|确定无疑")
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
    submission_tool: str = "submit_analysis"

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, default=str))

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

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, default=str))


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


@dataclass(frozen=True)
class _Recommendation:
    action: str
    rationale: str
    requires_review: bool


def _clean_text(value: Any, limit: int = 3000) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


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
    required = validation.status == "validated"
    return AnswerContract(
        schema_version="1.1",
        synthesizer_version="1.1.0",
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
    )


def synthesizer_system_message(contract: AnswerContract) -> str:
    if contract.status == "not_applicable":
        return (
            "当前 answer_contract.status=not_applicable，可按通用规则直接回答；"
            "不得伪造来源或展示隐藏思维链。\n"
            f"answer_contract={contract.to_prompt()}"
        )
    return (
        "最终回答必须通过 submit_analysis 提交，不要直接输出最终正文。"
        "facts 只放工具结果直接支持的事实且必须填写 permitted_source_refs；"
        "inferences 是基于事实的解释，hypotheses 必须包含验证方法，recommendations 必须说明依据与复核要求。"
        "保持精炼：只保留对决策最重要的条目，不要逐行复述工具结果或穷举全部设备。"
        + (
            f"知识库检索没有返回可用内容，允许使用 {MODEL_KNOWLEDGE_REF} 作为模型通用知识标识。"
            "应直接回答用户的一般性技术问题，将通用知识放入 inferences；"
            "conclusion 直接概括技术回答，不要重复知识库无结果声明，服务端会统一添加；"
            "不得把它写成厂内 SOP、配方、规格或当前生产事实，并必须明确披露知识库无结果。"
            if contract.model_knowledge_fallback
            else ""
        )
        + "制造域的 facts、inferences 和 conclusion_claim 必须从 answer_contract.source_semantics 逐项复制 claim_kind、semantic_id、scope、grain 和 time_range；不得根据用户目标范围猜测证据范围。"
        + "不得提交隐藏思维链、逐 token 推理或未在 permitted_source_refs 中的来源。"
        "conclusion_evidence_refs 必须列出结论依据；仅由 context_only 来源支持的整厂背景不得表述为主范围自身指标。"
        "结论不得超过 allowed_conclusion_strength，causal_claims_allowed=false 时不得声称已证明因果。\n"
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
        for supplied in supplied_refs:
            normalized = _normalize_ref(supplied, allowed)
            if normalized:
                refs.append(normalized)
            elif str(supplied or "").strip():
                invalid.add(str(supplied).strip())
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


def _overclaim(statement: str, strength: str, causal_allowed: bool) -> bool:
    if not causal_allowed and _CAUSAL_PATTERN.search(statement):
        return True
    return strength in {"insufficient", "hypothesis_only"} and bool(_DEFINITIVE_PATTERN.search(statement))


def _scope_mismatch(statement: str, references: tuple[str, ...], contract: AnswerContract) -> bool:
    if contract.primary_scope_type not in {"process", "equipment", "product"}:
        return False
    normalized = statement.lower()
    if not any(label.lower() in normalized for label in contract.primary_scope_labels if label):
        return False
    if not references:
        return True
    return all(contract.source_scope_roles.get(reference, "unknown") != "primary" for reference in references)


def _structured_claim_mismatch(claim: _Claim, contract: AnswerContract) -> bool:
    """Validate structured manufacturing claims without inspecting claim prose."""
    manufacturing = contract.primary_scope_type in {"fab", "process", "equipment", "product", "lot"}
    if claim.claim_role not in {"primary", "background"}:
        return True
    if not (claim.claim_kind or claim.semantic_id or claim.scope or claim.time_range or claim.grain):
        return manufacturing
    if not claim.claim_kind or not claim.semantic_id or not claim.scope or not claim.grain or claim.time_range is None or not claim.evidence_refs:
        return True
    try:
        claim_scope = EvidenceScope(**{
            key: tuple(str(value).upper() for value in values)
            for key, values in claim.scope.items()
            if key in EvidenceScope.__dataclass_fields__
            and isinstance(values, (list, tuple))
        })
    except (TypeError, ValueError):
        return True
    for reference in claim.evidence_refs:
        metadata = contract.source_semantics.get(reference)
        if not metadata:
            continue
        descriptor = EvidenceDescriptor(
            source_ref=reference, kind=metadata.get("kind", "unknown"),
            semantic_id=metadata.get("semantic_id", "unknown"),
            scope=EvidenceScope(**metadata.get("scope", {})), grain=metadata.get("grain", "unknown"),
            start=metadata.get("start"), end=metadata.get("end"),
            filter_provenance=metadata.get("filter_provenance", "unknown"),
            scope_role=metadata.get("scope_role", "primary"),
        )
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


def _claim_line(claim: _Claim) -> str:
    references = " ".join(
        "[模型通用知识]"
        if item == MODEL_KNOWLEDGE_REF
        else f"[数据 {item[5:]}]"
        if item.startswith("TOOL:")
        else f"[来源 {item}]"
        for item in claim.evidence_refs
    )
    return f"{claim.statement}{(' ' + references) if references else ''}"


def _render_section(title: str, items: list[str], empty: str) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items) if items else lines.append(empty)
    return "\n".join(lines)


def synthesize_submission(
    payload: dict[str, Any],
    contract: AnswerContract,
    sources: list[dict[str, Any]] | None = None,
    *,
    status: SynthesisStatus = "structured",
) -> SynthesizedAnswer:
    if contract.status == "not_applicable":
        answer = _clean_text(payload.get("conclusion")) or "分析完成。"
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
        ))

    allowed = {item.upper(): item for item in contract.permitted_source_refs}
    facts, invalid_facts = _parse_claims(payload.get("facts"), allowed)
    inferences, invalid_inferences = _parse_claims(payload.get("inferences"), allowed)
    hypotheses, invalid_hypotheses = _parse_claims(payload.get("hypotheses"), allowed)
    invalid = invalid_facts | invalid_inferences | invalid_hypotheses
    recommendations = _parse_recommendations(payload.get("recommendations"))
    adjustments: list[str] = []
    moved = 0

    verified_facts: list[_Claim] = []
    for claim in facts:
        uses_model_knowledge = contract.model_knowledge_fallback and (
            not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
        )
        if _structured_claim_mismatch(claim, contract) or _scope_mismatch(claim.statement, claim.evidence_refs, contract):
            hypotheses.append(_Claim(
                claim.statement,
                claim.evidence_refs,
                "补充与主范围一致的工具证据后复核。",
            ))
            moved += 1
            adjustments.append("将范围证据不匹配的事实降级为待验证假设。")
        elif uses_model_knowledge and not _overclaim(
            claim.statement,
            contract.allowed_conclusion_strength,
            contract.causal_claims_allowed,
        ):
            inferences.append(_Claim(claim.statement, (MODEL_KNOWLEDGE_REF,)))
            moved += 1
        elif not claim.evidence_refs or _overclaim(
            claim.statement,
            contract.allowed_conclusion_strength,
            contract.causal_claims_allowed,
        ):
            hypotheses.append(_Claim(claim.statement, claim.evidence_refs, "复核原始工具记录与同口径对照数据。"))
            moved += 1
        else:
            verified_facts.append(claim)
    facts = verified_facts

    if contract.model_knowledge_fallback:
        retained_hypotheses: list[_Claim] = []
        for claim in hypotheses:
            uses_model_knowledge = not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
            if uses_model_knowledge and not _overclaim(
                claim.statement,
                contract.allowed_conclusion_strength,
                contract.causal_claims_allowed,
            ):
                inferences.append(_Claim(claim.statement, (MODEL_KNOWLEDGE_REF,)))
                moved += 1
            else:
                retained_hypotheses.append(claim)
        hypotheses = retained_hypotheses

    retained_inferences: list[_Claim] = []
    for claim in inferences:
        uses_model_knowledge = contract.model_knowledge_fallback and (
            not claim.evidence_refs or set(claim.evidence_refs) == {MODEL_KNOWLEDGE_REF}
        )
        if _structured_claim_mismatch(claim, contract) or _scope_mismatch(claim.statement, claim.evidence_refs, contract):
            hypotheses.append(_Claim(
                claim.statement,
                claim.evidence_refs,
                claim.verification or "补充与主范围一致的工具证据后复核。",
            ))
            moved += 1
            adjustments.append("将范围证据不匹配的推断降级为待验证假设。")
        elif uses_model_knowledge and not _overclaim(
            claim.statement,
            contract.allowed_conclusion_strength,
            contract.causal_claims_allowed,
        ):
            retained_inferences.append(_Claim(claim.statement, (MODEL_KNOWLEDGE_REF,)))
        elif contract.allowed_conclusion_strength in {"insufficient", "hypothesis_only"} or _overclaim(
            claim.statement,
            contract.allowed_conclusion_strength,
            contract.causal_claims_allowed,
        ):
            hypotheses.append(_Claim(
                claim.statement,
                claim.evidence_refs,
                claim.verification or "补充同时间、同产品或同设备对照后验证。",
            ))
            moved += 1
        else:
            retained_inferences.append(claim)
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
    )
    conclusion_scope_mismatch = conclusion_scope_mismatch or _structured_claim_mismatch(conclusion_claim, contract)
    if contract.model_knowledge_fallback:
        safe_conclusion = (
            submitted_conclusion
            if submitted_conclusion and not _overclaim(
                submitted_conclusion,
                contract.allowed_conclusion_strength,
                contract.causal_claims_allowed,
            )
            else "可以提供一般性技术说明，但不能据此确认厂内实际情况。"
        )
        conclusion = f"> {MODEL_KNOWLEDGE_DISCLOSURE}\n\n{safe_conclusion}"
        if submitted_conclusion and safe_conclusion != submitted_conclusion:
            hypotheses.append(_Claim(submitted_conclusion, (), "使用厂内文档或制造数据复核。"))
            moved += 1
            adjustments.append("将模型通用知识中的确定性结论降级为待验证假设。")
    elif contract.allowed_conclusion_strength == "insufficient":
        conclusion = "当前必需证据不足，不能形成诊断性结论。"
        if submitted_conclusion:
            hypotheses.append(_Claim(submitted_conclusion, (), "补齐必需证据后重新评估。"))
            moved += 1
            adjustments.append("将模型提交的结论降级为待验证假设。")
    elif contract.allowed_conclusion_strength == "hypothesis_only":
        conclusion = "当前证据仅支持形成待验证假设，不能确认主要原因或因果关系。"
        if submitted_conclusion:
            hypotheses.append(_Claim(submitted_conclusion, (), "按证据限制中的缺口补充验证。"))
            moved += 1
            adjustments.append("将模型提交的结论降级为待验证假设。")
    elif conclusion_scope_mismatch:
        conclusion = "当前证据没有以一致范围支持模型提交的主范围结论。"
        if submitted_conclusion:
            hypotheses.append(_Claim(
                submitted_conclusion,
                tuple(dict.fromkeys(conclusion_refs)),
                "补充与主范围一致的工具证据后重新评估。",
            ))
            moved += 1
            adjustments.append("将范围证据不匹配的结论降级为待验证假设。")
    elif submitted_conclusion and not _overclaim(
        submitted_conclusion,
        contract.allowed_conclusion_strength,
        contract.causal_claims_allowed,
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
        sections = MODEL_KNOWLEDGE_SECTIONS
        answer = "\n\n".join((
            f"## 结论\n{conclusion}",
            _render_section("模型通用知识", inference_lines, "模型没有返回可展示的通用知识内容。"),
            _render_section("待验证内容", hypothesis_lines, "没有额外待验证内容。"),
            _render_section("建议", recommendation_lines, "如需厂内结论，请补充或上传相关正式文档。"),
            _render_section("使用限制", limitations, MODEL_KNOWLEDGE_DISCLOSURE),
        ))
    else:
        sections = REQUIRED_SECTIONS
        answer = "\n\n".join((
            f"## 结论\n{conclusion}",
            _render_section("已确认事实", fact_lines, "当前没有可通过有效引用独立确认的事实。"),
            _render_section("分析推断", inference_lines, "当前没有在证据等级内保留的分析推断。"),
            _render_section("待验证假设", hypothesis_lines, "当前没有额外的待验证假设。"),
            _render_section("建议", recommendation_lines, "先补齐证据缺口，再决定后续处置。"),
            _render_section("证据限制", limitations, "未识别到额外证据限制。"),
        ))
    report = AnswerSynthesisReport(
        schema_version="1.0",
        synthesizer_version=contract.synthesizer_version,
        plan_id=contract.plan_id,
        status=status,
        allowed_conclusion_strength=contract.allowed_conclusion_strength,
        sections=sections,
        source_refs=ordered_refs,
        invalid_source_refs=tuple(sorted(invalid)),
        moved_claims=moved,
        wording_adjustments=tuple(dict.fromkeys(adjustments)),
    )
    return SynthesizedAnswer(answer, report)


def synthesize_legacy_answer(
    answer: str,
    contract: AnswerContract,
    sources: list[dict[str, Any]] | None = None,
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
    refs = [item for item in _embedded_refs(answer) if item.upper() in {
        allowed.upper() for allowed in contract.permitted_source_refs
    }]
    if contract.model_knowledge_fallback:
        refs = [MODEL_KNOWLEDGE_REF]
    claim = {"statement": _SOURCE_PATTERN.sub("", answer), "evidence_refs": refs}
    low_strength = contract.allowed_conclusion_strength in {"insufficient", "hypothesis_only"}
    payload = {
        "conclusion": "基于模型通用知识提供一般性技术说明。" if contract.model_knowledge_fallback else "",
        "conclusion_evidence_refs": [MODEL_KNOWLEDGE_REF] if contract.model_knowledge_fallback else [],
        "facts": [],
        "inferences": [claim] if contract.model_knowledge_fallback or not low_strength else [],
        "hypotheses": (
            [{**claim, "verification": "按证据限制补充验证。"}]
            if low_strength and not contract.model_knowledge_fallback
            else []
        ),
        "recommendations": [],
        "limitations": ["模型未使用结构化提交，服务端已执行安全降级。"],
        "source_refs": refs,
    }
    return synthesize_submission(payload, contract, sources, status="repaired")
