"""SQLite demonstration adapter for governed factory knowledge retrieval."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..persistence.database import db_session, get_active_defect_aliases, rows_to_dicts
from .search_contracts import FactorySearchPrincipal, FactorySearchRequest
from .search_query import search_terms, tokenize_query


def sqlite_fts_query(text: str) -> str:
    """Translate portable query terms to the SQLite FTS syntax at this edge."""
    return " OR ".join(f'"{term}"' for term in tokenize_query(text) if len(term) >= 3)


class SqliteFactorySearchBackend:
    """Current local demo source; it deliberately has no production ACL claim."""

    def defect_aliases(self, principal: FactorySearchPrincipal) -> Mapping[str, Sequence[str]]:
        del principal
        return get_active_defect_aliases()

    def search(
        self,
        principal: FactorySearchPrincipal,
        request: FactorySearchRequest,
    ) -> list[dict]:
        del principal
        fts_query = sqlite_fts_query(request.raw_query)
        terms = search_terms(request.raw_query)
        if not terms:
            return []
        candidate_limit = request.candidate_limit
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
                       FROM knowledge.knowledge_trigram_fts
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
                       FROM knowledge.case_trigram_fts
                       JOIN knowledge.historical_cases c ON c.rowid = case_trigram_fts.rowid
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
        return [item for item in combined if item["source_type"] in request.source_types]

    def list_knowledge_documents(self, principal: FactorySearchPrincipal) -> list[dict]:
        del principal
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

    def get_knowledge_document(
        self, principal: FactorySearchPrincipal, chunk_id: int
    ) -> dict | None:
        del principal
        with db_session() as connection:
            selected = connection.execute(
                """SELECT k.chunk_id, k.title, k.source, k.section, d.doc_type, d.version,
                          d.status, d.effective_date, d.owner, d.authority, d.process_steps, d.tags
                   FROM knowledge_chunks k JOIN knowledge_documents d ON d.source = k.source
                   WHERE k.chunk_id = ? AND d.status = 'Active'""",
                (chunk_id,),
            ).fetchone()
            if selected is None:
                return None
            rows = connection.execute(
                """SELECT chunk_id, title, source, section, content
                   FROM knowledge_chunks WHERE source = ? ORDER BY chunk_id""",
                (selected["source"],),
            ).fetchall()
        return {"selected_chunk_id": chunk_id, "document": dict(selected), "chunks": rows_to_dicts(rows)}

    def list_historical_cases(self, principal: FactorySearchPrincipal) -> list[dict]:
        del principal
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

    def get_historical_case(
        self, principal: FactorySearchPrincipal, case_id: str
    ) -> dict | None:
        del principal
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
        return dict(row) if row is not None else None
