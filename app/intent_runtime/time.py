from __future__ import annotations

import re
from datetime import date, timedelta

from .contracts import RoutedTimeRange

_EXPLICIT_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?!\d)")
_RELATIVE_RANGE_PATTERN = re.compile(
    r"(?:最近|近|过去)\s*(\d{1,3}|[一二三四五六七八九十两]{1,3})\s*(天|日|周|星期|个月|月)"
)
def _parse_explicit_dates(question: str) -> tuple[date, ...]:
    parsed: list[date] = []
    for match in _EXPLICIT_DATE_PATTERN.finditer(question):
        try:
            value = date(*(int(part) for part in match.groups()))
        except ValueError:
            continue
        if value not in parsed:
            parsed.append(value)
    return tuple(parsed)


def _range_amount(value: str) -> int:
    if value.isdigit():
        return max(1, int(value))
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if "十" not in value:
        return max(1, digits.get(value, 1))
    tens, _, ones = value.partition("十")
    return max(1, (digits.get(tens, 1) * 10) + digits.get(ones, 0))


def _time_range(question: str, current_date: date) -> RoutedTimeRange:
    explicit_dates = _parse_explicit_dates(question)
    if explicit_dates:
        start = min(explicit_dates)
        end = max(explicit_dates)
        return RoutedTimeRange(start.isoformat(), end.isoformat(), "explicit", False)

    match = _RELATIVE_RANGE_PATTERN.search(question)
    if match:
        amount = _range_amount(match.group(1))
        unit = match.group(2)
        days = amount if unit in {"天", "日"} else amount * (7 if unit in {"周", "星期"} else 30)
        start = current_date - timedelta(days=days - 1)
        return RoutedTimeRange(start.isoformat(), current_date.isoformat(), "relative", False)
    if "昨天" in question:
        yesterday = current_date - timedelta(days=1)
        return RoutedTimeRange(yesterday.isoformat(), yesterday.isoformat(), "yesterday", False)
    if "今天" in question or "今日" in question:
        return RoutedTimeRange(current_date.isoformat(), current_date.isoformat(), "today", False)
    start = current_date - timedelta(days=89)
    return RoutedTimeRange(start.isoformat(), current_date.isoformat(), "default_90_days", True)
