"""Bind a real Session and independent result store to one runtime invocation."""

from __future__ import annotations

import json
import threading
import weakref

from ..agent_runtime.result_access_run import ResultAccessRun
from ..conversation.result_lifecycle import session_results_permitted
from ..core.storage_identity_ports import storage_identity_bindings

def _verified(principal):
    return getattr(principal, "authentication_scheme", None) == "verified"


def _sources_allowed(principal, sources):
    from ..core.settings import get_settings
    from ..knowledge.search_contracts import factory_reference_allowed
    from ..knowledge.search_registry import get_factory_catalog_backend
    from ..personal_knowledge_runtime.service import get_personal_chunk

    if not isinstance(sources, list):
        return False
    name = get_settings().factory_search_backend
    backend = None
    for source in sources:
        if not isinstance(source, dict):
            return False
        source_type = source.get("source_type")
        if source_type == "personal":
            chunk = source.get("chunk_id")
            if not isinstance(chunk, str) or not get_personal_chunk(chunk, principal.knowledge_owner_id):
                return False
        elif source_type in {"knowledge", "case"} and name != "sqlite":
            if backend is None:
                backend = get_factory_catalog_backend(name)
            if not factory_reference_allowed(backend, principal, source):
                return False
    return True


def _tool_allowed(principal, tool):
    from .capability_catalog import tool_allowed

    return (
        isinstance(tool, str)
        and "analyst" in principal.roles
        and tool_allowed(tool, principal)
    )


def _access_claims(result):
    for entry in result.get("tool_trace") or ():
        yield {"tool": entry.get("tool")}
    if skill := result.get("skill_execution"):
        yield {"skill": skill["id"]}
    sources = list(result.get("sources") or ())
    if page := result.get("tool_result_page"):
        tool = page.get("tool")
        yield {"tool": tool}
        if tool == "search_knowledge":
            if page.get("format") != "units":
                yield {"unverifiable": True}
            else:
                sources.extend(page.get("units") or ())
    for source in sources:
        if source.get("source_type") in {"knowledge", "case", "personal"}:
            yield {"source": {
                key: source[key]
                for key in ("source_type", "reference_id", "chunk_id", "case_id")
                if key in source
            }}
    yield from result.get("context_access") or ()


def history_access_claims(principal, messages):
    """Carry reference identity forward when a new answer can use old evidence."""
    if not _verified(principal):
        return []
    claims = {}
    for message in messages:
        if message.get("role") == "assistant":
            for claim in _access_claims(message.get("metadata") or {}):
                claims[json.dumps(claim, sort_keys=True)] = claim
                if len(claims) > 100:
                    return [{"unverifiable": True}]
    return list(claims.values())


def saved_answer_allowed(principal, result):
    """Recheck persisted capability and citation access for verified callers."""
    if not _verified(principal):
        return True
    try:
        from .duty_chat_skill import require_skill

        claims = {
            json.dumps(claim, sort_keys=True): claim for claim in _access_claims(result)
        }.values()
        sources = []
        for claim in claims:
            if "tool" in claim:
                if not _tool_allowed(principal, claim["tool"]):
                    return False
            elif "skill" in claim:
                require_skill(principal, claim["skill"])
            elif "source" in claim:
                sources.append(claim["source"])
            else:
                return False
        return _sources_allowed(principal, sources)
    except Exception:  # noqa: BLE001 - missing sources and policy errors fail closed.
        return False


def filter_saved_history(principal, messages):
    return [
        item for item in messages
        if item.get("role") != "assistant" or saved_answer_allowed(principal, item.get("metadata") or {})
    ]


_active = weakref.WeakSet()
_active_lock = threading.Lock()


def cancel_session_result_runs(session_id, tenant_id, owner_id):
    # Cancellation improves local responsiveness; the durable intent and result
    # DB transaction remain the authority across processes and late callbacks.
    with _active_lock:
        runs = tuple(_active)
    for run in runs:
        if (
            run.session_id == session_id
            and run.principal.tenant_id == tenant_id
            and run.principal.user_id == owner_id
        ):
            run.cancel()


def make_result_access_run(session_id, run_id):
    bindings = storage_identity_bindings()
    principal = bindings.current_principal()

    def authorize():
        current = bindings.current_principal()
        return (
            "analyst" in current.roles
            and current.tenant_id == principal.tenant_id
            and current.user_id == principal.user_id
            and session_results_permitted(
                session_id, principal.tenant_id, principal.user_id
            )
        )

    def authorize_snapshot(metadata, content):
        current = bindings.current_principal()
        tool = metadata.get("tool")
        try:
            return _tool_allowed(current, tool) and (
                tool != "search_knowledge" or _sources_allowed(current, content)
            )
        except Exception:  # noqa: BLE001 - unverifiable stored data stays unavailable.
            return False

    reason = "NO_SESSION"
    store, enabled = None, False
    if session_id:
        reason = "RESULT_UNAVAILABLE"
        try:
            if authorize() and bindings.result_store_factory is not None:
                store = bindings.result_store_factory()
                enabled = store.enabled()
                reason = ""  # False here is an explicit persisted switch value.
        except Exception:  # noqa: BLE001 - backend setup failure is an explicit unavailable state
            reason = "RESULT_STORE_UNAVAILABLE"
    run = ResultAccessRun(
        session_id=session_id,
        run_id=run_id,
        principal=principal,
        store=store,
        enabled=enabled,
        authorize=authorize,
        unavailable_reason=reason,
        authorize_snapshot=authorize_snapshot if _verified(principal) else None,
    )
    with _active_lock:
        _active.add(run)
    return run
