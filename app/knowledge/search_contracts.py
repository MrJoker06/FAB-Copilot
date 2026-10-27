"""Portable contracts for governed factory knowledge and case retrieval.

This module intentionally contains no application configuration, identity,
database, or transport dependency.  An intranet search adapter receives the
minimal principal and request shapes declared here and is responsible for its
own access-control enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


FACTORY_SOURCE_TYPES = frozenset({"knowledge", "case"})
MAX_CANDIDATE_LIMIT = 50


class FactorySearchPrincipal(Protocol):
    """Identity fields supplied to a factory search adapter."""

    @property
    def tenant_id(self) -> str: ...

    @property
    def user_id(self) -> str: ...

    @property
    def roles(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class FactorySearchRequest:
    """Read-only retrieval input that is independent of any query language."""

    raw_query: str
    inferred_filters: Mapping[str, str | None]
    candidate_limit: int
    source_types: tuple[str, ...] = ("knowledge", "case")

    def __post_init__(self) -> None:
        if not isinstance(self.raw_query, str) or not self.raw_query.strip():
            raise ValueError("factory search raw_query must be non-empty")
        if not isinstance(self.candidate_limit, int) or isinstance(self.candidate_limit, bool):
            raise ValueError("factory search candidate_limit must be an integer")
        if not 1 <= self.candidate_limit <= MAX_CANDIDATE_LIMIT:
            raise ValueError(f"factory search candidate_limit must be between 1 and {MAX_CANDIDATE_LIMIT}")
        if not self.source_types or any(source not in FACTORY_SOURCE_TYPES for source in self.source_types):
            raise ValueError("factory search source_types must contain only knowledge or case")


class FactorySearchBackend(Protocol):
    """Adapter boundary for governed factory knowledge and historical cases."""

    def defect_aliases(self, principal: FactorySearchPrincipal) -> Mapping[str, Sequence[str]]: ...

    def search(
        self,
        principal: FactorySearchPrincipal,
        request: FactorySearchRequest,
    ) -> Sequence[Mapping[str, object]]: ...


class FactoryCatalogBackend(Protocol):
    """Adapter boundary for factory knowledge and case catalogue browsing."""

    def list_knowledge_documents(self, principal: FactorySearchPrincipal) -> Sequence[Mapping[str, object]]: ...

    def get_knowledge_document(
        self, principal: FactorySearchPrincipal, chunk_id: int
    ) -> Mapping[str, object] | None: ...

    def list_historical_cases(self, principal: FactorySearchPrincipal) -> Sequence[Mapping[str, object]]: ...

    def get_historical_case(
        self, principal: FactorySearchPrincipal, case_id: str
    ) -> Mapping[str, object] | None: ...


class FactoryCatalogResponseError(RuntimeError):
    """A configured catalogue adapter returned an unsafe response.

    This deliberately is not a ``ValueError``: legacy API routes translate
    ``ValueError`` only for genuinely missing documents/cases into HTTP 404.
    """


def _catalog_error(message: str) -> FactoryCatalogResponseError:
    return FactoryCatalogResponseError(f"factory catalog backend {message}")


def _catalog_rows(rows: object, *, kind: str) -> list[dict]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise _catalog_error(f"must return a sequence of {kind} rows")
    validated: list[dict] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise _catalog_error(f"returned a non-mapping {kind} row")
        validated.append(dict(row))
    return validated


def _positive_chunk_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_knowledge_documents(rows: object) -> list[dict]:
    """Validate active document-list rows without prescribing extra metadata."""
    validated = _catalog_rows(rows, kind="knowledge document")
    for row in validated:
        if row.get("status") != "Active":
            raise _catalog_error("knowledge document rows must have status Active")
        if not isinstance(row.get("source"), str) or not row["source"].strip():
            raise _catalog_error("knowledge document rows must have a non-empty source")
        if not _positive_chunk_id(row.get("first_chunk_id")):
            raise _catalog_error("knowledge document rows must have a positive integer first_chunk_id")
    return validated


def validate_knowledge_document(chunk_id: int, response: object) -> dict | None:
    """Validate a detail response and its document/chunk source relationship."""
    if response is None:
        return None
    if not isinstance(response, Mapping):
        raise _catalog_error("must return a mapping knowledge document detail")
    selected_chunk_id = response.get("selected_chunk_id")
    document = response.get("document")
    chunks = response.get("chunks")
    if not _positive_chunk_id(selected_chunk_id) or selected_chunk_id != chunk_id:
        raise _catalog_error("knowledge document selected_chunk_id does not match request")
    if not isinstance(document, Mapping):
        raise _catalog_error("knowledge document detail must contain a document mapping")
    if document.get("status") != "Active":
        raise _catalog_error("knowledge document detail must have status Active")
    if not _positive_chunk_id(document.get("chunk_id")) or document["chunk_id"] != chunk_id:
        raise _catalog_error("knowledge document detail chunk_id does not match request")
    source = document.get("source")
    if not isinstance(source, str) or not source.strip():
        raise _catalog_error("knowledge document detail must have a non-empty source")
    validated_chunks = _catalog_rows(chunks, kind="knowledge chunk")
    if not validated_chunks:
        raise _catalog_error("knowledge document detail must contain chunks")
    selected_seen = False
    for chunk in validated_chunks:
        if chunk.get("source") != source:
            raise _catalog_error("knowledge chunks must match the document source")
        if not _positive_chunk_id(chunk.get("chunk_id")):
            raise _catalog_error("knowledge chunks must have positive integer chunk_id values")
        if not isinstance(chunk.get("content"), str):
            raise _catalog_error("knowledge chunks must have string content")
        selected_seen = selected_seen or chunk["chunk_id"] == chunk_id
    if not selected_seen:
        raise _catalog_error("knowledge chunks must include the selected chunk")
    return {"selected_chunk_id": chunk_id, "document": dict(document), "chunks": validated_chunks}


def validate_historical_cases(rows: object) -> list[dict]:
    """Validate list rows and prevent unvalidated cases leaking through an adapter."""
    validated = _catalog_rows(rows, kind="historical case")
    for row in validated:
        if row.get("case_status") != "Validated":
            raise _catalog_error("historical case rows must have case_status Validated")
        if not isinstance(row.get("case_id"), str) or not row["case_id"].strip():
            raise _catalog_error("historical case rows must have a non-empty case_id")
    return validated


def validate_historical_case(case_id: str, response: object) -> dict | None:
    if response is None:
        return None
    if not isinstance(response, Mapping):
        raise _catalog_error("must return a mapping historical case detail")
    if response.get("case_id") != case_id:
        raise _catalog_error("historical case case_id does not match request")
    if response.get("case_status") != "Validated":
        raise _catalog_error("historical case detail must have case_status Validated")
    return dict(response)


def validate_factory_candidates(candidates: object) -> list[dict]:
    """Return safely copied candidates or reject malformed adapter output.

    The application fail-closes on a bad adapter response rather than mixing
    it with SQLite demo data.  Ranking needs dictionaries, a supported source
    type, and a stable reference identifier; other metadata remains adapter
    defined so company deployments can enrich it.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("factory search backend must return a sequence of candidates")
    validated: list[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("factory search backend returned a non-mapping candidate")
        source_type = candidate.get("source_type")
        reference_id = candidate.get("reference_id")
        if source_type not in FACTORY_SOURCE_TYPES:
            raise ValueError("factory search candidate has an unsupported source_type")
        if not isinstance(reference_id, str) or not reference_id.strip():
            raise ValueError("factory search candidate must have a non-empty reference_id")
        if source_type == "knowledge" and candidate.get("status") != "Active":
            raise ValueError("factory search knowledge candidate must have status Active")
        if source_type == "case" and candidate.get("case_status") != "Validated":
            raise ValueError("factory search case candidate must have case_status Validated")
        validated.append(dict(candidate))
    return validated
