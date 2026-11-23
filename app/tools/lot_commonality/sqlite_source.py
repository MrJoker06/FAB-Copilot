"""Read-only SQLite lot history source for lot commonality analysis.

The local ``process_runs`` table stores one chamber per (lot, operation_seq) and
has no batch id, wafer counts, or separate rework passes, so every pass is
reported at ``reported`` granularity and rework is a flag on that pass.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent_runtime.tools.contracts import ToolPrincipal
from app.core.sqlite_support import install_sqlite_functions
from app.tools.lot_commonality.contracts import (
    LotCommonalityAccessError,
    LotCommonalityDataError,
    LotHistory,
    LotHistoryBatch,
    complete_coverage,
)

_LOT_CHUNK = 500
_PASS_SQL = (
    "SELECT run_id, lot_id, operation_seq, layer_name, process_step, equipment_id, "
    "chamber, recipe, run_time, queue_hours, rework_flag FROM process_runs "
    "WHERE lot_id IN ({placeholders}) AND (lot_id > ? OR (lot_id = ? AND operation_seq > ?)) "
    "ORDER BY lot_id, operation_seq LIMIT ?"
)


class SQLiteLotHistorySource:
    """Batch-read lot histories with keyset paging and an explicit row budget."""

    def __init__(
        self,
        manufacturing_path: Path,
        *,
        demo_tenant_id: str,
        timezone_name: str,
        utc_offset_minutes: int,
        page_size: int = 1000,
        max_rows: int = 50_000,
        busy_timeout_ms: int = 1000,
        query_timeout_ms: int = 5000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        for value, upper in (
            (page_size, 10_000),
            (max_rows, 1_000_000),
            (busy_timeout_ms, 10_000),
            (query_timeout_ms, 60_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= upper:
                raise ValueError("SQLite lot history limits must be bounded positive integers")
        if isinstance(utc_offset_minutes, bool) or not isinstance(utc_offset_minutes, int) or abs(utc_offset_minutes) > 14 * 60:
            raise ValueError("utc_offset_minutes must be a real UTC offset")
        self.manufacturing_path = Path(manufacturing_path)
        self.demo_tenant_id = demo_tenant_id
        self.timezone_name = timezone_name
        self.tz = timezone(timedelta(minutes=utc_offset_minutes))
        self.page_size = page_size
        self.max_rows = max_rows
        self.busy_timeout_ms = busy_timeout_ms
        self.query_timeout_ms = query_timeout_ms
        self.clock = clock or (lambda: datetime.now(self.tz))

    def source_metadata(self) -> dict[str, object]:
        return {
            "source_id": "sqlite:lot-commonality/process_runs",
            "kind": "sqlite",
            "timezone": self.timezone_name,
            "chamber_granularities": ["reported"],
            "pass_identity": "record",
            "rework_model": "flag_only",
        }

    def _connect(self) -> tuple[sqlite3.Connection, list[bool]]:
        if not self.manufacturing_path.is_file():
            raise LotCommonalityDataError()
        connection = sqlite3.connect(
            f"{self.manufacturing_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=self.busy_timeout_ms / 1000,
        )
        install_sqlite_functions(connection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        started = time.monotonic()
        timed_out = [False]

        def progress() -> int:
            timed_out[0] = (time.monotonic() - started) * 1000 > self.query_timeout_ms
            return int(timed_out[0])

        connection.set_progress_handler(progress, 1000)
        return connection, timed_out

    def _page(
        self,
        connection: sqlite3.Connection,
        chunk: list[str],
        after: tuple[str, int],
        size: int,
    ) -> list[sqlite3.Row]:
        sql = _PASS_SQL.format(placeholders=",".join("?" * len(chunk)))
        return connection.execute(sql, (*chunk, after[0], after[0], after[1], size)).fetchall()

    def _pass(self, row: sqlite3.Row) -> dict[str, object]:
        try:
            moment = datetime.fromisoformat(row["run_time"])
        except (TypeError, ValueError) as exc:
            raise LotCommonalityDataError() from exc
        if moment.utcoffset() is None:
            moment = moment.replace(tzinfo=self.tz)
        equipment = row["equipment_id"] or None
        chamber = row["chamber"] or None
        missing = [name for name, value in (("equipment_id", equipment), ("chamber", chamber)) if value is None]
        ref = f"process_runs:{row['run_id']}"
        has_chamber = chamber is not None and equipment is not None
        return {
            "record_ref": ref,
            "source_record_refs": [ref],
            "source_pass_id": None,
            "lot_id": row["lot_id"],
            "pass_seq": row["operation_seq"],
            "operation_key": f"{row['layer_name']}/{row['process_step']}",
            "layer": row["layer_name"],
            "step": row["process_step"],
            "equipment_id": equipment,
            "chamber_granularity": "reported" if has_chamber else "unknown",
            # The demo schema defines exactly one mandatory chamber per pass.
            "chamber_set_complete": has_chamber,
            "chambers": (
                [{"chamber": chamber, "chamber_key": f"{equipment}/{chamber}", "wafer_count": None, "wafer_ids": None}]
                if has_chamber
                else []
            ),
            "allocated_wafer_total": None,
            "recipe": row["recipe"] or None,
            "track_in_at": moment.isoformat(),
            "queue_hours": row["queue_hours"],
            "rework": {"is_rework": bool(row["rework_flag"]), "rework_of_record_ref": None},
            "missing_fields": missing,
        }

    def fetch(self, lot_ids: tuple[str, ...], principal: ToolPrincipal) -> LotHistoryBatch:
        if principal.tenant_id != self.demo_tenant_id:
            raise LotCommonalityAccessError()
        connection = None
        try:
            connection, _ = self._connect()
            found: dict[str, int] = {}
            for start in range(0, len(lot_ids), _LOT_CHUNK):
                chunk = list(lot_ids[start : start + _LOT_CHUNK])
                sql = f"SELECT lot_id, wafer_count FROM lots WHERE lot_id IN ({','.join('?' * len(chunk))})"
                for row in connection.execute(sql, chunk):
                    found[row["lot_id"]] = row["wafer_count"]
            ordered = sorted(found)
            passes: dict[str, list[dict[str, object]]] = {lot: [] for lot in ordered}
            remaining = self.max_rows
            read_any_page = False
            # (first lot that may be incomplete, reason); later lots are unread.
            stop: tuple[str, str] | None = None
            for start in range(0, len(ordered), _LOT_CHUNK):
                chunk = ordered[start : start + _LOT_CHUNK]
                after = ("", 0)
                while stop is None:
                    if remaining <= 0:
                        stop = (after[0] or chunk[0], "SOURCE_TRUNCATED")
                        break
                    size = min(self.page_size, remaining + 1)
                    try:
                        rows = self._page(connection, chunk, after, size)
                    except sqlite3.Error:
                        if not read_any_page:
                            raise
                        stop = (after[0] or chunk[0], "SOURCE_PAGE_FAILED")
                        break
                    read_any_page = True
                    for row in rows[:remaining]:
                        passes[row["lot_id"]].append(self._pass(row))
                    if len(rows) > remaining:
                        stop = (rows[remaining]["lot_id"], "SOURCE_TRUNCATED")
                        break
                    remaining -= len(rows)
                    if len(rows) < size:
                        break
                    after = (rows[-1]["lot_id"], rows[-1]["operation_seq"])
                if stop is not None:
                    break
            incomplete = (
                {lot: stop[1] for lot in ordered if lot >= stop[0]} if stop is not None else {}
            )
        except LotCommonalityDataError:
            raise
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise LotCommonalityDataError() from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
        lots = {}
        for lot in ordered:
            coverage = complete_coverage()
            reason = incomplete.get(lot)
            if reason is not None:
                coverage["records"] = "partial"
                if reason == "SOURCE_TRUNCATED":
                    coverage["truncated"] = True
                else:
                    coverage["failures"] = [{"reason": reason}]
            lots[lot] = LotHistory(lot, found[lot], coverage, tuple(passes[lot]))
        return LotHistoryBatch(
            self.source_metadata(),
            self.clock().isoformat(timespec="seconds"),
            lots,
        )
