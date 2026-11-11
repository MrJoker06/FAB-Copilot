from __future__ import annotations

from datetime import date, timedelta


def default_range() -> tuple[str, str]:
    end = date.today()
    return (end - timedelta(days=89)).isoformat(), end.isoformat()


def normalize_range(start: str | None, end: str | None) -> tuple[str, str]:
    default_start, default_end = default_range()
    try:
        start_value = date.fromisoformat(start or default_start)
        end_value = date.fromisoformat(end or default_end)
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc
    if start_value > end_value:
        raise ValueError("开始日期不能晚于结束日期")
    if (end_value - start_value).days > 730:
        raise ValueError("单次查询范围不能超过 730 天")
    return start_value.isoformat(), end_value.isoformat()


def timestamp_bounds(start: str | None, end: str | None) -> tuple[str, str]:
    """Return an inclusive start and exclusive end for ISO timestamp filters."""
    start_value, end_value = normalize_range(start, end)
    end_exclusive = (date.fromisoformat(end_value) + timedelta(days=1)).isoformat()
    return start_value, end_exclusive
