"""SQLite FTS-backed retrieval for personal knowledge."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from .contracts import PersonalKnowledgeError


class SearchDependencies(Protocol):
    db_session: object
    fts_query: object
    json_list: object


def fts_query(text: str, process_query_terms) -> str:
    terms = list(process_query_terms(text))
    for term in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 4:
            terms.extend(term[index:index + 3] for index in range(len(term) - 2))
        else:
            terms.append(term)
    unique = list(dict.fromkeys(term for term in terms if len(term) >= 3))[:20]
    return " OR ".join(f'"{term}"' for term in unique)


def search_knowledge(
    deps: SearchDependencies,
    owner_user_id: str,
    query: str,
    limit: int = 10,
    document_ids: Iterable[str] = (),
) -> list[dict]:
    bounded = max(1, min(limit, 20))
    selected_ids = list(dict.fromkeys(document_ids))[:100]
    clauses = ["f.owner_user_id = ?", "d.status = 'ready'"]
    params: list[object] = [owner_user_id]
    if selected_ids:
        placeholders = ", ".join("?" for _ in selected_ids)
        with deps.db_session() as connection:
            owned_count = connection.execute(
                f"""SELECT COUNT(*) FROM personal_knowledge_documents
                     WHERE owner_user_id = ? AND status = 'ready' AND document_id IN ({placeholders})""",
                [owner_user_id, *selected_ids],
            ).fetchone()[0]
        if owned_count != len(selected_ids):
            raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "指定文档不存在或尚未完成索引")
        clauses.append(f"f.document_id IN ({placeholders})")
        params.extend(selected_ids)
    query_for_fts = deps.fts_query(query)
    normalized_query = " ".join(query.casefold().split())
    tag_terms = list(dict.fromkeys([normalized_query, *(
        term.casefold() for term in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", query)
    )]))[:20]
    with deps.db_session() as connection:
        if tag_terms:
            tag_clauses = ["d.owner_user_id = ?", "d.status = 'ready'"]
            tag_params: list[object] = [owner_user_id]
            if selected_ids:
                placeholders = ", ".join("?" for _ in selected_ids)
                tag_clauses.append(f"d.document_id IN ({placeholders})")
                tag_params.extend(selected_ids)
            placeholders = ", ".join("?" for _ in tag_terms)
            tag_clauses.append(
                "EXISTS (SELECT 1 FROM json_each(d.tags_json) tag "
                f"WHERE LOWER(TRIM(tag.value)) IN ({placeholders}))"
            )
            tag_params.extend(tag_terms)
            tag_params.append(bounded)
            tag_rows = connection.execute(
                f"""SELECT c.chunk_id, c.document_id, d.title, c.section_path,
                           d.filename, d.process_steps_json, d.equipment_ids_json, d.tags_json, d.tags_source,
                           d.effective_date, c.page_number, c.content AS excerpt, -2.0 AS score
                    FROM personal_knowledge_documents d
                    JOIN personal_knowledge_chunks c ON c.chunk_id = (
                        SELECT c2.chunk_id FROM personal_knowledge_chunks c2
                        WHERE c2.document_id = d.document_id ORDER BY c2.chunk_index LIMIT 1
                    )
                    WHERE {' AND '.join(tag_clauses)}
                    ORDER BY d.updated_at DESC, d.document_id DESC LIMIT ?""",
                tag_params,
            ).fetchall()
        else:
            tag_rows = []
        if query_for_fts:
            rows = connection.execute(
                f"""SELECT f.chunk_id, f.document_id, f.title, f.section_path,
                           d.filename, d.process_steps_json, d.equipment_ids_json, d.tags_json, d.tags_source,
                           d.effective_date, c.page_number,
                           snippet(personal_knowledge_fts, 2, '[', ']', '…', 32) AS excerpt,
                           round(bm25(personal_knowledge_fts), 4) AS score
                    FROM knowledge.personal_knowledge_fts f
                    JOIN personal_knowledge_chunks c ON c.chunk_id = f.chunk_id
                    JOIN personal_knowledge_documents d ON d.document_id = f.document_id
                    WHERE personal_knowledge_fts MATCH ? AND {' AND '.join(clauses)}
                    ORDER BY bm25(personal_knowledge_fts) LIMIT ?""",
                [query_for_fts, *params, bounded * 2],
            ).fetchall()
        else:
            fallback_clauses = ["c.owner_user_id = ?", "d.status = 'ready'", "c.content LIKE ?"]
            fallback_params: list[object] = [owner_user_id, f"%{query.strip()}%"]
            if selected_ids:
                placeholders = ", ".join("?" for _ in selected_ids)
                fallback_clauses.append(f"c.document_id IN ({placeholders})")
                fallback_params.extend(selected_ids)
            fallback_params.append(bounded * 2)
            rows = connection.execute(
                f"""SELECT c.chunk_id, c.document_id, d.title, c.section_path,
                           d.filename, d.process_steps_json, d.equipment_ids_json, d.tags_json, d.tags_source,
                           d.effective_date, c.page_number, c.content AS excerpt, -1.0 AS score
                    FROM personal_knowledge_chunks c
                    JOIN personal_knowledge_documents d ON d.document_id = c.document_id
                    WHERE {' AND '.join(fallback_clauses)}
                    ORDER BY c.chunk_index LIMIT ?""",
                fallback_params,
            ).fetchall()
    seen_document_ids = {row["document_id"] for row in tag_rows}
    rows = (list(tag_rows) + [row for row in rows if row["document_id"] not in seen_document_ids])[:bounded]
    results = []
    for rank, row in enumerate(rows, start=1):
        item = dict(row)
        item["process_steps"] = deps.json_list(item.pop("process_steps_json", "[]"))
        item["equipment_ids"] = deps.json_list(item.pop("equipment_ids_json", "[]"))
        item["tags"] = deps.json_list(item.pop("tags_json", "[]"))
        item.update({
            "reference_id": f"PERSONAL-{item['chunk_id']}",
            "source_type": "personal",
            "source": "个人知识库",
            "section": item["section_path"],
            "retrieval": {
                "lexical_rank": rank,
                "final_score": item.pop("score"),
                "selection_reason": ["当前用户个人知识", f"lexical rank {rank}"],
            },
        })
        results.append(item)
    return results


def get_chunk(deps: SearchDependencies, chunk_id: str, owner_user_id: str) -> dict:
    with deps.db_session() as connection:
        row = connection.execute(
            """SELECT c.chunk_id, c.document_id, d.title, d.filename, c.page_number,
                      c.section_path, c.chunk_index, c.content, c.token_count
               FROM personal_knowledge_chunks c
               JOIN personal_knowledge_documents d ON d.document_id = c.document_id
               WHERE c.chunk_id = ? AND c.owner_user_id = ? AND d.status = 'ready'""",
            (chunk_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise PersonalKnowledgeError(404, "DOCUMENT_NOT_FOUND", "个人知识章节不存在")
    return dict(row)
