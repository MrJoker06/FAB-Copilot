"""Unregistered native definition for bounded knowledge retrieval."""

from __future__ import annotations

from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolScope
from app.agent_runtime.tools.definition import (
    ToolBinding,
    ToolDefinition,
    ToolPreparation,
)
from app.knowledge.search_query import search_terms
from app.tools.knowledge_search.contracts import (
    KNOWLEDGE_SEARCH_OUTPUT_SCHEMA,
    KnowledgeSearchInput,
    KnowledgeSearchPort,
    knowledge_scope,
    validate_knowledge_search_output,
)
from app.tools.knowledge_search.handler import KnowledgeSearchDependencies, knowledge_search_handler

KNOWLEDGE_SEARCH_DEFINITION = ToolDefinition(
    "search_knowledge",
    "1.0.0",
    "检索当前用户个人知识、厂内知识与已验证历史案例",
    KnowledgeSearchInput,
    validate_knowledge_search_output,
    title="知识与案例检索",
    output_schema=KNOWLEDGE_SEARCH_OUTPUT_SCHEMA,
)


def _prepare(
    value: KnowledgeSearchInput,
    context: ToolExecutionContext[KnowledgeSearchDependencies],
) -> ToolPreparation[KnowledgeSearchInput]:
    # Dispatcher accepts a successful empty result without provenance only for
    # its bare tenant scope. A tokenless query contacts no source by contract.
    scope = (
        knowledge_scope(context.principal)
        if search_terms(value.query)
        else ToolScope(context.principal.tenant_id)
    )
    return ToolPreparation(value, scope)


def create_knowledge_search_binding(
    port: KnowledgeSearchPort, *, default_tenant_id: str
) -> ToolBinding[KnowledgeSearchInput, KnowledgeSearchDependencies, object]:
    return ToolBinding(
        KNOWLEDGE_SEARCH_DEFINITION,
        knowledge_search_handler,
        KnowledgeSearchDependencies(port, default_tenant_id),
        _prepare,
    )
