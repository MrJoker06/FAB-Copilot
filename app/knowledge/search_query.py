"""Dependency-free query token helpers shared by factory-search adapters."""
from __future__ import annotations

import re

from ..manufacturing.processes import process_query_terms


def tokenize_query(text: str) -> list[str]:
    tokens = list(process_query_terms(text))
    for term in re.findall(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 4:
            tokens.extend(term[index:index + 3] for index in range(len(term) - 2))
        else:
            tokens.append(term)
    return list(dict.fromkeys(tokens))[:20]


def search_terms(text: str) -> list[str]:
    return tokenize_query(text)
