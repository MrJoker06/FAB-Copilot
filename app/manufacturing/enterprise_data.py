from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Callable

from ..core.settings import get_settings
from ..core.identity import Principal, current_principal
from .data_contracts import EnterpriseDataProvider
from .processes import MANUFACTURING_STEPS


ENTITY_COUNTS = {
    "lots": 1,
    "process-runs": 18,
    "sensor-events": 144,
}
PRODUCTS = ("Nova-P1", "Nova-P2", "Orion-MCU", "Atlas-CIS", "Vega-PMIC")
TECHNOLOGIES = (28, 40, 55, 65, 90)
SIGNALS = (
    ("Chamber pressure", "Torr", 0.015, 8.0),
    ("RF power", "W", 80.0, 1800.0),
    ("Gas flow", "sccm", 10.0, 900.0),
    ("Temperature", "C", 20.0, 1100.0),
    ("Endpoint", "a.u.", 0.0, 1.0),
    ("Vibration", "mm/s", 0.0, 12.0),
)


class EnterpriseDataError(ValueError):
    def __init__(self, error_code: str, detail: str):
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def _canonical_filters(filters: dict) -> dict:
    return {key: str(value).strip() for key, value in sorted(filters.items()) if value not in (None, "")}


def _digest_int(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "-" for character in value.upper())
    return cleaned[:12] or "TENANT"


class SyntheticFabProvider:
    provider_id = "synthetic-fab-v1"

    def __init__(self):
        settings = get_settings()
        self.seed = settings.enterprise_mock_seed
        self.virtual_lots = settings.enterprise_mock_virtual_lots
        self.secret = settings.enterprise_mock_cursor_secret.encode("utf-8")

    def manifest(self, principal: Principal) -> dict:
        return {
            "provider": self.provider_id,
            "simulated": True,
            "tenant_id": principal.tenant_id,
            "virtual_scale": {
                entity: self.virtual_lots * multiplier
                for entity, multiplier in ENTITY_COUNTS.items()
            },
            "entities": {
                "lots": {"path": "/api/enterprise/data/lots", "primary_key": "lot_id"},
                "process-runs": {"path": "/api/enterprise/data/process-runs", "primary_key": "run_id"},
                "sensor-events": {"path": "/api/enterprise/data/sensor-events", "primary_key": "reading_id"},
            },
            "analytics": {
                "summary_path": "/api/enterprise/data/summary",
                "semantics": "deterministic_projection",
                "supports": ["date_range", "process_step", "equipment_id"],
            },
            "pagination": {"strategy": "signed_keyset_cursor", "default_limit": 100, "max_limit": 500},
            "retention_days": 730,
            "partition_recommendation": ["tenant_id", "event_date", "process_step"],
            "data_classification": "synthetic_non_production",
        }

    def summary(self, principal: Principal, filters: dict | None = None) -> dict:
        normalized = _canonical_filters(filters or {})
        self._validate_filters("process-runs", normalized)
        today = date.today()
        requested_start = self._parse_date(normalized.get("start"), "start")
        requested_end = self._parse_date(normalized.get("end"), "end")
        effective_start = max(requested_start or today - timedelta(days=89), today - timedelta(days=729))
        effective_end = min(requested_end or today, today)
        effective_filters = {
            **normalized,
            "start": effective_start.isoformat(),
            "end": effective_end.isoformat(),
        }
        if effective_start > effective_end:
            lot_count = run_count = sensor_count = 0
        else:
            run_count = self._filtered_count("process-runs", effective_filters)
            sensor_count = self._filtered_count("sensor-events", effective_filters)
            lot_count = self._filtered_count(
                "lots",
                {key: effective_filters[key] for key in ("start", "end")},
            )
            if effective_filters.get("equipment_id"):
                lot_count //= 5

        key = json.dumps(effective_filters, ensure_ascii=True, sort_keys=True)
        yield_pct = self._projected_metric(principal.tenant_id, key, "yield", 91.5, 97.8)
        pass_rate_pct = self._projected_metric(principal.tenant_id, key, "pass", 92.0, 99.2)
        avg_cycle_hours = self._projected_metric(principal.tenant_id, key, "cycle", 78.0, 138.0)
        hold_rate_pct = self._projected_metric(principal.tenant_id, key, "hold", 0.8, 4.8)
        excursion_rate_pct = self._projected_metric(principal.tenant_id, key, "excursion", 0.12, 1.25)
        sensor_missing_pct = self._projected_metric(principal.tenant_id, key, "missing", 0.03, 0.35)
        sensor_outlier_pct = self._projected_metric(principal.tenant_id, key, "outlier", 0.08, 0.9)
        completed_lots = round(lot_count * self._projected_metric(principal.tenant_id, key, "completed", 0.90, 0.98))
        equipment_rows = self._equipment_projection(principal, effective_filters, key, run_count)
        return {
            "provider": self.provider_id,
            "simulated": True,
            "tenant_id": principal.tenant_id,
            "query": {
                "filters": normalized,
                "effective_start": effective_start.isoformat(),
                "effective_end": effective_end.isoformat(),
                "query_id": f"agg-{_digest_int(self.seed, principal.tenant_id, key):016x}",
            },
            "aggregation": {
                "semantics": "deterministic_projection",
                "exact": False,
                "description": "由可复现模拟分布直接计算，未扫描或抽样外推原始明细",
            },
            "totals": {
                "lots": lot_count,
                "completed_lots": completed_lots,
                "wafers": lot_count * 25,
                "process_runs": run_count,
                "sensor_events": sensor_count,
            },
            "kpis": {
                "yield_pct": yield_pct,
                "process_pass_rate_pct": pass_rate_pct,
                "avg_cycle_hours": avg_cycle_hours,
                "hold_rate_pct": hold_rate_pct,
                "excursion_rate_pct": excursion_rate_pct,
                "excursion_runs": round(run_count * excursion_rate_pct / 100),
                "sensor_missing_pct": sensor_missing_pct,
                "sensor_outlier_pct": sensor_outlier_pct,
            },
            "equipment": equipment_rows,
            "lineage": {
                "source": self.provider_id,
                "classification": "synthetic_non_production",
                "generated_from": ["tenant_id", "date_window", "process_step", "equipment_id", "mock_seed"],
                "as_of": datetime.combine(today, time.min, tzinfo=timezone.utc).isoformat(),
                "freshness": "deterministic_daily_snapshot",
            },
        }

    def page(
        self,
        entity: str,
        principal: Principal,
        limit: int = 100,
        cursor: str | None = None,
        filters: dict | None = None,
    ) -> dict:
        if entity not in ENTITY_COUNTS:
            raise EnterpriseDataError("UNKNOWN_ENTITY", "不支持的数据实体")
        if not 1 <= limit <= 500:
            raise EnterpriseDataError("INVALID_PAGE_SIZE", "limit 必须在 1 到 500 之间")
        normalized_filters = _canonical_filters(filters or {})
        self._validate_filters(entity, normalized_filters)
        filter_hash = hashlib.sha256(
            json.dumps(normalized_filters, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        position = 0
        if cursor:
            payload = self._decode_cursor(cursor)
            if payload.get("tenant") != principal.tenant_id:
                raise EnterpriseDataError("CURSOR_SCOPE_MISMATCH", "游标不属于当前租户")
            if payload.get("entity") != entity or payload.get("filters") != filter_hash:
                raise EnterpriseDataError("CURSOR_QUERY_MISMATCH", "游标与当前数据实体或筛选条件不匹配")
            position = int(payload.get("position", 0))

        available = self._filtered_count(entity, normalized_filters)
        page_size = min(limit, max(0, available - position))
        records = [
            self._record(entity, principal, normalized_filters, position + offset)
            for offset in range(page_size)
        ]
        next_position = position + page_size
        next_cursor = None
        if next_position < available:
            next_cursor = self._encode_cursor({
                "v": 1,
                "tenant": principal.tenant_id,
                "entity": entity,
                "filters": filter_hash,
                "position": next_position,
            })
        return {
            "provider": self.provider_id,
            "simulated": True,
            "tenant_id": principal.tenant_id,
            "entity": entity,
            "filters": normalized_filters,
            "records": records,
            "page": {
                "count": len(records),
                "limit": limit,
                "position": position,
                "estimated_total": available,
                "next_cursor": next_cursor,
            },
        }

    def _validate_filters(self, entity: str, filters: dict) -> None:
        allowed = {
            "lots": {"start", "end", "product", "status"},
            "process-runs": {"start", "end", "process_step", "equipment_id"},
            "sensor-events": {"start", "end", "process_step", "equipment_id", "signal_name"},
        }[entity]
        unknown = set(filters) - allowed
        if unknown:
            raise EnterpriseDataError("INVALID_FILTER", f"不支持的筛选字段: {', '.join(sorted(unknown))}")
        if filters.get("process_step") and filters["process_step"] not in MANUFACTURING_STEPS:
            raise EnterpriseDataError("INVALID_PROCESS_STEP", "制程站点不在支持范围内")
        if filters.get("status") and filters["status"] not in {"Completed", "Running", "Hold"}:
            raise EnterpriseDataError("INVALID_STATUS", "批次状态必须是 Completed、Running 或 Hold")
        if filters.get("signal_name") and filters["signal_name"] not in {item[0] for item in SIGNALS}:
            raise EnterpriseDataError("INVALID_SIGNAL", "传感器信号不在支持范围内")
        start = self._parse_date(filters.get("start"), "start")
        end = self._parse_date(filters.get("end"), "end")
        if start and end and start > end:
            raise EnterpriseDataError("INVALID_DATE_RANGE", "开始日期不能晚于结束日期")

    @staticmethod
    def _parse_date(value: str | None, field: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise EnterpriseDataError("INVALID_DATE", f"{field} 必须使用 YYYY-MM-DD") from exc

    def _filtered_count(self, entity: str, filters: dict) -> int:
        total = self.virtual_lots * ENTITY_COUNTS[entity]
        divisor = (5, 3, len(MANUFACTURING_STEPS), 5, len(SIGNALS))
        active_divisors = [
            divisor[index]
            for index, key in enumerate(("product", "status", "process_step", "equipment_id", "signal_name"))
            if filters.get(key)
        ]
        for value in active_divisors:
            total = max(1, total // value)
        start = self._parse_date(filters.get("start"), "start")
        end = self._parse_date(filters.get("end"), "end")
        if start or end:
            today = date.today()
            lower = max(start or today - timedelta(days=729), today - timedelta(days=729))
            upper = min(end or today, today)
            covered_days = max(0, (upper - lower).days + 1)
            total = math.floor(total * covered_days / 730)
        return max(0, total)

    def _projected_metric(self, tenant_id: str, key: str, metric: str, low: float, high: float) -> float:
        ratio = (_digest_int(self.seed, tenant_id, key, metric) % 10_000) / 9_999
        return round(low + (high - low) * ratio, 3)

    def _equipment_projection(
        self,
        principal: Principal,
        filters: dict,
        key: str,
        total_runs: int,
    ) -> list[dict]:
        step = filters.get("process_step") or "FAB"
        requested = filters.get("equipment_id")
        equipment_ids = [requested] if requested else [f"{step}-{index:02d}" for index in range(1, 6)]
        rows = []
        for equipment_id in equipment_ids:
            equipment_key = f"{key}|{equipment_id}"
            pass_rate = self._projected_metric(principal.tenant_id, equipment_key, "pass", 90.0, 99.5)
            excursion_rate = self._projected_metric(principal.tenant_id, equipment_key, "excursion", 0.08, 1.8)
            health_score = round(max(0.0, min(100.0, pass_rate - excursion_rate * 2.5)), 2)
            rows.append({
                "equipment_id": equipment_id,
                "projected_runs": total_runs if requested else total_runs // len(equipment_ids),
                "pass_rate_pct": pass_rate,
                "excursion_rate_pct": excursion_rate,
                "health_score": health_score,
                "risk": "high" if health_score < 92 else ("watch" if health_score < 96 else "stable"),
            })
        rows.sort(key=lambda item: (item["health_score"], item["equipment_id"]))
        return rows

    def _record(self, entity: str, principal: Principal, filters: dict, position: int) -> dict:
        total = self.virtual_lots * ENTITY_COUNTS[entity]
        base = _digest_int(self.seed, principal.tenant_id, entity, json.dumps(filters, sort_keys=True)) % total
        sequence = (base + position * 104_729) % total
        if entity == "lots":
            return self._lot_record(principal, filters, sequence)
        if entity == "process-runs":
            return self._process_record(principal, filters, sequence)
        return self._sensor_record(principal, filters, sequence)

    def _event_time(self, sequence: int, filters: dict) -> datetime:
        today = date.today()
        start = self._parse_date(filters.get("start"), "start") or today - timedelta(days=729)
        end = self._parse_date(filters.get("end"), "end") or today
        start = max(start, today - timedelta(days=729))
        end = min(end, today)
        days = max(1, (end - start).days + 1)
        event_date = start + timedelta(days=sequence % days)
        return datetime.combine(event_date, time(sequence % 24, (sequence // 24) % 60), tzinfo=timezone.utc)

    def _lot_record(self, principal: Principal, filters: dict, sequence: int) -> dict:
        product = filters.get("product") or PRODUCTS[sequence % len(PRODUCTS)]
        status = filters.get("status") or ("Completed", "Running", "Hold")[sequence % 3]
        started = self._event_time(sequence, filters)
        wafer_count = 25
        yield_rate = 0.82 + (_digest_int(self.seed, sequence, "yield") % 1650) / 10_000
        return {
            "tenant_id": principal.tenant_id,
            "lot_id": f"{_slug(principal.tenant_id)}-L{sequence:012d}",
            "product": product,
            "technology_nm": TECHNOLOGIES[sequence % len(TECHNOLOGIES)],
            "route": "LOGIC-18",
            "priority": ("Normal", "Hot", "Super Hot")[sequence % 3],
            "start_time": started.isoformat(),
            "status": status,
            "wafer_count": wafer_count,
            "good_wafers": min(wafer_count, round(wafer_count * yield_rate)),
            "yield_rate": round(yield_rate, 4),
            "cycle_time_hours": round(72 + (_digest_int(sequence, "cycle") % 2400) / 10, 1),
            "synthetic": True,
        }

    def _process_record(self, principal: Principal, filters: dict, sequence: int) -> dict:
        step = filters.get("process_step") or MANUFACTURING_STEPS[sequence % len(MANUFACTURING_STEPS)]
        equipment = filters.get("equipment_id") or f"{step}-{sequence % 5 + 1:02d}"
        timestamp = self._event_time(sequence, filters)
        value = 90 + (_digest_int(sequence, step, "measurement") % 2000) / 100
        return {
            "tenant_id": principal.tenant_id,
            "run_id": f"RUN-{sequence:015d}",
            "lot_id": f"{_slug(principal.tenant_id)}-L{sequence % self.virtual_lots:012d}",
            "operation_seq": sequence % 18 + 1,
            "process_step": step,
            "equipment_id": equipment,
            "chamber": f"CH-{sequence % 4 + 1}",
            "recipe": f"{step}-R{sequence % 12 + 1:02d}",
            "run_time": timestamp.isoformat(),
            "measurement_name": "Normalized process metric",
            "measurement_value": round(value, 3),
            "measurement_unit": "a.u.",
            "pass_flag": int(92 <= value <= 108),
            "synthetic": True,
        }

    def _sensor_record(self, principal: Principal, filters: dict, sequence: int) -> dict:
        step = filters.get("process_step") or MANUFACTURING_STEPS[sequence % len(MANUFACTURING_STEPS)]
        equipment = filters.get("equipment_id") or f"{step}-{sequence % 5 + 1:02d}"
        selected_signal = filters.get("signal_name")
        signal = next((item for item in SIGNALS if item[0] == selected_signal), SIGNALS[sequence % len(SIGNALS)])
        low, high = signal[2], signal[3]
        ratio = (_digest_int(sequence, signal[0], "sensor") % 10_000) / 10_000
        value = low + (high - low) * ratio
        return {
            "tenant_id": principal.tenant_id,
            "reading_id": f"SNS-{sequence:016d}",
            "lot_id": f"{_slug(principal.tenant_id)}-L{sequence % self.virtual_lots:012d}",
            "process_step": step,
            "equipment_id": equipment,
            "chamber": f"CH-{sequence % 4 + 1}",
            "sample_time": self._event_time(sequence, filters).isoformat(),
            "signal_name": signal[0],
            "signal_value": round(value, 5),
            "signal_unit": signal[1],
            "is_missing": int(sequence % 997 == 0),
            "is_outlier": int(sequence % 251 == 0),
            "synthetic": True,
        }

    def _encode_cursor(self, payload: dict) -> str:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).decode("ascii").rstrip("=")

    def _decode_cursor(self, cursor: str) -> dict:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            body, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self.secret, body, hashlib.sha256).digest()
            if len(signature) != 32 or not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            payload = json.loads(body)
            if payload.get("v") != 1 or int(payload.get("position", -1)) < 0:
                raise ValueError("payload")
            return payload
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EnterpriseDataError("INVALID_CURSOR", "分页游标无效或已被修改") from exc


_PROVIDER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESERVED_PROVIDER_NAMES = frozenset({"synthetic"})
_ENTERPRISE_PROVIDER_FACTORIES: dict[str, Callable[[], EnterpriseDataProvider]] = {}
_REQUIRED_PROVIDER_METHODS = ("manifest", "summary", "page")


def register_enterprise_provider(
    name: str,
    factory: Callable[[], EnterpriseDataProvider],
) -> None:
    """Register a startup-time factory for an explicitly configured provider.

    Registration deliberately does not discover adapters or open connections.
    Production composition code must register an adapter before setting
    ``FAB_DATA_PROVIDER`` to its name.
    """
    if not isinstance(name, str) or not _PROVIDER_NAME_PATTERN.fullmatch(name):
        raise ValueError("enterprise provider name must be lowercase and use letters, digits, '-' or '_'")
    if name in _RESERVED_PROVIDER_NAMES:
        raise ValueError(f"enterprise provider name is reserved: {name}")
    if not callable(factory):
        raise TypeError("enterprise provider factory must be callable")
    if name in _ENTERPRISE_PROVIDER_FACTORIES:
        raise ValueError(f"enterprise provider is already registered: {name}")
    _ENTERPRISE_PROVIDER_FACTORIES[name] = factory


def _configured_provider_error(name: str) -> EnterpriseDataError:
    return EnterpriseDataError(
        "PROVIDER_NOT_CONFIGURED",
        f"企业数据提供器未配置: {name}",
    )


def _provider_from_factory(name: str, factory: Callable[[], EnterpriseDataProvider]) -> EnterpriseDataProvider:
    try:
        provider = factory()
    except Exception as exc:
        raise _configured_provider_error(name) from exc
    if not all(callable(getattr(provider, method, None)) for method in _REQUIRED_PROVIDER_METHODS):
        raise _configured_provider_error(name)
    return provider


def get_enterprise_provider() -> EnterpriseDataProvider:
    settings = get_settings()
    name = settings.enterprise_data_provider
    if name == "synthetic":
        return SyntheticFabProvider()
    factory = _ENTERPRISE_PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise _configured_provider_error(name)
    return _provider_from_factory(name, factory)


def enterprise_data_manifest() -> dict:
    return get_enterprise_provider().manifest(current_principal())


def enterprise_fab_summary(
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
) -> dict:
    return get_enterprise_provider().summary(
        current_principal(),
        {
            "start": start,
            "end": end,
            "process_step": process_step,
            "equipment_id": equipment_id,
        },
    )


def query_enterprise_data(
    entity: str,
    limit: int = 20,
    start: str | None = None,
    end: str | None = None,
    process_step: str | None = None,
    equipment_id: str | None = None,
    product: str | None = None,
    status: str | None = None,
    signal_name: str | None = None,
) -> dict:
    allowed_filters = {
        "lots": {"start", "end", "product", "status"},
        "process-runs": {"start", "end", "process_step", "equipment_id"},
        "sensor-events": {"start", "end", "process_step", "equipment_id", "signal_name"},
    }
    if entity not in allowed_filters:
        raise EnterpriseDataError("UNKNOWN_ENTITY", "不支持的数据实体")
    values = locals()
    filters = {key: values[key] for key in allowed_filters[entity] if values.get(key) not in (None, "")}
    return get_enterprise_provider().page(entity, current_principal(), min(max(limit, 1), 50), None, filters)
