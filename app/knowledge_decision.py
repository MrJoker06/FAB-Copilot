from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

RetrievalState = Literal[
    "GROUND_PERSONAL",
    "GROUND_FACTORY",
    "GROUND_MIXED",
    "HYBRID_GENERAL_SUPPLEMENT",
    "MODEL_ONLY_FALLBACK",
]

HYBRID_DISCLOSURE = (
    "知识库只检索到部分相关内容。回答中引用部分来自知识库，"
    "其余为模型通用知识补充，不代表厂内 SOP、规格或当前生产事实。"
)
MODEL_ONLY_DISCLOSURE = (
    "个人知识库和工厂知识库均未检索到可用内容。以下回答使用模型通用知识，仅供参考，"
    "不代表厂内 SOP、规格或当前生产事实。"
)

_GENERIC_TERMS = {
    "sop", "规范", "知识", "案例", "查询", "检索", "分析", "说明", "介绍",
    "工艺", "技术", "器件", "差异", "区别", "原理", "基础", "相关", "资料", "文档",
}
_CASE_PATTERN = re.compile(r"(?:故障|异常|失效|根因|原因|解决|处置|案例|经验|复发|改善)")


@dataclass(frozen=True)
class QueryRewrite:
    query: str
    changed: bool
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalDecision:
    state: RetrievalState
    reason: str
    attempted_scopes: tuple[str, ...]
    attempts: tuple[dict[str, Any], ...]
    selected_reference_ids: tuple[str, ...]
    source_counts: dict[str, int]
    rewritten_query: str | None
    assumptions: tuple[str, ...]
    model_knowledge_allowed: bool
    disclosure: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "attempted_scopes": list(self.attempted_scopes),
            "attempts": list(self.attempts),
            "selected_reference_ids": list(self.selected_reference_ids),
            "source_counts": self.source_counts,
            "rewritten_query": self.rewritten_query,
            "assumptions": list(self.assumptions),
            "model_knowledge_allowed": self.model_knowledge_allowed,
            "disclosure": self.disclosure,
        }


def required_scopes(question: str) -> tuple[str, ...]:
    scopes = ["personal", "knowledge"]
    if _CASE_PATTERN.search(question):
        scopes.append("case")
    return tuple(scopes)


def rewrite_query(question: str) -> QueryRewrite:
    rewritten = re.sub(r"(?i)(?<![A-Za-z0-9])gan(?![A-Za-z0-9])", "GaN", question)
    assumptions: list[str] = []
    si_pattern = re.compile(r"(?i)(?<![A-Za-z0-9])s(?=\s*器件)")
    if si_pattern.search(rewritten):
        rewritten = si_pattern.sub("Si", rewritten)
        assumptions.append("暂按 S 器件指 Si（硅）器件理解")
    rewritten = " ".join(rewritten.split())
    return QueryRewrite(rewritten, rewritten != " ".join(question.split()), tuple(assumptions))


def knowledge_anchor_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", query.lower()):
        candidates = (
            [token[index:index + 3] for index in range(len(token) - 2)]
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 4
            else [token]
        )
        terms.extend(item for item in candidates if len(item) >= 2 and item not in _GENERIC_TERMS)
    return tuple(dict.fromkeys(terms))


def usable_result(query: str, result: dict[str, Any]) -> bool:
    retrieval = result.get("retrieval") or {}
    confidence = str(retrieval.get("confidence") or "").lower()
    if confidence == "low":
        return False
    if confidence == "high" or not confidence:
        return True

    filters = retrieval.get("filters") or {}
    process_step = str(filters.get("process_step") or "").upper()
    candidate_steps = result.get("process_steps") or result.get("process_step") or []
    if isinstance(candidate_steps, str):
        candidate_steps = re.split(r"[,|\s]+", candidate_steps.upper())
    if process_step and process_step in set(candidate_steps):
        return True

    searchable = " ".join(
        str(result.get(field) or "")
        for field in (
            "title", "source", "section", "content", "excerpt", "tags",
            "problem", "solution", "result", "summary",
        )
    ).lower()
    anchors = knowledge_anchor_terms(query)
    return bool(anchors and any(term in searchable for term in anchors))


def assess_retrieval(
    attempts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    rewrite: QueryRewrite,
) -> RetrievalDecision:
    unique_sources = {
        str(item.get("reference_id")): item
        for item in sources
        if item.get("reference_id")
    }
    selected = list(unique_sources.values())
    source_counts = {
        source_type: sum(1 for item in selected if item.get("source_type") == source_type)
        for source_type in ("personal", "knowledge", "case")
    }
    confidences = [
        str((item.get("retrieval") or {}).get("confidence") or "high").lower()
        for item in selected
    ]
    has_strong_grounding = "high" in confidences or sum(value == "medium" for value in confidences) >= 2
    has_errors = any(item.get("status") != "success" for item in attempts)

    if not selected:
        state: RetrievalState = "MODEL_ONLY_FALLBACK"
        reason = (
            "search_unavailable"
            if has_errors
            else "all_scopes_empty_after_rewrite"
            if rewrite.changed
            else "all_scopes_empty"
        )
        model_allowed = True
        disclosure = MODEL_ONLY_DISCLOSURE
    elif not has_strong_grounding or has_errors:
        state = "HYBRID_GENERAL_SUPPLEMENT"
        reason = "partial_evidence" if not has_errors else "partial_evidence_with_search_error"
        model_allowed = True
        disclosure = HYBRID_DISCLOSURE
    else:
        populated = {key for key, value in source_counts.items() if value}
        if populated == {"personal"}:
            state = "GROUND_PERSONAL"
        elif "personal" in populated:
            state = "GROUND_MIXED"
        else:
            state = "GROUND_FACTORY"
        reason = "usable_grounding_found"
        model_allowed = False
        disclosure = None

    return RetrievalDecision(
        state=state,
        reason=reason,
        attempted_scopes=tuple(dict.fromkeys(str(item.get("scope")) for item in attempts)),
        attempts=tuple(attempts),
        selected_reference_ids=tuple(unique_sources),
        source_counts=source_counts,
        rewritten_query=rewrite.query if rewrite.changed else None,
        assumptions=rewrite.assumptions,
        model_knowledge_allowed=model_allowed,
        disclosure=disclosure,
    )


def retrieval_system_message(decision: RetrievalDecision, sources: list[dict[str, Any]]) -> str:
    selected = set(decision.selected_reference_ids)
    compact_sources = [{
        "reference_id": source.get("reference_id"),
        "source_type": source.get("source_type"),
        "title": source.get("title"),
        "section": source.get("section"),
        "excerpt": source.get("excerpt") or source.get("content") or source.get("problem"),
        "version": source.get("version"),
        "status": source.get("status") or source.get("case_status"),
        "retrieval": source.get("retrieval"),
    } for source in sources if source.get("reference_id") in selected]
    payload = {"decision": decision.to_dict(), "sources": compact_sources}
    return (
        "以下是服务端确定性知识检索与降级判定，不是隐藏思维链。"
        "个人知识已按当前用户隔离检索，工厂知识单独检索。"
        "有来源时应优先基于来源回答并使用 [来源 reference_id] 引用；"
        "只有 model_knowledge_allowed=true 时才可补充模型通用知识，并必须遵守 disclosure。"
        "若 assumptions 非空，在答案开头简短说明假设并允许用户纠正；不得索要无关的设备、批次或日期。\n"
        f"knowledge_retrieval={json.dumps(payload, ensure_ascii=False, default=str)}"
    )
