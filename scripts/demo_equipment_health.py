"""Standalone, explicit-adapter demonstration for the equipment-health pilot."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.integrations.manufacturing.fake_equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.manufacturing.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthDataError,
    EquipmentHealthInput,
    EquipmentHealthInputError,
)


@dataclass(frozen=True)
class DemoPrincipal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...] = ("analyst",)


def _today(value: str | None) -> Callable[[], date]:
    try:
        as_of = date.fromisoformat(value) if value else date.today()  # noqa: DTZ011
    except ValueError as exc:
        raise EquipmentHealthInputError("as-of must use YYYY-MM-DD") from exc
    return lambda: as_of


def _source(value) -> dict[str, object]:
    return {
        "source_ref": value.source_ref,
        "adapter_id": value.adapter_id,
        "source_kind": value.source_kind.value,
        "scope": {
            "tenant_id": value.scope.tenant_id,
            "start_date": value.scope.start_date.isoformat()
            if value.scope.start_date
            else None,
            "end_date": value.scope.end_date.isoformat()
            if value.scope.end_date
            else None,
            "equipment_ids": list(value.scope.equipment_ids),
            "process_steps": list(value.scope.process_steps),
            "grain": value.scope.grain,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", choices=("fake", "sqlite"), default="fake")
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--as-of")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--manufacturing-db")
    parser.add_argument("--equipment-db")
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.arguments)
        input_value = EquipmentHealthInput.from_arguments(raw)
        today = _today(args.as_of)
        query = input_value.resolve(today())
        principal = DemoPrincipal(args.tenant_id, args.user_id)
        if args.adapter == "sqlite":
            if not args.manufacturing_db or not args.equipment_db:
                raise EquipmentHealthInputError(
                    "sqlite adapter requires both database paths"
                )
            from app.integrations.manufacturing.sqlite_equipment_health import (
                SQLiteEquipmentHealthAdapter,
            )

            port = SQLiteEquipmentHealthAdapter(
                args.manufacturing_db, args.equipment_db, demo_tenant_id=args.tenant_id
            )
        else:
            row = EquipmentHealthAggregate(
                query.equipment_id or "DEMO-01", 12, 1, 0.123, 98.5, 2, 15.0
            )
            port = FakeEquipmentHealthAdapter(args.tenant_id, {query: (row,)})
        binding = create_equipment_health_binding(port, today=today)
        result = binding.handler(
            input_value,
            ToolExecutionContext(
                principal, "demo-run", "demo-call", binding.dependencies
            ),
        )
        print(
            json.dumps(
                {
                    "status": result.status.value,
                    "call_id": result.call_id,
                    "data": result.data,
                    "row_count": result.row_count,
                    "sources": [_source(source) for source in result.sources],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (json.JSONDecodeError, EquipmentHealthInputError):
        print(
            json.dumps(
                {"status": "invalid_arguments", "error": {"code": "INVALID_ARGUMENTS"}},
                ensure_ascii=False,
            )
        )
        return 2
    except EquipmentHealthDataError:
        print(
            json.dumps(
                {"status": "failed", "error": {"code": "SOURCE_FAILURE"}},
                ensure_ascii=False,
            )
        )
        return 3
    except Exception:  # noqa: BLE001 - CLI boundary must redact unexpected failures.
        print(
            json.dumps(
                {"status": "failed", "error": {"code": "INTERNAL_ERROR"}},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
