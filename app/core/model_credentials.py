"""Local, per-model credentials for the model catalog.

The catalog deliberately stores no secrets.  Administrators may save one API
key per model in a local JSON file instead; the file lives outside the
database and outside the browser payloads.  Environment variables remain a
fallback so existing deployments keep working.

Resolution order for one catalog entry:

1. the local credentials file (an explicit, model-specific binding);
2. ``FAB_MODEL_API_KEY__<MODEL_ID>``;
3. ``DEEPSEEK_API_KEY`` for DeepSeek models;
4. the legacy global ``FAB_MODEL_API_KEY``.

Once a local entry exists it is authoritative for that model: the resolver
never borrows a key from another model.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .settings import PROJECT_DIR, model_api_key


class ModelCredentialError(ValueError):
    """Raised when the local credential file or one entry is invalid."""


_LOCK = threading.RLock()
_MAX_KEY_LENGTH = 4096


def model_credentials_path() -> Path:
    value = os.getenv("FAB_MODEL_CREDENTIALS_PATH", "").strip()
    path = Path(value) if value else PROJECT_DIR / "runtime/local/model_credentials.json"
    return path if path.is_absolute() else PROJECT_DIR / path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _clean_model_id(model_id: str) -> str:
    cleaned = str(model_id or "").strip()
    if not cleaned or len(cleaned) > 64:
        raise ModelCredentialError("模型编号不正确")
    return cleaned


def _clean_api_key(api_key: str) -> str:
    cleaned = str(api_key or "").strip()
    if not cleaned:
        raise ModelCredentialError("API Key 不能为空")
    if len(cleaned) > _MAX_KEY_LENGTH:
        raise ModelCredentialError("API Key 过长")
    if "\n" in cleaned or "\r" in cleaned:
        raise ModelCredentialError("API Key 不能包含换行")
    return cleaned


def _load_entries() -> dict[str, dict]:
    """Read the store without creating it.  Missing file means no entries."""
    path = model_credentials_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ModelCredentialError(f"无法读取模型凭据文件: {path.name}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelCredentialError(f"模型凭据文件格式不正确: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ModelCredentialError(f"模型凭据文件格式不正确: {path.name}")
    credentials = payload.get("credentials", {})
    if not isinstance(credentials, dict):
        raise ModelCredentialError(f"模型凭据文件格式不正确: {path.name}")
    entries: dict[str, dict] = {}
    for model_id, entry in credentials.items():
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if isinstance(entry, str):
            api_key = entry
            updated_at = ""
        elif isinstance(entry, dict):
            api_key = entry.get("api_key", "")
            updated_at = entry.get("updated_at", "")
        else:
            continue
        if isinstance(api_key, str) and api_key.strip():
            entries[model_id.strip()] = {
                "api_key": api_key.strip(),
                "updated_at": updated_at if isinstance(updated_at, str) else "",
            }
    return entries


def _replace_with_retry(source: Path, target: Path) -> None:
    # Windows can briefly hold a freshly written file (Defender/indexer), so a
    # direct os.replace occasionally raises PermissionError.  Retry the exact
    # replacement; the temp file is always cleaned up by the caller.
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


def _write_entries(entries: dict[str, dict]) -> None:
    path = model_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "credentials": {
            model_id: {
                "api_key": entry["api_key"],
                "updated_at": entry.get("updated_at") or _now(),
            }
            for model_id, entry in sorted(entries.items())
        },
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=".model-credentials-", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        _replace_with_retry(temporary_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def get_stored_model_api_key(model_id: str) -> str | None:
    """Return the explicitly stored key, or ``None`` when no entry exists."""
    cleaned = _clean_model_id(model_id)
    with _LOCK:
        entry = _load_entries().get(cleaned)
    return entry["api_key"] if entry else None


def resolve_model_api_key(model_id: str, provider: str) -> str:
    """Resolve the effective key for a model, preferring its local entry."""
    stored = get_stored_model_api_key(model_id)
    if stored is not None:
        return stored
    return model_api_key(model_id, provider)


def credential_status(model_id: str, provider: str) -> tuple[bool, str]:
    """Return ``(configured, source)`` where source is local_file/environment/missing."""
    if get_stored_model_api_key(model_id) is not None:
        return True, "local_file"
    if model_api_key(model_id, provider):
        return True, "environment"
    return False, "missing"


def set_stored_model_api_key(model_id: str, api_key: str) -> None:
    """Create or replace one model's local credential."""
    cleaned_model_id = _clean_model_id(model_id)
    cleaned_api_key = _clean_api_key(api_key)
    with _LOCK:
        entries = _load_entries()
        entries[cleaned_model_id] = {
            "api_key": cleaned_api_key,
            "updated_at": _now(),
        }
        _write_entries(entries)


def clear_stored_model_api_key(model_id: str) -> bool:
    """Delete one model's local credential; return whether an entry existed."""
    cleaned_model_id = _clean_model_id(model_id)
    with _LOCK:
        entries = _load_entries()
        if cleaned_model_id not in entries:
            return False
        entries.pop(cleaned_model_id)
        _write_entries(entries)
        return True
