from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..core.local_model_config import (
    get_local_model,
    remove_local_model,
    save_local_model,
    update_local_model_capabilities,
)
from ..core.model_capabilities import (
    MODEL_CAPABILITY_DEFAULTS,
    normalize_capabilities,
    normalize_capability_declaration,
    thinking_settings,
)
from ..core.model_credentials import credential_status, resolve_model_api_key
from ..core.settings import (
    ALLOWED_MODELS,
    MODEL_API_NAMES,
    ModelConnection,
    Settings,
    get_settings,
)
from ..core.storage_identity_ports import PrincipalView, storage_identity_bindings
from .health import ensure_model_health


MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$")
MODEL_PROVIDERS = {"deepseek", "openai-compatible"}


def db_session():
    return storage_identity_bindings().session_factory()


def current_principal() -> PrincipalView:
    return storage_identity_bindings().current_principal()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def ensure_model_catalog() -> None:
    settings = get_settings()
    timestamp = _now()
    rows = [
        (
            model_id,
            "DeepSeek V4 Flash" if model_id.endswith("flash") else "DeepSeek V4 Pro",
            "deepseek",
            MODEL_API_NAMES[model_id],
            settings.model_connection.base_url,
            "published",
            json.dumps(MODEL_CAPABILITY_DEFAULTS, separators=(",", ":")),
            "system",
            timestamp,
            timestamp,
            timestamp,
        )
        for model_id in ALLOWED_MODELS
    ]
    with db_session() as connection:
        existing = {
            row[0]
            for row in connection.execute("SELECT model_id FROM agent.model_catalog")
        }
        # Seed the built-ins only for an empty catalog.  An administrator may
        # intentionally delete one; it must not reappear on the next restart.
        if not existing:
            connection.executemany(
                """INSERT OR IGNORE INTO agent.model_catalog(
                       model_id, display_name, provider, provider_model, base_url, status,
                       capabilities_json, created_by, created_at, updated_at, published_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            existing = {row[0] for row in rows}
        for model_id, *_ in rows:
            if model_id in existing:
                ensure_model_health(model_id, connection)
        connection.commit()


def _decode_model(row) -> dict:
    item = dict(row)
    try:
        capabilities = json.loads(item.pop("capabilities_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        capabilities = {}
    item["capabilities"] = normalize_capabilities(capabilities)
    local = get_local_model(item.get("model_id", "")) if item.get("model_id") else None
    if local is not None:
        # Local models are file-backed: an operator can edit the JSON and the
        # next admin/user request sees the new values without a restart.
        for key in ("display_name", "provider", "provider_model", "base_url"):
            value = local.get(key)
            if isinstance(value, str) and value.strip():
                item[key] = value.strip().rstrip("/") if key == "base_url" else value.strip()
        item["capabilities"] = normalize_capabilities(local.get("capabilities"))
        item["config_source"] = "local_file"
    else:
        item["config_source"] = "database"
    try:
        item["compatibility"] = json.loads(item.pop("compatibility_json", "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        item["compatibility"] = {}
    item["compatibility_checked_at"] = item.get("compatibility_checked_at")
    item["health"] = {
        "status": item.pop("health_status", None) or "unknown",
        "consecutive_failures": int(item.pop("health_failures", 0) or 0),
        "opened_at": item.pop("health_opened_at", None),
        "open_until": item.pop("health_open_until", None),
        "last_success_at": item.pop("health_last_success_at", None),
        "last_failure_at": item.pop("health_last_failure_at", None),
        "last_error_category": item.pop("health_error_category", None),
    }
    item["selectable"] = item["status"] == "published"
    configured, source = (
        credential_status(item["model_id"], item["provider"])
        if item.get("model_id") and item.get("provider")
        else (False, "missing")
    )
    item["credential_configured"] = configured
    item["credential_source"] = source
    return item


def list_models(include_retired: bool = False) -> list[dict]:
    where = "" if include_retired else "WHERE m.status = 'published'"
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT m.*, COUNT(p.user_id) AS selected_user_count,
                       h.status AS health_status, h.consecutive_failures AS health_failures,
                       h.opened_at AS health_opened_at, h.open_until AS health_open_until,
                       h.last_success_at AS health_last_success_at, h.last_failure_at AS health_last_failure_at,
                       h.last_error_category AS health_error_category
                FROM model_catalog m
                LEFT JOIN model_health h ON h.model_id = m.model_id
                LEFT JOIN user_model_preferences p ON p.model_id = m.model_id
                {where}
                GROUP BY m.model_id
                ORDER BY CASE m.status WHEN 'published' THEN 0 ELSE 1 END,
                         m.published_at DESC, m.model_id"""
        ).fetchall()
    return [_decode_model(row) for row in rows]


def _selected_model(principal: PrincipalView) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT m.*, h.status AS health_status, h.consecutive_failures AS health_failures,
                      h.opened_at AS health_opened_at, h.open_until AS health_open_until,
                      h.last_success_at AS health_last_success_at, h.last_failure_at AS health_last_failure_at,
                      h.last_error_category AS health_error_category
               FROM user_model_preferences p
               JOIN model_catalog m ON m.model_id = p.model_id
               LEFT JOIN model_health h ON h.model_id = m.model_id
               WHERE p.tenant_id = ? AND p.user_id = ? AND m.status = 'published'""",
            (principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            configured = get_settings().model_connection.model
            row = connection.execute(
                """SELECT m.*, h.status AS health_status, h.consecutive_failures AS health_failures,
                          h.opened_at AS health_opened_at, h.open_until AS health_open_until,
                          h.last_success_at AS health_last_success_at, h.last_failure_at AS health_last_failure_at,
                          h.last_error_category AS health_error_category FROM model_catalog m
                   LEFT JOIN model_health h ON h.model_id = m.model_id
                   WHERE m.status = 'published'
                   ORDER BY CASE WHEN provider_model = ? THEN 0 ELSE 1 END,
                            published_at DESC, model_id
                   LIMIT 1""",
                (configured,),
            ).fetchone()
    if row is None:
        raise ValueError("当前没有已发布模型")
    return _decode_model(row)


def public_user_model_config(principal: PrincipalView | None = None) -> dict:
    principal = principal or current_principal()
    selected = _selected_model(principal)
    models = list_models()
    api_key_configured = bool(
        resolve_model_api_key(selected["model_id"], selected["provider"])
    )
    return {
        "model": selected["model_id"],
        "display_name": selected["display_name"],
        "provider": selected["provider"],
        "provider_model": selected["provider_model"],
        "base_url": selected["base_url"],
        "capabilities": selected["capabilities"],
        "thinking": thinking_settings(
            selected["capabilities"],
            provider=selected["provider"],
            provider_model=selected["provider_model"],
        ),
        "config_source": selected.get("config_source", "database"),
        "health": selected["health"],
        "allowed_models": [item["model_id"] for item in models],
        "model_options": [
            {
                "model_id": item["model_id"],
                "display_name": item["display_name"],
                "provider": item["provider"],
                "provider_model": item["provider_model"],
                "capabilities": item["capabilities"],
                "thinking": thinking_settings(
                    item["capabilities"],
                    provider=item["provider"],
                    provider_model=item["provider_model"],
                ),
                "config_source": item.get("config_source", "database"),
                "health": item["health"],
            }
            for item in models
        ],
        "api_key_configured": api_key_configured,
        "credential_scope": "server_managed",
        "persistence": "model_preference_database",
    }


def select_user_model(model_id: str, principal: PrincipalView | None = None) -> dict:
    principal = principal or current_principal()
    with db_session() as connection:
        exists = connection.execute(
            "SELECT 1 FROM model_catalog WHERE model_id = ? AND status = 'published'",
            (model_id,),
        ).fetchone()
        if exists is None:
            raise ValueError(f"模型未发布或不可用: {model_id}")
        connection.execute(
            """INSERT INTO agent.user_model_preferences(tenant_id, user_id, model_id, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(tenant_id, user_id) DO UPDATE SET
                   model_id = excluded.model_id, updated_at = excluded.updated_at""",
            (principal.tenant_id, principal.user_id, model_id, _now()),
        )
        ensure_model_health(model_id, connection)
        connection.commit()
    return public_user_model_config(principal)


def effective_agent_settings(settings):
    if not isinstance(settings, Settings):
        return settings
    principal = current_principal()
    selected = _selected_model(principal)
    return replace(
        settings,
        model_connection=ModelConnection(
            provider=selected["provider"],
            api_key=resolve_model_api_key(selected["model_id"], selected["provider"]),
            base_url=selected["base_url"].rstrip("/"),
            model=selected["provider_model"],
        ),
    )


def validate_model_definition(
    model_id: str, display_name: str, provider: str, provider_model: str, base_url: str,
    *, allow_retired_id: str | None = None,
) -> tuple[str, str, str, str]:
    """Pure/read-only publication validation; call before any upstream probe."""
    cleaned_model_id, cleaned_display_name = model_id.strip(), display_name.strip()
    cleaned_provider_model, cleaned_url = provider_model.strip(), base_url.strip().rstrip("/")
    if not MODEL_ID_PATTERN.fullmatch(cleaned_model_id): raise ValueError("模型编号格式不正确")
    if len(cleaned_display_name) < 2: raise ValueError("模型显示名称不能少于 2 个字符")
    if len(cleaned_provider_model) < 2: raise ValueError("Provider Model 不能少于 2 个字符")
    if provider not in MODEL_PROVIDERS: raise ValueError("不支持的模型提供方")
    if not cleaned_url.startswith(("https://", "http://")): raise ValueError("模型 API 地址必须使用 http:// 或 https://")
    with db_session() as connection:
        row = connection.execute("SELECT status FROM model_catalog WHERE model_id = ?", (cleaned_model_id,)).fetchone()
    if row is not None and cleaned_model_id != allow_retired_id: raise ValueError("模型编号已经存在")
    if allow_retired_id and (row is None or row["status"] != "retired"): raise ValueError("模型不存在或不是已停用状态")
    return cleaned_model_id, cleaned_display_name, cleaned_provider_model, cleaned_url


def _is_loopback_url(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def publish_model(
    model_id: str,
    display_name: str,
    provider: str,
    provider_model: str,
    base_url: str,
    capabilities: dict | None,
    created_by: str,
) -> dict:
    cleaned_model_id, cleaned_display_name, cleaned_provider_model, cleaned_url = validate_model_definition(model_id, display_name, provider, provider_model, base_url)
    timestamp = _now()
    declaration = normalize_capability_declaration(
        capabilities or {}, provider=provider, provider_model=cleaned_provider_model
    )
    compatibility = {
        "status": "unverified", "summary": "尚未进行兼容性测试"
    }
    with db_session() as connection:
        exists = connection.execute(
            "SELECT 1 FROM model_catalog WHERE model_id = ?",
            (cleaned_model_id,),
        ).fetchone()
        if exists is not None:
            raise ValueError("模型编号已经存在")
        connection.execute(
            """INSERT INTO agent.model_catalog(
                   model_id, display_name, provider, provider_model, base_url, status,
                   capabilities_json, compatibility_json, compatibility_checked_at, created_by, created_at, updated_at, published_at
               ) VALUES (?, ?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, ?, ?)""",
            (
                cleaned_model_id,
                cleaned_display_name,
                provider,
                cleaned_provider_model,
                cleaned_url,
                json.dumps(normalize_capabilities(declaration), separators=(",", ":")),
                json.dumps(compatibility or {}, separators=(",", ":")),
                (compatibility or {}).get("checked_at"),
                created_by,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM model_catalog WHERE model_id = ?",
            (cleaned_model_id,),
        ).fetchone()
    if cleaned_provider_model and provider == "openai-compatible" and _is_loopback_url(cleaned_url):
        save_local_model(
            cleaned_model_id,
            display_name=cleaned_display_name,
            provider=provider,
            provider_model=cleaned_provider_model,
            base_url=cleaned_url,
            capabilities=declaration,
        )
    return _decode_model(row)


def set_model_status(model_id: str, status: str) -> dict:
    if status not in {"published", "retired"}:
        raise ValueError("模型状态不正确")
    with db_session() as connection:
        if status == "retired":
            published_count = connection.execute(
                "SELECT COUNT(*) FROM model_catalog WHERE status = 'published'"
            ).fetchone()[0]
            current = connection.execute(
                "SELECT status FROM model_catalog WHERE model_id = ?", (model_id,)
            ).fetchone()
            if current is None:
                raise ValueError("模型不存在")
            if current["status"] == "published" and published_count <= 1:
                raise ValueError("至少保留一个已发布模型")
        timestamp = _now()
        cursor = connection.execute(
            """UPDATE agent.model_catalog
               SET status = ?, updated_at = ?,
                   published_at = CASE WHEN ? = 'published' THEN ? ELSE published_at END
               WHERE model_id = ? AND (? != 'published' OR status = 'retired')""",
            (status, timestamp, status, timestamp, model_id, status),
        )
        if cursor.rowcount == 0:
            raise ValueError("模型不存在或状态已变化")
        connection.commit()
        row = connection.execute("SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)).fetchone()
    return _decode_model(row)


def delete_model(model_id: str) -> dict:
    """Remove one catalog entry and every row that references it.

    The last published model is kept: deleting it would leave the application
    without any selectable model.  A retired model can always be deleted.
    """
    with db_session() as connection:
        row = connection.execute(
            "SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)
        ).fetchone()
        if row is None:
            raise ValueError("模型不存在")
        if row["status"] == "published":
            published_count = connection.execute(
                "SELECT COUNT(*) FROM model_catalog WHERE status = 'published'"
            ).fetchone()[0]
            if published_count <= 1:
                raise ValueError("至少保留一个已发布模型")
        connection.execute(
            "DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,)
        )
        connection.execute("DELETE FROM agent.model_health WHERE model_id = ?", (model_id,))
        deleted = connection.execute(
            "DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,)
        )
        if deleted.rowcount != 1:
            raise ValueError("模型不存在或状态已变化")
        connection.commit()
    remove_local_model(model_id)
    return _decode_model(row)


def update_model_capabilities(model_id: str, capabilities: dict) -> dict:
    """Persist the administrator's complete capability declaration without probing."""
    timestamp = _now()
    unverified = {"status": "unverified", "summary": "能力配置已变更，请按需重新测试"}
    with db_session() as connection:
        existing = connection.execute(
            "SELECT provider, provider_model FROM model_catalog WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        if existing is None:
            raise ValueError("模型不存在")
        declaration = normalize_capability_declaration(
            capabilities,
            provider=existing["provider"],
            provider_model=existing["provider_model"],
        )
        cursor = connection.execute(
            """UPDATE agent.model_catalog
               SET capabilities_json = ?, compatibility_json = ?, compatibility_checked_at = NULL,
                   updated_at = ? WHERE model_id = ?""",
            (json.dumps(declaration, separators=(",", ":")), json.dumps(unverified, separators=(",", ":")), timestamp, model_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("模型不存在")
        connection.commit()
        row = connection.execute("SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)).fetchone()
    update_local_model_capabilities(model_id, declaration)
    return _decode_model(row)


def invalidate_model_compatibility(
    model_id: str, summary: str = "凭据已更新，请重新测试兼容性"
) -> None:
    """Mark a stored probe stale after its credential changes."""
    timestamp = _now()
    unverified = {"status": "unverified", "summary": summary}
    with db_session() as connection:
        cursor = connection.execute(
            """UPDATE agent.model_catalog
               SET compatibility_json = ?, compatibility_checked_at = NULL,
                   updated_at = ?
               WHERE model_id = ?""",
            (
                json.dumps(unverified, separators=(",", ":")),
                timestamp,
                model_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("模型不存在")
        connection.commit()


def save_model_compatibility_report(model_id: str, report: dict) -> dict:
    """Store only an explicit, bounded probe result; never changes model state."""
    if not isinstance(report, dict) or report.get("status") not in {"passed", "failed"}:
        raise ValueError("兼容性报告格式不正确")
    timestamp = _now()
    checked_at = report.get("checked_at") if isinstance(report.get("checked_at"), str) else timestamp
    if report["status"] == "failed":
        # Failed reports are deliberately a small public-safe envelope: never retain
        # upstream response bodies, request data, or any accidental credential field.
        stored = {
            "status": "failed",
            "summary": str(report.get("summary") or "兼容性测试失败")[:500],
            "category": str(report.get("category") or "protocol")[:80],
            "retryable": bool(report.get("retryable")),
            "checked_at": checked_at,
        }
    else:
        stored = dict(report)
        stored["checked_at"] = checked_at
    with db_session() as connection:
        cursor = connection.execute(
            """UPDATE agent.model_catalog
               SET compatibility_json = ?, compatibility_checked_at = ?, updated_at = ?
               WHERE model_id = ?""",
            (json.dumps(stored, separators=(",", ":")), checked_at, timestamp, model_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("模型不存在")
        connection.commit()
        row = connection.execute("SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)).fetchone()
    return _decode_model(row)
