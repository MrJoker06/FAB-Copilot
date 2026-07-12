from __future__ import annotations

import re

from .database import db_session, rows_to_dicts


def _fts_query(text: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text)
    return " OR ".join(f'"{term}"' for term in terms[:12] if len(term) >= 3)


def _search_terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text)[:12]


def search_knowledge(query: str, limit: int = 5) -> list[dict]:
    """Search both governed knowledge and historical cases with auditable references."""
    fts_query = _fts_query(query)
    terms = _search_terms(query)
    if not terms:
        return []
    bounded_limit = max(1, min(limit, 10))
    with db_session() as connection:
        if fts_query:
            knowledge_rows = connection.execute(
                """SELECT 'knowledge' AS source_type,
                          'KB-' || k.chunk_id AS reference_id,
                          k.chunk_id, k.title, k.source, k.section,
                          snippet(knowledge_trigram_fts, 2, '[', ']', '…', 24) AS excerpt,
                          round(bm25(knowledge_trigram_fts), 4) AS score
                   FROM knowledge_trigram_fts
                   JOIN knowledge_chunks k ON k.chunk_id = knowledge_trigram_fts.rowid
                   WHERE knowledge_trigram_fts MATCH ?
                   ORDER BY bm25(knowledge_trigram_fts)
                   LIMIT ?""",
                (fts_query, bounded_limit),
            ).fetchall()
            case_rows = connection.execute(
                """SELECT 'case' AS source_type,
                          c.case_id AS reference_id,
                          c.case_id, c.title, '历史案例库' AS source,
                          c.title AS section,
                          snippet(case_trigram_fts, 3, '[', ']', '…', 24) AS excerpt,
                          round(bm25(case_trigram_fts), 4) AS score,
                          c.process_step, c.equipment_id, c.occurred_date, c.severity,
                          c.problem, c.solution, c.result, c.summary, c.tags
                   FROM case_trigram_fts
                   JOIN historical_cases c ON c.rowid = case_trigram_fts.rowid
                   WHERE case_trigram_fts MATCH ?
                   ORDER BY bm25(case_trigram_fts)
                   LIMIT ?""",
                (fts_query, bounded_limit),
            ).fetchall()
        else:
            pattern = f"%{terms[0]}%"
            knowledge_rows = connection.execute(
                """SELECT 'knowledge' AS source_type, 'KB-' || chunk_id AS reference_id,
                          chunk_id, title, source, section, content AS excerpt, -1.0 AS score
                   FROM knowledge_chunks
                   WHERE title LIKE ? OR section LIKE ? OR content LIKE ? LIMIT ?""",
                (pattern, pattern, pattern, bounded_limit),
            ).fetchall()
            case_rows = connection.execute(
                """SELECT 'case' AS source_type, case_id AS reference_id,
                          case_id, title, '历史案例库' AS source, title AS section,
                          problem AS excerpt, -1.0 AS score, process_step, equipment_id,
                          occurred_date, severity, problem, solution, result, summary, tags
                   FROM historical_cases
                   WHERE title LIKE ? OR problem LIKE ? OR solution LIKE ? OR summary LIKE ? OR tags LIKE ?
                   LIMIT ?""",
                (pattern, pattern, pattern, pattern, pattern, bounded_limit),
            ).fetchall()
    combined = rows_to_dicts(knowledge_rows) + rows_to_dicts(case_rows)
    combined.sort(key=lambda item: item.get("score", 0))
    return combined[:bounded_limit]


def list_knowledge_documents() -> list[dict]:
    with db_session() as connection:
        rows = connection.execute(
            """SELECT title, source, COUNT(*) AS section_count,
                      GROUP_CONCAT(section, ' · ') AS sections,
                      MIN(chunk_id) AS first_chunk_id
               FROM knowledge_chunks
               GROUP BY title, source
               ORDER BY source"""
        ).fetchall()
    return rows_to_dicts(rows)


def get_knowledge_document(chunk_id: int) -> dict:
    with db_session() as connection:
        selected = connection.execute(
            "SELECT chunk_id, title, source, section FROM knowledge_chunks WHERE chunk_id = ?",
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
                      severity, problem, summary, tags
               FROM historical_cases
               ORDER BY occurred_date DESC, case_id"""
        ).fetchall()
    return rows_to_dicts(rows)


def get_historical_case(case_id: str) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT case_id, title, process_step, equipment_id, occurred_date,
                      severity, problem, solution, result, summary, tags
               FROM historical_cases WHERE case_id = ?""",
            (case_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"历史案例不存在: {case_id}")
    return dict(row)
