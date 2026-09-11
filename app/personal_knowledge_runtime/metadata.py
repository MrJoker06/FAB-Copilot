from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from ..manufacturing.processes import MANUFACTURING_STEPS, PROCESS_ALIASES
from .contracts import ExtractedSection, PersonalDocumentMetadata, PersonalKnowledgeError


DOCUMENT_TYPE_TAGS = {
    "SOP": ("sop", "standard operating procedure", "标准作业程序", "作业指导书"),
    "CONTROL PLAN": ("control plan", "控制计划"),
    "GUIDE": ("guide", "guideline", "指南", "指引"),
    "REPORT": ("report", "报告"),
    "RECORD": ("record", "记录"),
    "TRAINING": ("training", "培训"),
}
TOPIC_TAGS = {
    "SCRATCH": ("scratch", "划伤", "刮伤"),
    "PARTICLE": ("particle", "颗粒"),
    "MAINTENANCE": ("maintenance", "维护", "保养"),
    "SPC": ("spc", "statistical process control", "统计过程控制"),
    "YIELD": ("yield", "良率"),
    "CPK": ("cpk", "process capability index", "过程能力指数"),
    "RECIPE": ("recipe", "配方"),
    "ALARM": ("alarm", "报警", "告警"),
}
MAX_TAG_SOURCE_CHARS = 200_000


def _json_list(value: str | None) -> list[str]:
    try:
        result = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return result if isinstance(result, list) else []


def _document_dict(row) -> dict:
    item = dict(row)
    item["process_steps"] = _json_list(item.pop("process_steps_json", "[]"))
    item["equipment_ids"] = _json_list(item.pop("equipment_ids_json", "[]"))
    item["tags"] = _json_list(item.pop("tags_json", "[]"))
    item["tags_source"] = item.get("tags_source", "auto")
    item.pop("owner_user_id", None)
    item.pop("storage_key", None)
    item.pop("idempotency_key", None)
    return item


def _normalise_tags(values: Iterable[str]) -> list[str]:
    """Return stable, case-insensitively unique tags within public limits."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = " ".join(str(value).strip().split())
        key = tag.casefold()
        if tag and len(tag) <= 40 and key not in seen:
            result.append(tag)
            seen.add(key)
        if len(result) == 30:
            break
    return result


def _automatic_tags(title: str, filename: str, sections: Iterable[ExtractedSection]) -> list[str]:
    """Derive explainable tags from document text without a model call."""
    parts = [title, filename]
    remaining = MAX_TAG_SOURCE_CHARS - sum(len(part) for part in parts)
    for section in sections:
        if remaining <= 0:
            break
        part = f"{section.section_path}\n{section.content}"
        parts.append(part[:remaining])
        remaining -= len(part)
    text = "\n".join(parts)
    compact = text.casefold().replace(" ", "")
    tags: list[str] = []
    for step in MANUFACTURING_STEPS:
        aliases = PROCESS_ALIASES[step]
        if step.casefold() in text.casefold() or any(
            alias.casefold().replace(" ", "") in compact for alias in aliases
        ):
            tags.append(step)
    # Ordinary prose is excluded by requiring a digit, dash, or underscore.
    equipment_pattern = (
        r"\b(?=[A-Za-z][A-Za-z0-9_-]{1,31}\b)"
        r"(?=[A-Za-z0-9_-]*[0-9_-])[A-Za-z][A-Za-z0-9_-]+\b"
    )
    tags.extend(re.findall(equipment_pattern, text))
    suffix = Path(filename).suffix.lstrip(".").upper()
    for tag, aliases in DOCUMENT_TYPE_TAGS.items():
        if any(alias.casefold().replace(" ", "") in compact for alias in aliases):
            tags.append(tag)
    if suffix:
        tags.append(suffix)
    for tag, aliases in TOPIC_TAGS.items():
        if any(alias.casefold().replace(" ", "") in compact for alias in aliases):
            tags.append(tag)
    return _normalise_tags(tags)


def parse_metadata(raw: str | None) -> PersonalDocumentMetadata:
    try:
        return PersonalDocumentMetadata.model_validate_json(raw or "{}")
    except ValidationError as exc:
        fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
        raise PersonalKnowledgeError(400, "INVALID_METADATA", f"元数据不符合要求: {', '.join(fields)}") from exc
