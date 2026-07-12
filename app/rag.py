from __future__ import annotations

import re

from .database import db_session, rows_to_dicts


def _fts_query(text: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text)
    return " OR ".join(f'"{term}"' for term in terms[:12])


def search_knowledge(query: str, limit: int = 5) -> list[dict]:
    """Search process knowledge with SQLite FTS5 and return auditable citations."""
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    with db_session() as connection:
        rows = connection.execute(
            """SELECT k.chunk_id, k.title, k.source, k.section,
                      snippet(knowledge_fts, 2, '[', ']', '…', 24) AS excerpt,
                      round(bm25(knowledge_fts), 4) AS score
               FROM knowledge_fts
               JOIN knowledge_chunks k ON k.chunk_id = knowledge_fts.rowid
               WHERE knowledge_fts MATCH ?
               ORDER BY bm25(knowledge_fts)
               LIMIT ?""",
            (fts_query, max(1, min(limit, 10))),
        ).fetchall()
    return rows_to_dicts(rows)
