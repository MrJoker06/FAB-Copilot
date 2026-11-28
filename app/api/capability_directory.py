"""Platform-managed registration of installed tools and standard Skill packages."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.bootstrap import capability_catalog as catalog
from app.core.identity import current_principal

from .routers.runtime import RouterBundle
from .schemas import FolderAccess


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access: FolderAccess | None
    groups: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=50
    )
    enabled: bool


def create_router(current_admin):
    router = APIRouter()

    @router.get("/api/admin/capabilities")
    def manage(_: Annotated[str, Depends(current_admin)]):
        return {"items": catalog.directory(current_principal(), admin=True)}

    @router.put("/api/admin/capabilities/{kind}/{name}")
    def register(
        kind: Literal["tool", "skill"],
        name: str,
        body: Registration,
        _: Annotated[str, Depends(current_admin)],
    ):
        installed = catalog.inventory().get((kind, name))
        if installed is None:
            raise HTTPException(404, "找不到已部署的工具或技能")
        if body.enabled and installed.get("availability_issue"):
            raise HTTPException(409, "技能包校验失败或当前版本未发布，无法启用")
        catalog.save(kind, name, body.model_dump())
        return {"registered": True}

    @router.get("/api/capabilities")
    def visible():
        return {"items": catalog.directory(current_principal())}

    return RouterBundle(router, {})
