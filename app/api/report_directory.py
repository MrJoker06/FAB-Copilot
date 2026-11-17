"""Editable report links for the duty workspace, independent of model state."""
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.settings import PROJECT_DIR
from .routers.runtime import RouterBundle

_LOCK = threading.RLock()


class ReportLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=500)
    object: str = Field(default="", max_length=200)
    folder_id: str | None = Field(default=None, max_length=64)
    sort_order: int = Field(default=0, ge=0, le=100000)
    enabled: bool = True
    updated_at: str = Field(default="", max_length=40)

    @field_validator("title", "description", "object")
    @classmethod
    def clean_text(cls, value):
        cleaned = " ".join(value.split())
        if not cleaned and value and value.isspace():
            return ""
        return cleaned

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value):
        if not value:
            raise ValueError("报表名称不能为空")
        return value

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        value = value.strip()
        if re.search(r"[\s\\]", value):
            raise ValueError("报表链接不能包含空白或反斜杠")
        if value.startswith("/") and not value.startswith("//"):
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("请填写相对根路径或不含凭据的 HTTP(S) 链接")
        _ = parsed.port
        return value


class ReportFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=60)
    parent_id: str | None = Field(default=None, max_length=64)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("文件夹名称不能为空")
        return value


class ReportDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(default=0, ge=0)
    folders: list[ReportFolder] = Field(default_factory=list, max_length=100)
    reports: list[ReportLink] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def valid_references(self):
        if len({item.id for item in self.reports}) != len(self.reports):
            raise ValueError("报表编号不能重复")
        folders = {folder.id: folder for folder in self.folders}
        if len(folders) != len(self.folders):
            raise ValueError("文件夹编号不能重复")
        siblings = set()
        for folder in self.folders:
            key = (folder.parent_id, folder.name)
            if key in siblings:
                raise ValueError("同级文件夹名称不能重复")
            siblings.add(key)
            visited = {folder.id}
            parent_id = folder.parent_id
            while parent_id is not None:
                if parent_id not in folders or parent_id in visited:
                    raise ValueError("文件夹上级不存在或形成循环")
                visited.add(parent_id)
                parent_id = folders[parent_id].parent_id
        if any(item.folder_id is not None and item.folder_id not in folders for item in self.reports):
            raise ValueError("报表所属文件夹不存在")
        return self


def directory_path() -> Path:
    configured = os.getenv("FAB_REPORT_DIRECTORY_PATH", "").strip()
    path = Path(configured) if configured else PROJECT_DIR / "runtime/local/report_directory.json"
    return path if path.is_absolute() else PROJECT_DIR / path


def read_directory() -> ReportDirectory:
    path = directory_path()
    if path.exists():
        return ReportDirectory.model_validate_json(path.read_text(encoding="utf-8"))
    seed = PROJECT_DIR / "display_mock_data/catalog.json"
    items = json.loads(seed.read_text(encoding="utf-8")).get("reports", []) if seed.is_file() else []
    return ReportDirectory(reports=[ReportLink(**{key: item[key] for key in ("id", "title", "url", "description", "object", "updated_at") if key in item}, sort_order=index) for index, item in enumerate(items)])


def save_directory(request: ReportDirectory) -> ReportDirectory:
    with _LOCK:
        previous = read_directory()
        if previous.revision != request.revision:
            raise HTTPException(409, detail={"error_code": "REPORT_DIRECTORY_CONFLICT", "message": "目录已被更新，请刷新后重新编辑。", "retryable": False})
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        old = {item.id: item for item in previous.reports}
        for item in request.reports:
            before = old.get(item.id)
            item.updated_at = before.updated_at if before and before.model_dump(exclude={"updated_at"}) == item.model_dump(exclude={"updated_at"}) else now
        saved = request.model_copy(update={"revision": previous.revision + 1})
        path = directory_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw = tempfile.mkstemp(prefix=".report-directory-", suffix=".tmp", dir=path.parent)
        temporary = Path(raw)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
                target.write(saved.model_dump_json(indent=2) + "\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return saved


def create_router(current_admin) -> RouterBundle:
    router = APIRouter()

    def unavailable():
        return HTTPException(503, detail={"error_code": "REPORT_DIRECTORY_UNAVAILABLE", "message": "报表目录暂不可用，请联系管理员检查配置。", "retryable": True})

    @router.get("/api/reports/directory")
    def public_directory():
        try:
            directory = read_directory()
        except (OSError, ValueError):
            raise unavailable() from None
        items = sorted((item for item in directory.reports if item.enabled), key=lambda item: (item.sort_order, item.id))
        return {"revision": directory.revision, "reports": [item.model_dump(exclude={"folder_id", "sort_order", "enabled"}) for item in items]}

    @router.get("/api/admin/report-directory")
    def admin_directory(_: Annotated[str, Depends(current_admin)]):
        try:
            return read_directory().model_dump()
        except (OSError, ValueError):
            raise unavailable() from None

    @router.put("/api/admin/report-directory")
    def update_directory(request: ReportDirectory, _: Annotated[str, Depends(current_admin)]):
        try:
            return save_directory(request).model_dump()
        except (OSError, ValueError):
            raise unavailable() from None

    return RouterBundle(router, {})
