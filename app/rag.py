from __future__ import annotations

import re
from datetime import date

from .database import db_session, rows_to_dicts


def _tokenize_query(text: str) -> list[str]:
    tokens: list[str] = []
    for term in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 4:
            tokens.extend(term[index:index + 3] for index in range(len(term) - 2))
        else:
            tokens.append(term)
    return list(dict.fromkeys(tokens))[:20]


def _fts_query(text: str) -> str:
    return " OR ".join(f'"{term}"' for term in _tokenize_query(text) if len(term) >= 3)


def _search_terms(text: str) -> list[str]:
    return _tokenize_query(text)


PROCESS_STEPS = ("CMP", "CVD", "ETCH", "LITHO", "METROLOGY", "EQUIPMENT", "WIP", "YIELD")
DEFECT_ALIASES = {
    "Scratch": ("scratch", "划伤"),
    "Thickness": ("thickness", "膜厚"),
    "Non-uniformity": ("non-uniformity", "uniformity", "均匀性", "不均匀"),
    "Particle": ("particle", "颗粒"),
    "Overlay": ("overlay", "套刻"),
    "Focus": ("focus", "焦距"),
    "CD Shift": ("cd shift", "cd偏移", "cd shift"),
    "Residue": ("residue", "残留"),
    "Dishing": ("dishing", "蝶形凹陷"),
    "Yield": ("yield", "良率"),
    "Cycle Time": ("cycle time", "周期时间"),
}


def _infer_filters(query: str, process_step: str | None, equipment_id: str | None, defect_type: str | None) -> dict:
    upper = query.upper()
    inferred_equipment = equipment_id.upper() if equipment_id else next(iter(re.findall(r"\b(?:CMP|CVD|ETCH|LITHO)-\d+\b", upper)), None)
    inferred_step = process_step.upper() if process_step else None
    if inferred_step is None and inferred_equipment:
        inferred_step = inferred_equipment.split("-", 1)[0]
    if inferred_step is None:
        inferred_step = next((step for step in PROCESS_STEPS if re.search(rf"\b{step}\b", upper)), None)
    lower = query.lower().replace(" ", "")
    inferred_defect = defect_type or next(
        (name for name, aliases in DEFECT_ALIASES.items() if any(alias.lower().replace(" ", "") in lower for alias in aliases)),
        None,
    )
    return {"process_step": inferred_step, "equipment_id": inferred_equipment, "defect_type": inferred_defect}


def _metadata_rerank(candidates: list[dict], filters: dict, limit: int, source_types: list[str] | None) -> list[dict]:
    allowed_sources = set(source_types or ("knowledge", "case"))
    ranked: list[dict] = []
    source_ranks = {"knowledge": 0, "case": 0}
    for candidate in candidates:
        source_type = candidate["source_type"]
        if source_type not in allowed_sources:
            continue
        source_ranks[source_type] += 1
        lexical_rank = source_ranks[source_type]
        score = 100.0 / (60 + lexical_rank)
        reasons = [f"{source_type} lexical rank {lexical_rank}"]
        process_step = filters.get("process_step")
        equipment_id = filters.get("equipment_id")
        defect_type = filters.get("defect_type")

        if source_type == "knowledge":
            steps = {item.strip() for item in candidate.get("process_steps", "").split(",")}
            if process_step and process_step not in steps and "ALL" not in steps:
                continue
            if process_step:
                score += 1.4
                reasons.append(f"process={process_step}")
            authority = int(candidate.get("authority", 0))
            score += authority * 0.12
            reasons.append(f"authority={authority}/5")
            searchable = f"{candidate.get('tags', '')} {candidate.get('title', '')} {candidate.get('section', '')}".lower()
            if defect_type and defect_type.lower() in searchable:
                score += 1.6
                reasons.append(f"defect={defect_type}")
        else:
            if candidate.get("case_status") != "Validated":
                continue
            candidate_step = candidate.get("process_step")
            family = candidate.get("equipment_family")
            if process_step and process_step not in {candidate_step, family} and family != "ALL":
                continue
            if process_step:
                score += 1.3
                reasons.append(f"process={process_step}")
            if equipment_id and candidate.get("equipment_id") == equipment_id:
                score += 2.2
                reasons.append("exact equipment")
            elif equipment_id and family == equipment_id.split("-", 1)[0]:
                score += 0.8
                reasons.append("equipment family")
            if defect_type and candidate.get("defect_type", "").lower() == defect_type.lower():
                score += 1.8
                reasons.append(f"defect={defect_type}")
            elif defect_type:
                continue
            confidence = float(candidate.get("root_cause_confidence", 0))
            score += confidence * 0.8
            reasons.append(f"validated confidence={confidence:.2f}")
            if not any((process_step, equipment_id, defect_type)):
                score -= 0.8
                reasons.append("no structured case match")
            try:
                age_days = (date.today() - date.fromisoformat(candidate["occurred_date"])).days
                recency = max(0.0, 1.0 - age_days / 730) * 0.25
                score += recency
            except (KeyError, ValueError):
                pass

        candidate["retrieval"] = {
            "lexical_rank": lexical_rank,
            "final_score": round(score, 4),
            "confidence": "high" if score >= 4.5 else ("medium" if score >= 2.0 else "low"),
            "selection_reason": reasons,
            "filters": filters,
        }
        ranked.append(candidate)

    ranked.sort(key=lambda item: item["retrieval"]["final_score"], reverse=True)
    selected: list[dict] = []
    if limit >= 2:
        for source_type in ("knowledge", "case"):
            first = next((item for item in ranked if item["source_type"] == source_type), None)
            if first is not None and first["retrieval"]["confidence"] != "low":
                selected.append(first)
    for item in ranked:
        if item not in selected:
            selected.append(item)
        if len(selected) >= limit:
            break
    selected.sort(key=lambda item: item["retrieval"]["final_score"], reverse=True)
    return selected[:limit]


def search_knowledge(
    query: str,
    limit: int = 5,
    process_step: str | None = None,
    equipment_id: str | None = None,
    defect_type: str | None = None,
    source_types: list[str] | None = None,
) -> list[dict]:
    """Search both governed knowledge and historical cases with auditable references."""
    fts_query = _fts_query(query)
    terms = _search_terms(query)
    if not terms:
        return []
    bounded_limit = max(1, min(limit, 10))
    candidate_limit = max(30, bounded_limit * 5)
    with db_session() as connection:
        if fts_query:
            knowledge_rows = connection.execute(
                """SELECT 'knowledge' AS source_type,
                          'KB-' || k.chunk_id AS reference_id,
                          k.chunk_id, k.title, k.source, k.section,
                          d.doc_type, d.version, d.status, d.effective_date,
                          d.owner, d.authority, d.process_steps, d.equipment_families, d.tags,
                          snippet(knowledge_trigram_fts, 2, '[', ']', '…', 24) AS excerpt,
                          round(bm25(knowledge_trigram_fts), 4) AS score
                   FROM knowledge_trigram_fts
                   JOIN knowledge_chunks k ON k.chunk_id = knowledge_trigram_fts.rowid
                   JOIN knowledge_documents d ON d.source = k.source AND d.status = 'Active'
                   WHERE knowledge_trigram_fts MATCH ?
                   ORDER BY bm25(knowledge_trigram_fts)
                   LIMIT ?""",
                (fts_query, candidate_limit),
            ).fetchall()
            case_rows = connection.execute(
                """SELECT 'case' AS source_type,
                          c.case_id AS reference_id,
                          c.case_id, c.title, '历史案例库' AS source,
                          c.title AS section,
                          snippet(case_trigram_fts, 3, '[', ']', '…', 24) AS excerpt,
                          round(bm25(case_trigram_fts), 4) AS score,
                          c.process_step, c.equipment_id, c.occurred_date, c.severity,
                          c.problem, c.solution, c.result, c.summary, c.tags,
                          c.equipment_family, c.defect_type, c.symptoms, c.root_cause,
                          c.root_cause_confidence, c.validation_method, c.recurrence_status,
                          c.approved_by, c.case_status
                   FROM case_trigram_fts
                   JOIN historical_cases c ON c.rowid = case_trigram_fts.rowid
                   WHERE case_trigram_fts MATCH ?
                   ORDER BY bm25(case_trigram_fts)
                   LIMIT ?""",
                (fts_query, candidate_limit),
            ).fetchall()
        else:
            pattern = f"%{terms[0]}%"
            knowledge_rows = connection.execute(
                """SELECT 'knowledge' AS source_type, 'KB-' || k.chunk_id AS reference_id,
                          k.chunk_id, k.title, k.source, k.section,
                          d.doc_type, d.version, d.status, d.effective_date, d.owner,
                          d.authority, d.process_steps, d.equipment_families, d.tags,
                          k.content AS excerpt, -1.0 AS score
                   FROM knowledge_chunks k JOIN knowledge_documents d ON d.source = k.source
                   WHERE d.status = 'Active' AND (k.title LIKE ? OR k.section LIKE ? OR k.content LIKE ?)
                   LIMIT ?""",
                (pattern, pattern, pattern, candidate_limit),
            ).fetchall()
            case_rows = connection.execute(
                """SELECT 'case' AS source_type, case_id AS reference_id,
                          case_id, title, '历史案例库' AS source, title AS section,
                          problem AS excerpt, -1.0 AS score, process_step, equipment_id,
                          occurred_date, severity, problem, solution, result, summary, tags,
                          equipment_family, defect_type, symptoms, root_cause,
                          root_cause_confidence, validation_method, recurrence_status,
                          approved_by, case_status
                   FROM historical_cases
                   WHERE title LIKE ? OR problem LIKE ? OR solution LIKE ? OR summary LIKE ? OR tags LIKE ?
                   LIMIT ?""",
                (pattern, pattern, pattern, pattern, pattern, candidate_limit),
            ).fetchall()
    combined = rows_to_dicts(knowledge_rows) + rows_to_dicts(case_rows)
    combined.sort(key=lambda item: item.get("score", 0))
    filters = _infer_filters(query, process_step, equipment_id, defect_type)
    return _metadata_rerank(combined, filters, bounded_limit, source_types)


def list_knowledge_documents() -> list[dict]:
    with db_session() as connection:
        rows = connection.execute(
            """SELECT d.title, d.source, d.doc_type, d.version, d.status,
                      d.effective_date, d.owner, d.authority, d.process_steps, d.tags,
                      COUNT(k.chunk_id) AS section_count,
                      GROUP_CONCAT(k.section, ' · ') AS sections,
                      MIN(k.chunk_id) AS first_chunk_id
               FROM knowledge_documents d
               JOIN knowledge_chunks k ON k.source = d.source
               WHERE d.status = 'Active'
               GROUP BY d.source
               ORDER BY d.source"""
        ).fetchall()
    return rows_to_dicts(rows)


def get_knowledge_document(chunk_id: int) -> dict:
    with db_session() as connection:
        selected = connection.execute(
            """SELECT k.chunk_id, k.title, k.source, k.section, d.doc_type, d.version,
                      d.status, d.effective_date, d.owner, d.authority, d.process_steps, d.tags
               FROM knowledge_chunks k JOIN knowledge_documents d ON d.source = k.source
               WHERE k.chunk_id = ?""",
            (chunk_id,),
        ).fetchone()
        if selected is None:
            raise ValueError(f"知识章节不存在: {chunk_id}")
        rows = connection.execute(
            """SELECT chunk_id, title, source, section, content
               FROM knowledge_chunks WHERE source = ? ORDER BY chunk_id""",
            (selected["source"],),
        ).fetchall()
    return {"selected_chunk_id": chunk_id, "document": dict(selected), "chunks": rows_to_dicts(rows)}


def list_historical_cases() -> list[dict]:
    with db_session() as connection:
        rows = connection.execute(
            """SELECT case_id, title, process_step, equipment_id, occurred_date,
                      severity, problem, summary, tags, equipment_family, defect_type,
                      root_cause_confidence, recurrence_status, case_status
               FROM historical_cases
               WHERE case_status = 'Validated'
               ORDER BY occurred_date DESC, case_id"""
        ).fetchall()
    return rows_to_dicts(rows)


def get_historical_case(case_id: str) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT case_id, title, process_step, equipment_id, occurred_date,
                      severity, problem, solution, result, summary, tags,
                      equipment_family, defect_type, symptoms, root_cause,
                      root_cause_confidence, validation_method, recurrence_status,
                      approved_by, case_status
               FROM historical_cases WHERE case_id = ? AND case_status = 'Validated'""",
            (case_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"历史案例不存在: {case_id}")
    return dict(row)
