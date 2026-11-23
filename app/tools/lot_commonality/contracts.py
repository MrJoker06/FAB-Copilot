"""Request, source, and error contracts for lot commonality analysis."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Protocol

from app.agent_runtime.tools.contracts import ToolPrincipal
from app.agent_runtime.tools.dispatch_contracts import (
    ToolDataSourceError,
    ToolInputError,
)

DIMENSIONS = ("equipment", "chamber", "recipe", "path_adjacent")
PASS_DIMENSIONS = frozenset({"equipment", "chamber", "recipe"})
ROLES = frozenset(
    {"primary", "concurrent_abnormal", "historical_abnormal", "normal_reference"}
)
UNION_GROUP = "union"
GROUP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
LOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,2}$")
SCOPE_BOUNDARIES = {
    "time_range": "start_inclusive_end_exclusive",
    "cutoff": "inclusive",
}


class LotCommonalityInputError(ToolInputError):
    """A request was rejected before any source read; ``detail`` is safe to show."""

    def __init__(
        self,
        detail: str,
        *,
        error_code: str = "VALIDATION_ERROR",
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.error_code = error_code
        self.context = dict(context) if context is not None else None


class LotCommonalityAccessError(PermissionError):
    """The principal may not read at least one requested lot.

    The message never names the lot so that existence is not disclosed.
    """

    error_code = "SCOPE_DENIED"
    detail = "当前身份无权访问请求的数据范围。"

    def __init__(self) -> None:
        super().__init__(self.detail)


class LotCommonalityDataError(ToolDataSourceError):
    """The whole source read failed; this is never reported as an empty result."""

    error_code = "DATA_SOURCE_FAILED"
    detail = "数据来源失败，不能将其当作无数据或切换到模拟来源。"

    def __init__(self) -> None:
        super().__init__(self.detail)


@dataclass(frozen=True)
class AnalysisLimits:
    max_groups: int = 4
    max_lots_per_group: int = 200
    max_unique_lots: int = 500
    max_source_rows: int = 50_000
    max_candidates: int = 500
    page_limit_default: int = 50
    page_limit_max: int = 200

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


DEFAULT_LIMITS = AnalysisLimits()


@dataclass(frozen=True)
class LotHistory:
    """Normalized history of one lot; ``passes`` follow the B1 pass contract."""

    lot_id: str
    wafer_count: int | None
    coverage: dict[str, object]
    passes: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class LotHistoryBatch:
    """Everything a source returned for one analysis; absent lots were not found."""

    source: dict[str, object]
    queried_at: str
    lots: dict[str, LotHistory] = field(default_factory=dict)


class LotHistorySource(Protocol):
    def fetch(
        self, lot_ids: tuple[str, ...], principal: ToolPrincipal
    ) -> LotHistoryBatch: ...


def complete_coverage() -> dict[str, object]:
    return {
        "records": "complete",
        "order": "complete",
        "truncated": False,
        "gaps": [],
        "failures": [],
    }


def _invalid(detail: str) -> LotCommonalityInputError:
    return LotCommonalityInputError(detail)


def _exact_keys(
    value: object, required: set[str], optional: set[str], name: str
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} 必须是对象。")
    keys = set(value)
    if not required <= keys or keys - required - optional:
        raise _invalid(f"{name} 字段不符合契约。")
    return dict(value)


def _text(value: object, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise _invalid(f"{name} 必须是 1～{max_length} 个字符的文本。")
    return value.strip()


def parse_offset_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise _invalid(f"{name} 必须是带时区偏移的 ISO 时间。")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(f"{name} 必须是带时区偏移的 ISO 时间。") from exc
    if parsed.utcoffset() is None:
        raise _invalid(f"{name} 必须带时区偏移，服务端不推断时区。")
    return parsed


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{name} 必须是正整数。")
    return value


def _parse_cutoff(value: object, lot_ids: set[str]) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("mode") not in {"time", "operation"}:
        raise _invalid("cutoff.mode 只能是 time 或 operation。")
    if value["mode"] == "time":
        raw = _exact_keys(value, {"mode", "at"}, {"per_lot"}, "cutoff")
        parse_offset_datetime(raw["at"], "cutoff.at")
        per_lot = raw.get("per_lot") or {}
        if not isinstance(per_lot, Mapping):
            raise _invalid("cutoff.per_lot 必须是对象。")
        for lot_id, at in per_lot.items():
            if lot_id not in lot_ids:
                raise _invalid("cutoff.per_lot 只能引用已输入的 lot。")
            parse_offset_datetime(at, "cutoff.per_lot")
        return {"mode": "time", "at": raw["at"], "per_lot": dict(sorted(per_lot.items()))}
    raw = _exact_keys(
        value, {"mode", "operation_key"}, {"occurrence", "per_lot"}, "cutoff"
    )
    occurrence = raw.get("occurrence")
    if occurrence is not None:
        _positive_int(occurrence, "cutoff.occurrence")
    per_lot = raw.get("per_lot") or {}
    if not isinstance(per_lot, Mapping):
        raise _invalid("cutoff.per_lot 必须是对象。")
    for lot_id, item in per_lot.items():
        if lot_id not in lot_ids:
            raise _invalid("cutoff.per_lot 只能引用已输入的 lot。")
        _positive_int(item, "cutoff.per_lot")
    return {
        "mode": "operation",
        "operation_key": _text(raw["operation_key"], "cutoff.operation_key", max_length=128),
        "occurrence": occurrence,
        "per_lot": dict(sorted(per_lot.items())),
    }


def parse_create_request(
    body: object, limits: AnalysisLimits = DEFAULT_LIMITS
) -> dict[str, object]:
    """Validate a create request and return its normalized, JSON-safe form."""

    raw = _exact_keys(
        body, {"groups", "dimensions", "scope", "timezone"}, {"description"}, "请求"
    )
    groups = raw["groups"]
    if not isinstance(groups, list) or not groups:
        raise _invalid("groups 必须是非空数组。")
    if len(groups) > limits.max_groups:
        raise LotCommonalityInputError(
            "输入超过分析限额，请缩小 lot 范围。",
            error_code="ANALYSIS_LIMIT_EXCEEDED",
            context={"limit": "max_groups", "max": limits.max_groups, "actual": len(groups)},
        )
    normalized_groups: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for item in groups:
        group = _exact_keys(item, {"group_id", "name", "role", "lot_ids"}, set(), "group")
        group_id = group["group_id"]
        if (
            not isinstance(group_id, str)
            or not GROUP_ID_RE.fullmatch(group_id)
            or group_id == UNION_GROUP
            or group_id in seen_ids
        ):
            raise _invalid("group_id 无效、重复或使用了保留值。")
        seen_ids.add(group_id)
        if group["role"] not in ROLES:
            raise _invalid("group.role 不在允许范围内。")
        lot_ids = group["lot_ids"]
        if not isinstance(lot_ids, list) or not lot_ids:
            raise _invalid("lot_ids 必须是非空数组。")
        cleaned: list[str] = []
        for lot_id in lot_ids:
            if not isinstance(lot_id, str) or not LOT_ID_RE.fullmatch(lot_id.strip()):
                raise _invalid("lot_ids 含空值或格式无效的 lot。")
            cleaned.append(lot_id.strip())
        unique = list(dict.fromkeys(cleaned))
        if len(unique) > limits.max_lots_per_group:
            raise LotCommonalityInputError(
                "输入超过分析限额，请缩小 lot 范围。",
                error_code="ANALYSIS_LIMIT_EXCEEDED",
                context={
                    "limit": "max_lots_per_group",
                    "group_id": group_id,
                    "max": limits.max_lots_per_group,
                    "actual": len(unique),
                },
            )
        normalized_groups.append(
            {
                "group_id": group_id,
                "name": _text(group["name"], "group.name", max_length=64),
                "role": group["role"],
                "lot_ids": cleaned,
            }
        )
    if sum(group["role"] == "primary" for group in normalized_groups) != 1:
        raise _invalid("必须有且只有一个 primary 组。")
    all_lots = {lot for group in normalized_groups for lot in group["lot_ids"]}
    if len(all_lots) > limits.max_unique_lots:
        raise LotCommonalityInputError(
            "输入超过分析限额，请缩小 lot 范围。",
            error_code="ANALYSIS_LIMIT_EXCEEDED",
            context={
                "limit": "max_unique_lots",
                "max": limits.max_unique_lots,
                "actual": len(all_lots),
            },
        )
    dimensions = raw["dimensions"]
    if (
        not isinstance(dimensions, list)
        or not dimensions
        or len(set(dimensions)) != len(dimensions)
        or not set(dimensions) <= set(DIMENSIONS)
    ):
        raise _invalid("dimensions 必须是不重复的已知维度。")
    scope = _exact_keys(raw["scope"], {"time_range", "cutoff"}, set(), "scope")
    time_range = scope["time_range"]
    if time_range is not None:
        window = _exact_keys(time_range, {"start", "end"}, set(), "time_range")
        if parse_offset_datetime(window["start"], "time_range.start") >= parse_offset_datetime(
            window["end"], "time_range.end"
        ):
            raise _invalid("time_range.start 必须早于 end。")
        time_range = {"start": window["start"], "end": window["end"]}
    timezone = raw["timezone"]
    if not isinstance(timezone, str) or not TIMEZONE_RE.fullmatch(timezone):
        raise _invalid("timezone 必须是 IANA 时区名称。")
    description = raw.get("description")
    if description is not None:
        description = _text(description, "description", max_length=500)
    return {
        "groups": normalized_groups,
        "dimensions": [name for name in DIMENSIONS if name in dimensions],
        "scope": {
            "time_range": time_range,
            "cutoff": _parse_cutoff(scope["cutoff"], all_lots),
        },
        "timezone": timezone,
        "description": description,
    }
