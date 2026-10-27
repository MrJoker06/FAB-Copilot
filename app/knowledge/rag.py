from __future__ import annotations

import re
from collections.abc import Mapping

from ..core.settings import get_settings
from ..persistence.database import get_active_defect_aliases
from ..core.identity import current_principal
from ..personal_knowledge_runtime.service import search_personal_knowledge
from ..manufacturing.processes import (
    ANALYSIS_SCOPES,
    MANUFACTURING_STEPS,
    matched_process_step,
)
from .ranking import _metadata_rerank
from .search_contracts import (
    FactorySearchRequest,
    validate_factory_candidates,
    validate_historical_case,
    validate_historical_cases,
    validate_knowledge_document,
    validate_knowledge_documents,
)
from .search_query import search_terms as _portable_search_terms, tokenize_query as _portable_tokenize_query
from .search_registry import get_factory_catalog_backend, get_factory_search_backend
from .sqlite_backend import sqlite_fts_query


def _tokenize_query(text: str) -> list[str]:
    return _portable_tokenize_query(text)


def _fts_query(text: str) -> str:
    return sqlite_fts_query(text)


def _search_terms(text: str) -> list[str]:
    return _portable_search_terms(text)


PROCESS_STEPS = ANALYSIS_SCOPES

PROCESS_SEARCH_EXPANSIONS = {
    "LITHO": "photolithography lithography introduction intro overview purpose principle fundamentals basics process photoresist exposure reticle mask",
    "ETCH": "etch etching plasma dry etch wet etch reactive ion RIE",
    "CVD": "chemical vapor deposition CVD film thickness deposition",
    "PVD": "physical vapor deposition PVD sputter sputtering metal deposition",
    "DIFFUSION": "diffusion furnace oxidation anneal thermal process",
    "IMPLANT": "ion implantation implant dopant dose energy",
    "CMP": "chemical mechanical polishing planarization slurry pad conditioner",
    "CLEAN": "wet clean cleaning rinse scrubber chemical bath",
    "METROLOGY": "metrology measurement inspection CD SEM overlay thickness",
}


def _infer_filters_from_aliases(
    query: str,
    process_step: str | None,
    equipment_id: str | None,
    defect_type: str | None,
    defect_aliases: Mapping[str, object],
) -> dict:
    upper = query.upper()
    equipment_families = "|".join(re.escape(step) for step in MANUFACTURING_STEPS)
    inferred_equipment = equipment_id.upper() if equipment_id else next(iter(re.findall(rf"\b(?:{equipment_families})-\d+\b", upper)), None)
    inferred_step = process_step.upper() if process_step else None
    if inferred_step is None and inferred_equipment:
        inferred_step = inferred_equipment.split("-", 1)[0]
    if inferred_step is None:
        inferred_step = next((step for step in PROCESS_STEPS if re.search(rf"\b{step}\b", upper)), None)
    if inferred_step is None:
        inferred_step = matched_process_step(query)
    lower = query.lower().replace(" ", "")
    inferred_defect = defect_type or next(
        (name for name, aliases in defect_aliases.items()
         if any(alias.lower().replace(" ", "") in lower for alias in aliases)),
        None,
    )
    return {"process_step": inferred_step, "equipment_id": inferred_equipment, "defect_type": inferred_defect}


def _infer_filters(query: str, process_step: str | None, equipment_id: str | None, defect_type: str | None) -> dict:
    """Compatibility entry point for callers that patch local defect aliases."""
    return _infer_filters_from_aliases(
        query,
        process_step,
        equipment_id,
        defect_type,
        get_active_defect_aliases(),
    )


def search_knowledge(
    query: str,
    limit: int = 5,
    process_step: str | None = None,
    equipment_id: str | None = None,
    defect_type: str | None = None,
    source_types: list[str] | None = None,
    include_personal: bool = False,
    owner_user_id: str | None = None,
) -> list[dict]:
    """Search governed sources and optionally the current user's private knowledge."""
    # Preserve the legacy no-op path: blank or non-tokenizable input must not
    # instantiate an adapter, open SQLite, or contact an intranet backend.
    if not _search_terms(query):
        return []
    principal = current_principal()
    backend = get_factory_search_backend(get_settings().factory_search_backend)
    aliases = backend.defect_aliases(principal)
    if not isinstance(aliases, Mapping):
        raise ValueError("factory search backend must return defect aliases as a mapping")
    filters = _infer_filters_from_aliases(query, process_step, equipment_id, defect_type, aliases)
    enrichment = " ".join(str(value) for value in filters.values() if value)
    retrieval_query = f"{query} {enrichment}".strip()
    bounded_limit = max(1, min(limit, 10))
    candidate_limit = max(30, bounded_limit * 5)
    requested_sources = tuple(source for source in (source_types or ("knowledge", "case")) if source in {"knowledge", "case"})
    request = FactorySearchRequest(
        raw_query=retrieval_query,
        inferred_filters=filters,
        candidate_limit=candidate_limit,
        source_types=requested_sources or ("knowledge", "case"),
    )
    combined = validate_factory_candidates(backend.search(principal, request))
    if include_personal and (not source_types or "personal" in source_types):
        personal_owner = owner_user_id or get_settings().personal_knowledge_user_id
        process_expansion = PROCESS_SEARCH_EXPANSIONS.get(filters.get("process_step"), "")
        personal_query = f"{retrieval_query} {process_expansion}".strip()
        combined.extend(search_personal_knowledge(personal_owner, personal_query, candidate_limit))
    return _metadata_rerank(combined, filters, bounded_limit, source_types)


def search_agent_knowledge(
    query: str,
    limit: int = 5,
    process_step: str | None = None,
    equipment_id: str | None = None,
    defect_type: str | None = None,
    source_types: list[str] | None = None,
) -> list[dict]:
    return search_knowledge(
        query,
        limit,
        process_step,
        equipment_id,
        defect_type,
        source_types,
        include_personal=True,
        owner_user_id=current_principal().knowledge_owner_id,
    )


def list_knowledge_documents() -> list[dict]:
    backend = get_factory_catalog_backend(get_settings().factory_search_backend)
    return validate_knowledge_documents(backend.list_knowledge_documents(current_principal()))


def get_knowledge_document(chunk_id: int) -> dict:
    backend = get_factory_catalog_backend(get_settings().factory_search_backend)
    response = validate_knowledge_document(
        chunk_id, backend.get_knowledge_document(current_principal(), chunk_id)
    )
    if response is None:
        raise ValueError(f"知识章节不存在: {chunk_id}")
    return response


def list_historical_cases() -> list[dict]:
    backend = get_factory_catalog_backend(get_settings().factory_search_backend)
    return validate_historical_cases(backend.list_historical_cases(current_principal()))


def get_historical_case(case_id: str) -> dict:
    backend = get_factory_catalog_backend(get_settings().factory_search_backend)
    response = validate_historical_case(case_id, backend.get_historical_case(current_principal(), case_id))
    if response is None:
        raise ValueError(f"历史案例不存在: {case_id}")
    return response
