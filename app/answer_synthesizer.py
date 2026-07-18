from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .evidence_validator import EvidenceValidation


SynthesisStatus = Literal["structured", "repaired", "not_applicable"]

REQUIRED_SECTIONS = (
    "结论",
    "已确认事实",
    "分析推断",
    "待验证假设",
    "建议",
    "证据限制",
    "来源",
)

SUBMIT_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_analysis",
        "description": "提交最终结构化分析。它不是数据工具，不得包含隐藏思维链；只提交面向用户的事实、推断、假设、建议、限制和引用。",
        "parameters": {
            "type": "object",
            "properties": {
                "conclusion": {"type": "string"},
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["statement", "evidence_refs"],
                        "additionalProperties": False,
                    },
                },
                "inferences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["statement", "evidence_refs"],
                        "additionalProperties": False,
                    },
                },
                "hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "statement": {"type": "string"},
                            "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            "verification": {"type": "string"},
                        },
                        "required": ["statement", "evidence_refs", "verification"],
                        "additionalProperties": False,
                    },
                },
                "recommendations": {
                    "type": "array",
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
                "limitations": {"type": "array", "items": {"type": "string"}},
                "source_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "conclusion",
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
) -> AnswerContract:
    matched_tools = {
        tool
        for check in validation.evidence_checks
        if check.status in {"covered", "partial"}
        for tool in check.matched_tools
    }
    source_refs = (
        {
            str(source.get("reference_id"))
            for source in sources or []
            if source.get("reference_id")
        }
        if "search_knowledge" in matched_tools
        else set()
    )
    permitted = tuple(sorted({*(f"TOOL:{tool}" for tool in matched_tools), *source_refs}))
    required = validation.status == "validated"
    return AnswerContract(
        schema_version="1.0",
        synthesizer_version="1.0.0",
        plan_id=validation.plan_id,
        status="required" if required else "not_applicable",
        allowed_conclusion_strength=validation.allowed_conclusion_strength,
        causal_claims_allowed=validation.causal_claims_allowed,
        required_sections=REQUIRED_SECTIONS if required else (),
        permitted_source_refs=permitted,
        mandatory_limitations=_validation_limitations(validation),
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
        "不得提交隐藏思维链、逐 token 推理或未在 permitted_source_refs 中的来源。"
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


def _claim_line(claim: _Claim) -> str:
    references = " ".join(
        f"[数据 {item[5:]}]" if item.startswith("TOOL:") else f"[来源 {item}]"
        for item in claim.evidence_refs
    )
    return f"{claim.statement}{(' ' + references) if references else ''}"


def _render_section(title: str, items: list[str], empty: str) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items) if items else lines.append(empty)
    return "\n".join(lines)


def _source_lines(refs: tuple[str, ...], sources: list[dict[str, Any]]) -> list[str]:
    by_ref = {str(source.get("reference_id")): source for source in sources if source.get("reference_id")}
    lines: list[str] = []
    for reference in refs:
        if reference.startswith("TOOL:"):
            lines.append(f"数据工具：`{reference[5:]}`")
            continue
        source = by_ref.get(reference, {})
        description = " · ".join(
            str(value) for value in (source.get("source"), source.get("section")) if value
        )
        lines.append(f"[来源 {reference}]{(' ' + description) if description else ''}")
    return lines


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
        if not claim.evidence_refs or _overclaim(
            claim.statement,
            contract.allowed_conclusion_strength,
            contract.causal_claims_allowed,
        ):
            hypotheses.append(_Claim(claim.statement, claim.evidence_refs, "复核原始工具记录与同口径对照数据。"))
            moved += 1
        else:
            verified_facts.append(claim)
    facts = verified_facts

    retained_inferences: list[_Claim] = []
    for claim in inferences:
        if contract.allowed_conclusion_strength in {"insufficient", "hypothesis_only"} or _overclaim(
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
        adjustments.append(f"将 {moved} 条超出证据等级或缺少引用的声明降级为待验证假设。")

    submitted_conclusion = _clean_text(payload.get("conclusion"))
    if contract.allowed_conclusion_strength == "insufficient":
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

    submitted_limitations = [
        _clean_text(item, 1600) for item in payload.get("limitations", [])
        if _clean_text(item, 1600)
    ] if isinstance(payload.get("limitations"), list) else []
    limitations = list(dict.fromkeys([*contract.mandatory_limitations, *submitted_limitations]))
    supplied_sources = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []
    used_refs = {
        reference
        for claim in (*facts, *inferences, *hypotheses)
        for reference in claim.evidence_refs
    }
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
    source_lines = _source_lines(ordered_refs, sources or [])
    answer = "\n\n".join((
        f"## 结论\n{conclusion}",
        _render_section("已确认事实", fact_lines, "当前没有可通过有效引用独立确认的事实。"),
        _render_section("分析推断", inference_lines, "当前没有在证据等级内保留的分析推断。"),
        _render_section("待验证假设", hypothesis_lines, "当前没有额外的待验证假设。"),
        _render_section("建议", recommendation_lines, "先补齐证据缺口，再决定后续处置。"),
        _render_section("证据限制", limitations, "未识别到额外证据限制。"),
        _render_section("来源", source_lines, "本次结构化提交未引用可核验来源。"),
    ))
    report = AnswerSynthesisReport(
        schema_version="1.0",
        synthesizer_version=contract.synthesizer_version,
        plan_id=contract.plan_id,
        status=status,
        allowed_conclusion_strength=contract.allowed_conclusion_strength,
        sections=REQUIRED_SECTIONS,
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
    refs = [item for item in _embedded_refs(answer) if item.upper() in {
        allowed.upper() for allowed in contract.permitted_source_refs
    }]
    claim = {"statement": _SOURCE_PATTERN.sub("", answer), "evidence_refs": refs}
    low_strength = contract.allowed_conclusion_strength in {"insufficient", "hypothesis_only"}
    payload = {
        "conclusion": "",
        "facts": [],
        "inferences": [] if low_strength else [claim],
        "hypotheses": [{**claim, "verification": "按证据限制补充验证。"}] if low_strength else [],
        "recommendations": [],
        "limitations": ["模型未使用结构化提交，服务端已执行安全降级。"],
        "source_refs": refs,
    }
    return synthesize_submission(payload, contract, sources, status="repaired")
