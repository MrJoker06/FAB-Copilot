"""File-backed configuration for locally hosted models.

The database owns publication state, health, compatibility and user choices.
For a model present in this file, the editable connection/capability fields
are read from the file so an operator can change them without an API call.
Credentials deliberately live in ``model_credentials.json`` instead.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .model_capabilities import normalize_capabilities
from .settings import PROJECT_DIR

LOCAL_MODELS_VERSION = 1
LOCAL_MODELS_FILENAME = "local_models.json"

_LOCK = threading.RLock()


def local_models_path() -> Path:
    configured = os.getenv("FAB_LOCAL_MODELS_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_DIR / path
    return PROJECT_DIR / "runtime/local" / LOCAL_MODELS_FILENAME


def _clean_model_id(model_id: str) -> str:
    value = str(model_id or "").strip()
    if not value:
        raise ValueError("模型编号不能为空")
    return value


def _load_models() -> dict[str, dict]:
    path = local_models_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("本地模型配置文件无法读取") from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, dict):
        raise ValueError("本地模型配置文件格式不正确")
    return {
        str(model_id): dict(entry)
        for model_id, entry in models.items()
        if isinstance(model_id, str) and isinstance(entry, dict)
    }


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            import time

            time.sleep(0.05 * (attempt + 1))


def _write_models(models: dict[str, dict]) -> None:
    path = local_models_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": LOCAL_MODELS_VERSION, "models": models}
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        _replace_with_retry(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def get_local_model(model_id: str) -> dict | None:
    with _LOCK:
        try:
            entry = _load_models().get(_clean_model_id(model_id))
        except ValueError:
            return None
    return dict(entry) if entry is not None else None


def local_model_ids() -> set[str]:
    with _LOCK:
        try:
            return set(_load_models())
        except ValueError:
            return set()


def model_from_local_file(model_id: str) -> dict | None:
    entry = get_local_model(model_id)
    if entry is None:
        return None
    capabilities = normalize_capabilities(entry.get("capabilities"))
    return {
        "display_name": str(entry.get("display_name") or ""),
        "provider": str(entry.get("provider") or "openai-compatible"),
        "provider_model": str(entry.get("provider_model") or ""),
        "base_url": str(entry.get("base_url") or "").rstrip("/"),
        "capabilities": capabilities,
    }


def save_local_model(
    model_id: str,
    *,
    display_name: str,
    provider: str,
    provider_model: str,
    base_url: str,
    capabilities: dict,
) -> dict:
    cleaned = _clean_model_id(model_id)
    entry = {
        "model_id": cleaned,
        "display_name": str(display_name).strip(),
        "provider": str(provider).strip(),
        "provider_model": str(provider_model).strip(),
        "base_url": str(base_url).strip().rstrip("/"),
        "capabilities": normalize_capabilities(capabilities),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    with _LOCK:
        models = _load_models()
        models[cleaned] = entry
        _write_models(models)
    return dict(entry)


def update_local_model_capabilities(model_id: str, capabilities: dict) -> dict | None:
    cleaned = _clean_model_id(model_id)
    with _LOCK:
        models = _load_models()
        entry = models.get(cleaned)
        if entry is None:
            return None
        updated = dict(entry)
        updated["capabilities"] = normalize_capabilities(capabilities)
        updated["updated_at"] = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
        models[cleaned] = updated
        _write_models(models)
    return dict(updated)


def remove_local_model(model_id: str) -> bool:
    cleaned = _clean_model_id(model_id)
    with _LOCK:
        models = _load_models()
        if cleaned not in models:
            return False
        del models[cleaned]
        _write_models(models)
    return True


__all__ = [
    "LOCAL_MODELS_FILENAME",
    "LOCAL_MODELS_VERSION",
    "get_local_model",
    "local_model_ids",
    "local_models_path",
    "model_from_local_file",
    "remove_local_model",
    "save_local_model",
    "update_local_model_capabilities",
]
