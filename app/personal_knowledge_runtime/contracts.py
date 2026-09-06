from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field, field_validator

from ..ocr_quality import OCRObservation
from ..processes import MANUFACTURING_STEPS


class PersonalKnowledgeError(Exception):
    def __init__(self, status_code: int, error_code: str, detail: str, retryable: bool = False):
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


class PersonalDocumentMetadata(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    process_steps: list[str] = Field(default_factory=list, max_length=20)
    equipment_ids: list[str] = Field(default_factory=list, max_length=100)
    effective_date: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        cleaned = " ".join((value or "").strip().split())
        return cleaned or None

    @field_validator("process_steps")
    @classmethod
    def clean_process_steps(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))
        invalid = [value for value in cleaned if value not in MANUFACTURING_STEPS]
        if invalid:
            raise ValueError(f"不支持的制程: {', '.join(invalid)}")
        return cleaned

    @field_validator("equipment_ids")
    @classmethod
    def clean_equipment_ids(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,31}", value) for value in cleaned):
            raise ValueError("设备编号格式不正确")
        return cleaned

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = " ".join(value.strip().split())
            key = tag.casefold()
            if tag and key not in seen:
                cleaned.append(tag)
                seen.add(key)
        if any(len(value) > 40 for value in cleaned):
            raise ValueError("单个标签不能超过 40 个字符")
        return cleaned


class PersonalDocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    process_steps: list[str] | None = Field(default=None, max_length=20)
    equipment_ids: list[str] | None = Field(default=None, max_length=100)
    effective_date: date | None = None
    tags: list[str] | None = Field(default=None, max_length=30)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("标题不能为空")
        return cleaned

    @field_validator("process_steps")
    @classmethod
    def clean_process_steps(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else PersonalDocumentMetadata.clean_process_steps(values)

    @field_validator("equipment_ids")
    @classmethod
    def clean_equipment_ids(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else PersonalDocumentMetadata.clean_equipment_ids(values)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else PersonalDocumentMetadata.clean_tags(values)


@dataclass(frozen=True)
class ExtractedSection:
    page_number: int | None
    section_path: str
    content: str
    ocr_observation: OCRObservation | None = None
