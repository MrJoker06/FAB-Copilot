from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class AuditReader:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.directory.exists():
            return records
        for path in self.directory.rglob("*.jsonl"):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue
        records.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
        return records[: max(1, min(limit, 1000))]

    def summary(self, hours: int = 24) -> dict[str, Any]:
        cutoff = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 720)))
        events = []
        for event in self.events(20_000):
            try:
                timestamp = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if timestamp >= cutoff:
                events.append(event)
        finished = [item for item in events if item.get("event") == "agent_run_finished"]
        tool_calls = [item for item in events if item.get("event") == "tool_call_finished"]
        model_calls = [item for item in events if item.get("event") == "model_call_finished"]
        success = sum(item.get("status") == "success" for item in finished)
        durations = sorted(float(item.get("duration_ms", 0) or 0) for item in finished)
        p95 = durations[max(0, round(len(durations) * 0.95) - 1)] if durations else None
        tools = Counter(str(item.get("tool", "unknown")) for item in tool_calls)
        errors = Counter(
            str(item.get("error_type", "unknown")) for item in events if item.get("status") == "error"
        )
        return {
            "window_hours": hours,
            "runs": len(finished),
            "success_runs": success,
            "failed_runs": len(finished) - success,
            "success_rate_pct": round(success * 100 / len(finished), 2) if finished else None,
            "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else None,
            "p95_duration_ms": round(p95, 1) if p95 is not None else None,
            "model_calls": len(model_calls),
            "tool_calls": len(tool_calls),
            "tool_usage": [{"tool": name, "count": count} for name, count in tools.most_common()],
            "errors": [{"type": name, "count": count} for name, count in errors.most_common()],
            "recent_runs": finished[:20],
        }
