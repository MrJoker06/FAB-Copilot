from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from datetime import datetime, timezone

from .config import ALLOWED_MODELS, MODEL_API_NAMES, Settings, get_settings
from .database import db_session
from .identity import Principal, current_principal


MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$")
MODEL_PROVIDERS = {"deepseek", "openai-compatible"}
_key_lock = threading.Lock()
_user_api_keys: dict[tuple[str, str], str] = {}


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
            settings.deepseek_base_url,
            "published",
            json.dumps({"streaming": True, "tool_calls": True}, separators=(",", ":")),
            "system",
            timestamp,
            timestamp,
            timestamp,
        )
        for model_id in ALLOWED_MODELS
    ]
    with db_session() as connection:
        connection.executemany(
            """INSERT OR IGNORE INTO agent.model_catalog(
                   model_id, display_name, provider, provider_model, base_url, status,
                   capabilities_json, created_by, created_at, updated_at, published_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        connection.commit()


def _decode_model(row) -> dict:
    item = dict(row)
    try:
        item["capabilities"] = json.loads(item.pop("capabilities_json") or "{}")
    except json.JSONDecodeError:
        item["capabilities"] = {}
    item["selectable"] = item["status"] == "published"
    return item


def list_models(include_retired: bool = False) -> list[dict]:
    where = "" if include_retired else "WHERE m.status = 'published'"
    with db_session() as connection:
        rows = connection.execute(
            f"""SELECT m.*, COUNT(p.user_id) AS selected_user_count
                FROM model_catalog m
                LEFT JOIN user_model_preferences p ON p.model_id = m.model_id
                {where}
                GROUP BY m.model_id
                ORDER BY CASE m.status WHEN 'published' THEN 0 ELSE 1 END,
                         m.published_at DESC, m.model_id"""
        ).fetchall()
    return [_decode_model(row) for row in rows]


def _selected_model(principal: Principal) -> dict:
    with db_session() as connection:
        row = connection.execute(
            """SELECT m.* FROM user_model_preferences p
               JOIN model_catalog m ON m.model_id = p.model_id
               WHERE p.tenant_id = ? AND p.user_id = ? AND m.status = 'published'""",
            (principal.tenant_id, principal.user_id),
        ).fetchone()
        if row is None:
            configured = get_settings().deepseek_model
            row = connection.execute(
                """SELECT * FROM model_catalog
                   WHERE status = 'published'
                   ORDER BY CASE WHEN provider_model = ? THEN 0 ELSE 1 END,
                            published_at DESC, model_id
                   LIMIT 1""",
                (configured,),
            ).fetchone()
    if row is None:
        raise ValueError("当前没有已发布模型")
    return _decode_model(row)


def _runtime_api_key(principal: Principal) -> tuple[str, str]:
    with _key_lock:
        key = _user_api_keys.get((principal.tenant_id, principal.user_id), "")
    if key:
        return key, "user_runtime"
    environment_key = get_settings().deepseek_api_key
    return environment_key, "environment" if environment_key else "none"


def public_user_model_config(principal: Principal | None = None) -> dict:
    principal = principal or current_principal()
    selected = _selected_model(principal)
    models = list_models()
    api_key, key_source = _runtime_api_key(principal)
    return {
        "model": selected["model_id"],
        "display_name": selected["display_name"],
        "provider": selected["provider"],
        "provider_model": selected["provider_model"],
        "base_url": selected["base_url"],
        "allowed_models": [item["model_id"] for item in models],
        "model_options": [
            {
                "model_id": item["model_id"],
                "display_name": item["display_name"],
                "provider": item["provider"],
                "provider_model": item["provider_model"],
                "capabilities": item["capabilities"],
            }
            for item in models
        ],
        "api_key_configured": bool(api_key),
        "api_key_masked": f"••••••••{api_key[-4:]}" if len(api_key) >= 4 else "",
        "api_key_source": key_source,
        "persistence": "model_preference_database_api_key_process_memory",
    }


def select_user_model(model_id: str, api_key: str | None = None, principal: Principal | None = None) -> dict:
    principal = principal or current_principal()
    cleaned_key = api_key.strip() if api_key is not None else None
    if cleaned_key is not None and cleaned_key and len(cleaned_key) < 8:
        raise ValueError("API Key 长度不能少于 8 个字符")
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
        connection.commit()
    if cleaned_key:
        with _key_lock:
            _user_api_keys[(principal.tenant_id, principal.user_id)] = cleaned_key
    return public_user_model_config(principal)


def effective_agent_settings(settings):
    if not isinstance(settings, Settings):
        return settings
    principal = current_principal()
    selected = _selected_model(principal)
    api_key, _ = _runtime_api_key(principal)
    return replace(
        settings,
        deepseek_api_key=api_key,
        deepseek_base_url=selected["base_url"].rstrip("/"),
        deepseek_model=selected["provider_model"],
    )


def publish_model(
    model_id: str,
    display_name: str,
    provider: str,
    provider_model: str,
    base_url: str,
    capabilities: dict | None,
    created_by: str,
) -> dict:
    cleaned_model_id = model_id.strip()
    cleaned_display_name = display_name.strip()
    cleaned_provider_model = provider_model.strip()
    if not MODEL_ID_PATTERN.fullmatch(cleaned_model_id):
        raise ValueError("模型编号格式不正确")
    if len(cleaned_display_name) < 2:
        raise ValueError("模型显示名称不能少于 2 个字符")
    if len(cleaned_provider_model) < 2:
        raise ValueError("Provider Model 不能少于 2 个字符")
    if provider not in MODEL_PROVIDERS:
        raise ValueError("不支持的模型提供方")
    cleaned_url = base_url.strip().rstrip("/")
    if not cleaned_url.startswith(("https://", "http://")):
        raise ValueError("模型 API 地址必须使用 http:// 或 https://")
    timestamp = _now()
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
                   capabilities_json, created_by, created_at, updated_at, published_at
               ) VALUES (?, ?, ?, ?, ?, 'published', ?, ?, ?, ?, ?)""",
            (
                cleaned_model_id,
                cleaned_display_name,
                provider,
                cleaned_provider_model,
                cleaned_url,
                json.dumps(capabilities or {"streaming": True, "tool_calls": True}, separators=(",", ":")),
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
               WHERE model_id = ?""",
            (status, timestamp, status, timestamp, model_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("模型不存在")
        connection.commit()
        row = connection.execute("SELECT * FROM model_catalog WHERE model_id = ?", (model_id,)).fetchone()
    return _decode_model(row)
