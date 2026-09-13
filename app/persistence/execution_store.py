from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .database import db_session
from ..core.identity import current_principal


_SCOPE_PARAMETERS = (
    "start",
    "end",
    "process_step",
    "equipment_id",
    "lot_id",
    "source_types",
    "sql",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _normalize(key: str, value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip().upper()
        return re.sub(r"\s+", " ", normalized) if key == "sql" else normalized
    if isinstance(value, list):
        items = tuple(_normalize(key, item) for item in value)
        return tuple(sorted(items)) if key == "source_types" else items
    return value


def _matches(planned_tool: str, planned: dict, actual_tool: str, actual: dict) -> bool:
    if planned_tool != actual_tool:
        return False
    for key in _SCOPE_PARAMETERS:
        if key not in planned:
            continue
        if key not in actual or _normalize(key, planned[key]) != _normalize(key, actual[key]):
            return False
    return True


def start_run_record(
    run_id: str,
    session_id: str,
    user_message_id: int | None,
    question: str,
    model: str,
) -> None:
    timestamp = _now()
    preview = " ".join(question.strip().split())[:240]
    with db_session() as connection:
        connection.execute(
            """INSERT INTO agent.agent_runs(
                   run_id, session_id, user_message_id, assistant_message_id, question_preview,
                   model, mode, status, started_at, completed_at
               ) VALUES (?, ?, ?, NULL, ?, ?, 'pending', 'running', ?, ?)
               ON CONFLICT(run_id) DO NOTHING""",
            (run_id, session_id, user_message_id, preview, model, timestamp, timestamp),
        )
        connection.commit()


def persist_execution_plan(run_id: str, plan: dict) -> None:
    timestamp = _now()
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    definition_status = str(plan.get("status") or "unsupported")
    execution_status = "running" if definition_status == "ready" and steps else "completed"
    completed_at = None if execution_status == "running" else timestamp
    with db_session() as connection:
        connection.execute(
            """INSERT INTO agent.agent_execution_plans(
                   run_id, plan_id, schema_version, planner_version, definition_status,
                   execution_status, reason, route_intent, playbook_id, playbook_version,
                   required_evidence_json, budget_json, missing_inputs_json,
                   clarification_questions_json, created_at, updated_at, completed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                   plan_id = excluded.plan_id,
                   schema_version = excluded.schema_version,
                   planner_version = excluded.planner_version,
                   definition_status = excluded.definition_status,
                   reason = excluded.reason,
                   route_intent = excluded.route_intent,
                   playbook_id = excluded.playbook_id,
                   playbook_version = excluded.playbook_version,
                   required_evidence_json = excluded.required_evidence_json,
                   budget_json = excluded.budget_json,
                   missing_inputs_json = excluded.missing_inputs_json,
                   clarification_questions_json = excluded.clarification_questions_json,
                   updated_at = excluded.updated_at""",
            (
                run_id,
                str(plan.get("plan_id") or ""),
                str(plan.get("schema_version") or ""),
                str(plan.get("planner_version") or ""),
                definition_status,
                execution_status,
                str(plan.get("reason") or ""),
                str(plan.get("route_intent") or "unknown"),
                plan.get("playbook_id"),
                plan.get("playbook_version"),
                _json(plan.get("required_evidence_ids") or []),
                _json(plan.get("budget") or {}),
                _json(plan.get("missing_inputs") or []),
                _json(plan.get("clarification_questions") or []),
                timestamp,
                timestamp,
                completed_at,
            ),
        )
        for sequence_no, step in enumerate(steps, start=1):
            connection.execute(
                """INSERT INTO agent.agent_plan_steps(
                       run_id, step_id, sequence_no, title, tool_name, parameters_json,
                       parameter_sources_json, evidence_ids_json, depends_on_json, required,
                       success_criteria_json, estimated_result_limit, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                   ON CONFLICT(run_id, step_id) DO UPDATE SET
                       sequence_no = excluded.sequence_no,
                       title = excluded.title,
                       tool_name = excluded.tool_name,
                       parameters_json = excluded.parameters_json,
                       parameter_sources_json = excluded.parameter_sources_json,
                       evidence_ids_json = excluded.evidence_ids_json,
                       depends_on_json = excluded.depends_on_json,
                       required = excluded.required,
                       success_criteria_json = excluded.success_criteria_json,
                       estimated_result_limit = excluded.estimated_result_limit""",
                (
                    run_id,
                    str(step.get("step_id") or f"S{sequence_no:02d}"),
                    sequence_no,
                    str(step.get("title") or ""),
                    str(step.get("tool") or "unknown"),
                    _json(step.get("parameters") or {}),
                    _json(step.get("parameter_sources") or {}),
                    _json(step.get("evidence_ids") or []),
                    _json(step.get("depends_on") or []),
                    int(bool(step.get("required"))),
                    _json(step.get("success_criteria") or []),
                    int(step.get("estimated_result_limit") or 0),
                ),
            )
        connection.commit()


def _matching_step(connection, run_id: str, tool: str, arguments: dict, statuses: tuple[str, ...]):
    placeholders = ",".join("?" for _ in statuses)
    rows = connection.execute(
        f"""SELECT step_id, tool_name, parameters_json, status
            FROM agent_plan_steps
            WHERE run_id = ? AND status IN ({placeholders})
            ORDER BY sequence_no""",
        (run_id, *statuses),
    ).fetchall()
    for row in rows:
        if _matches(row["tool_name"], _load(row["parameters_json"], {}), tool, arguments):
            return row
    return None


def start_tool_event(run_id: str, tool: str, arguments: dict) -> str | None:
    timestamp = _now()
    with db_session() as connection:
        step = _matching_step(connection, run_id, tool, arguments, ("pending", "running"))
        step_id = str(step["step_id"]) if step is not None else None
        if step is not None and step["status"] == "pending":
            connection.execute(
                """UPDATE agent.agent_plan_steps
                   SET status = 'running', attempt_count = attempt_count + 1,
                       started_at = COALESCE(started_at, ?), error_message = NULL
                   WHERE run_id = ? AND step_id = ?""",
                (timestamp, run_id, step_id),
            )
            connection.execute(
                "UPDATE agent.agent_execution_plans SET execution_status = 'running', updated_at = ? WHERE run_id = ?",
                (timestamp, run_id),
            )
        sequence_no = connection.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM agent_tool_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO agent.agent_tool_events(
                   run_id, sequence_no, tool_name, arguments_json, status,
                   plan_step_id, started_at
               ) VALUES (?, ?, ?, ?, 'running', ?, ?)""",
            (run_id, sequence_no, tool or "unknown", _json(arguments), step_id, timestamp),
        )
        connection.commit()
    return step_id


def finish_tool_event(run_id: str, tool: str, arguments: dict, event: dict) -> str | None:
    timestamp = _now()
    with db_session() as connection:
        candidates = connection.execute(
            """SELECT tool_event_id, arguments_json, plan_step_id
               FROM agent_tool_events
               WHERE run_id = ? AND tool_name = ? AND status = 'running'
               ORDER BY sequence_no DESC""",
            (run_id, tool or "unknown"),
        ).fetchall()
        tool_event = next(
            (row for row in candidates if _load(row["arguments_json"], {}) == arguments),
            candidates[0] if candidates else None,
        )
        step_id = str(tool_event["plan_step_id"]) if tool_event is not None and tool_event["plan_step_id"] else None
        status = str(event.get("status") or "unknown")
        if tool_event is not None:
            connection.execute(
                """UPDATE agent.agent_tool_events
                   SET status = ?, row_count = ?, duration_ms = ?, error_message = ?, completed_at = ?
                   WHERE tool_event_id = ?""",
                (
                    status,
                    event.get("rows"),
                    event.get("duration_ms"),
                    event.get("error"),
                    timestamp,
                    tool_event["tool_event_id"],
                ),
            )
        if step_id:
            step_status = "succeeded" if status in {"ok", "success"} else "blocked" if status == "blocked" else "failed"
            connection.execute(
                """UPDATE agent.agent_plan_steps
                   SET status = ?, row_count = ?, duration_ms = ?, error_message = ?, completed_at = ?
                   WHERE run_id = ? AND step_id = ?""",
                (
                    step_status,
                    event.get("rows"),
                    event.get("duration_ms"),
                    event.get("error"),
                    timestamp,
                    run_id,
                    step_id,
                ),
            )
        connection.commit()
    return step_id


def finalize_execution(run_id: str, status: str, reason: str = "") -> None:
    if not run_id:
        return
    timestamp = _now()
    interrupted = status == "interrupted"
    with db_session() as connection:
        plan = connection.execute(
            "SELECT definition_status FROM agent_execution_plans WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if plan is not None:
            if interrupted:
                connection.execute(
                    """UPDATE agent.agent_plan_steps
                       SET status = 'interrupted', completed_at = ?, error_message = COALESCE(error_message, ?)
                       WHERE run_id = ? AND status = 'running'""",
                    (timestamp, reason or "运行被中断", run_id),
                )
                execution_status = "interrupted"
            elif status == "error":
                connection.execute(
                    """UPDATE agent.agent_plan_steps
                       SET status = 'failed', completed_at = ?, error_message = COALESCE(error_message, ?)
                       WHERE run_id = ? AND status = 'running'""",
                    (timestamp, reason or "Agent 运行失败", run_id),
                )
                execution_status = "failed"
            else:
                connection.execute(
                    """UPDATE agent.agent_plan_steps SET status = 'skipped', completed_at = ?
                       WHERE run_id = ? AND status = 'pending'""",
                    (timestamp, run_id),
                )
                required_gaps = connection.execute(
                    """SELECT COUNT(*) FROM agent_plan_steps
                       WHERE run_id = ? AND required = 1 AND status <> 'succeeded'""",
                    (run_id,),
                ).fetchone()[0]
                execution_status = "completed_with_gaps" if required_gaps else "completed"
            connection.execute(
                """UPDATE agent.agent_execution_plans
                   SET execution_status = ?, updated_at = ?, completed_at = ?, interruption_reason = ?
                   WHERE run_id = ?""",
                (execution_status, timestamp, timestamp, reason or None, run_id),
            )
        if status in {"error", "interrupted"}:
            connection.execute(
                """UPDATE agent.agent_runs
                   SET status = ?, completed_at = ?, error_message = ?
                   WHERE run_id = ? AND status = 'running'""",
                (status, timestamp, reason or None, run_id),
            )
        connection.commit()


def recover_interrupted_executions(reason: str = "服务重启时发现未完成运行") -> int:
    timestamp = _now()
    with db_session() as connection:
        run_ids = [
            row[0]
            for row in connection.execute("SELECT run_id FROM agent_runs WHERE status = 'running'").fetchall()
        ]
        if not run_ids:
            return 0
        placeholders = ",".join("?" for _ in run_ids)
        connection.execute(
            f"""UPDATE agent.agent_runs
                SET status = 'interrupted', completed_at = ?, error_message = ?
                WHERE run_id IN ({placeholders})""",
            (timestamp, reason, *run_ids),
        )
        connection.execute(
            f"""UPDATE agent.agent_execution_plans
                SET execution_status = 'interrupted', updated_at = ?, completed_at = ?, interruption_reason = ?
                WHERE run_id IN ({placeholders}) AND execution_status = 'running'""",
            (timestamp, timestamp, reason, *run_ids),
        )
        connection.execute(
            f"""UPDATE agent.agent_plan_steps
                SET status = 'interrupted', completed_at = ?, error_message = COALESCE(error_message, ?)
                WHERE run_id IN ({placeholders}) AND status = 'running'""",
            (timestamp, reason, *run_ids),
        )
        connection.execute(
            f"""UPDATE agent.agent_tool_events
                SET status = 'interrupted', completed_at = ?, error_message = COALESCE(error_message, ?)
                WHERE run_id IN ({placeholders}) AND status = 'running'""",
            (timestamp, reason, *run_ids),
        )
        connection.commit()
    return len(run_ids)


def _execution_payload(connection, run_id: str) -> dict | None:
    plan = connection.execute(
        "SELECT * FROM agent_execution_plans WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if plan is None:
        return None
    payload = dict(plan)
    for field, target, fallback in (
        ("required_evidence_json", "required_evidence_ids", []),
        ("budget_json", "budget", {}),
        ("missing_inputs_json", "missing_inputs", []),
        ("clarification_questions_json", "clarification_questions", []),
    ):
        payload[target] = _load(payload.pop(field), fallback)
    rows = connection.execute(
        "SELECT * FROM agent_plan_steps WHERE run_id = ? ORDER BY sequence_no",
        (run_id,),
    ).fetchall()
    steps = []
    for row in rows:
        step = dict(row)
        step["required"] = bool(step["required"])
        for field, fallback in (
            ("parameters_json", {}),
            ("parameter_sources_json", {}),
            ("evidence_ids_json", []),
            ("depends_on_json", []),
            ("success_criteria_json", []),
        ):
            step[field.removesuffix("_json")] = _load(step.pop(field), fallback)
        steps.append(step)
    payload["steps"] = steps
    incomplete = [step["step_id"] for step in steps if step["status"] != "succeeded"]
    payload["recovery"] = {
        "resumable": payload["execution_status"] == "interrupted" and bool(incomplete),
        "completed_step_ids": [step["step_id"] for step in steps if step["status"] == "succeeded"],
        "resume_from_step_ids": incomplete if payload["execution_status"] == "interrupted" else [],
    }
    return payload


def get_run_audit(run_id: str) -> dict:
    principal = current_principal()
    with db_session() as connection:
        run = connection.execute(
            """SELECT r.* FROM agent_runs r
               JOIN chat_sessions s ON s.session_id = r.session_id
               WHERE r.run_id = ? AND s.tenant_id = ? AND s.owner_user_id = ?""",
            (run_id, principal.tenant_id, principal.user_id),
        ).fetchone()
        if run is None:
            raise ValueError("Agent Run 不存在")
        execution = _execution_payload(connection, run_id)
        tool_rows = connection.execute(
            "SELECT * FROM agent_tool_events WHERE run_id = ? ORDER BY sequence_no",
            (run_id,),
        ).fetchall()
    tools = []
    for row in tool_rows:
        item = dict(row)
        item["arguments"] = _load(item.pop("arguments_json"), {})
        tools.append(item)
    run_payload = dict(run)
    timeline = [
        {
            "timestamp": run_payload["started_at"],
            "event": "run_started",
            "run_id": run_id,
            "status": "running",
        }
    ]
    if execution:
        timeline.append({
            "timestamp": execution["created_at"],
            "event": "plan_created",
            "run_id": run_id,
            "plan_id": execution["plan_id"],
            "status": execution["definition_status"],
        })
        for step in execution["steps"]:
            if step["started_at"]:
                timeline.append({
                    "timestamp": step["started_at"],
                    "event": "step_started",
                    "run_id": run_id,
                    "step_id": step["step_id"],
                    "tool": step["tool_name"],
                    "status": "running",
                })
            if step["completed_at"]:
                timeline.append({
                    "timestamp": step["completed_at"],
                    "event": "step_finished",
                    "run_id": run_id,
                    "step_id": step["step_id"],
                    "tool": step["tool_name"],
                    "status": step["status"],
                    "rows": step["row_count"],
                    "error": step["error_message"],
                })
    for tool in tools:
        if tool["started_at"]:
            timeline.append({
                "timestamp": tool["started_at"],
                "event": "tool_started",
                "run_id": run_id,
                "sequence_no": tool["sequence_no"],
                "step_id": tool["plan_step_id"],
                "tool": tool["tool_name"],
                "arguments": tool["arguments"],
                "status": "running",
            })
        if tool["completed_at"]:
            timeline.append({
                "timestamp": tool["completed_at"],
                "event": "tool_finished",
                "run_id": run_id,
                "sequence_no": tool["sequence_no"],
                "step_id": tool["plan_step_id"],
                "tool": tool["tool_name"],
                "status": tool["status"],
                "rows": tool["row_count"],
                "error": tool["error_message"],
            })
    timeline.append({
        "timestamp": run_payload["completed_at"],
        "event": "run_finished",
        "run_id": run_id,
        "status": run_payload["status"],
        "error": run_payload["error_message"],
    })
    event_order = {
        "run_started": 0,
        "plan_created": 1,
        "step_started": 2,
        "tool_started": 3,
        "tool_finished": 4,
        "step_finished": 5,
        "run_finished": 6,
    }
    timeline.sort(key=lambda item: (item["timestamp"] or "", event_order.get(item["event"], 99)))
    for sequence_no, item in enumerate(timeline, start=1):
        item["replay_sequence"] = sequence_no
    return {"run": run_payload, "execution": execution, "tool_events": tools, "timeline": timeline}


def executions_for_session(connection, session_id: str) -> dict[int, dict]:
    rows = connection.execute(
        "SELECT run_id, assistant_message_id FROM agent_runs WHERE session_id = ? AND assistant_message_id IS NOT NULL",
        (session_id,),
    ).fetchall()
    return {
        int(row["assistant_message_id"]): execution
        for row in rows
        if (execution := _execution_payload(connection, str(row["run_id"]))) is not None
    }


class RunExecutionRecorder:
    def __init__(self, session_id: str, user_message_id: int | None, question: str, model: str):
        self.session_id = session_id
        self.user_message_id = user_message_id
        self.question = question
        self.model = model
        self.run_id = ""

    async def observe(self, event: dict) -> None:
        event_type = event.get("event")
        if event_type == "run_started":
            self.run_id = str(event.get("run_id") or "")
            if self.run_id:
                start_run_record(self.run_id, self.session_id, self.user_message_id, self.question, self.model)
        elif not self.run_id:
            return
        if event_type == "stage" and event.get("stage") == "plan" and isinstance(event.get("plan"), dict):
            persist_execution_plan(self.run_id, event["plan"])
        elif event_type == "tool_started":
            step_id = start_tool_event(self.run_id, str(event.get("tool") or "unknown"), event.get("arguments") or {})
            if step_id:
                event["step_id"] = step_id
        elif event_type == "tool_finished":
            step_id = finish_tool_event(
                self.run_id,
                str(event.get("tool") or "unknown"),
                event.get("arguments") or {},
                event,
            )
            if step_id:
                event["step_id"] = step_id
        elif event_type == "run_failed":
            finalize_execution(self.run_id, "error", str(event.get("message") or "Agent 运行失败"))

    def complete(self, result: dict) -> None:
        result_run_id = str(result.get("run_id") or self.run_id)
        if not result_run_id:
            return
        if not self.run_id:
            self.run_id = result_run_id
            start_run_record(self.run_id, self.session_id, self.user_message_id, self.question, self.model)
        finalize_execution(result_run_id, "success")

    def fail(self, reason: str, interrupted: bool = False) -> None:
        finalize_execution(self.run_id, "interrupted" if interrupted else "error", reason)
