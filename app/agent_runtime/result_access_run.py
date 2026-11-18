"""Invocation-owned result presentation and bounded model requests."""

from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from ..core.tool_result_projection import project_result, truncation_prompt_note
from ..core.tool_result_units import canonical_json
from .tools.contracts import (
    ToolExecutionContext,
    ToolExecutionState,
    ToolResult,
    ToolStatus,
    make_tool_error,
    tool_error_details,
)
from .tools.projection import model_function_view
from .tools.result_access import (
    RESULT_READ_DEFINITION,
    ResultReadAccess,
    install_result_reader,
    result_read_content,
)
from .tools.tool_registry import ToolRegistry

_current: ContextVar[ResultAccessRun | None] = ContextVar(
    "fab_result_access_run", default=None
)


class ResultRequestLimit(RuntimeError):
    pass


class ResultAccessRun:
    def __init__(
        self,
        *,
        session_id=None,
        run_id="unbound",
        principal=None,
        store=None,
        enabled=False,
        authorize=lambda: False,
        unavailable_reason="NO_SESSION",
    ):
        self.session_id, self.run_id, self.principal = session_id, run_id, principal
        self.store, self.enabled, self.authorize = store, enabled, authorize
        self.unavailable_reason = unavailable_reason
        self.guard = None
        self.reader = None
        self.dispatcher = None
        self.closed = False
        self.views: dict[str, dict] = {}
        self._source_views: dict[str, dict] = {}
        self.notices: list[dict] = []
        self._notified = 0
        self.deadline = None
        self.request_count = 0
        self.output_remaining = 0
        self._read_sequence = 0
        self._active_task = None
        self._active_loop = None

    @contextmanager
    def activate(self):
        token = _current.set(self)
        try:
            self._active_task, self._active_loop = (
                asyncio.current_task(),
                asyncio.get_running_loop(),
            )
        except RuntimeError:
            pass
        try:
            yield self
        finally:
            _current.reset(token)
            self._active_task = self._active_loop = None

    def cancel(self):
        self.close()
        task, loop = self._active_task, self._active_loop
        if task is not None and loop is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)

    def close(self):
        self.closed = True
        if self.reader is not None:
            self.reader.phase = "closed"

    def authorized(self):
        try:
            return bool(self.authorize())
        except Exception:  # noqa: BLE001 - failed live authorization must deny without backend details
            return False

    def bind(self, guard, registry=None):
        if self.guard is not None:
            if self.guard is not guard:
                raise ValueError("Result access already belongs to another guard")
            return
        self.guard = guard
        if self.store is not None and self.session_id and self.principal is not None:
            self.reader = ResultReadAccess(
                self.store,
                self.principal,
                self.session_id,
                self.run_id,
                guard,
                self.authorized,
                enabled=self.enabled,
                cancelled=lambda: self.closed,
            )
            self.dispatcher = install_result_reader(
                registry or ToolRegistry(), self.reader
            )

    def begin_synthesis(self, timeout, max_output=8192):
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
            or type(max_output) is not int
            or not 1 <= max_output <= 32768
        ):
            raise ValueError("Invalid synthesis limits")
        if self.deadline is None:
            self.deadline = time.monotonic() + timeout
            self.output_remaining = max_output + 2048
        if self.reader is not None:
            self.reader.phase = "synthesis"
            self.reader.deadline = self.deadline

    def can_read(self):
        return bool(
            self.reader is not None
            and self.reader.permitted()
            and self.reader.reads < 4
            and self.guard.total_calls < self.guard.plan.budget.max_tool_calls
            and self.guard.stop_reason
            in {None, "required_evidence_complete", "no_progress", "deterministic_plan_completed"}
        )

    def tool_view(self):
        return model_function_view(RESULT_READ_DEFINITION)

    def render(self, tool, data, *, call_id, source_ref, scope=None, envelope=None):
        if call_id in self.views:
            return self.views[call_id]
        if source_ref in self._source_views:
            self.views[call_id] = self._source_views[source_ref]
            return self.views[call_id]
        try:
            projected, truncation = project_result(tool, data)
            payload = {"ok": True, "data": projected, **(envelope or {})}
            if truncation is not None:
                payload["truncation"] = {
                    **truncation,
                    "note": truncation_prompt_note(tool, truncation),
                }
            large = (
                truncation is not None
                or len(canonical_json(payload).encode("utf-8")) > 8192
            )
        except (TypeError, ValueError, RecursionError, UnicodeError):
            payload, large = {**(envelope or {}), "ok": True, "data": None}, True
            projected = None
        if not large:
            self.views[call_id] = payload
            self._source_views[source_ref] = payload
            return payload
        notice = {
            "call_id": call_id,
            "tool": tool,
            "status": "unavailable",
            "reason": self.unavailable_reason or "RESULT_UNAVAILABLE",
            "message": "当前结果仅展示预览，未保存的省略内容不可回读。",
        }
        if not self.enabled and not self.unavailable_reason:
            notice.update(
                status="truncated",
                reason="OFFLOADING_DISABLED",
                message="大结果卸载已关闭，本次结果已截断，省略部分未保存、不可回读。",
            )
        elif (
            self.enabled
            and self.store is not None
            and self.guard is not None
            and self.authorized()
        ):
            try:
                metadata = {
                    "tool": tool,
                    "source_ref": source_ref,
                    "queried_at": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                    "scope": scope or {},
                }
                if len(canonical_json(metadata).encode("utf-8")) > 2560:
                    raise ValueError("Result metadata exceeds response budget")
                reference = self.store.save(
                    tenant_id=self.principal.tenant_id,
                    owner_id=self.principal.user_id,
                    session_id=self.session_id,
                    run_id=self.run_id,
                    call_id=call_id,
                    metadata=metadata,
                    content=data,
                    permit=lambda: not self.closed and self.authorized(),
                )
                notice.update(
                    status="saved",
                    reason=None,
                    result_ref=reference,
                    queried_at=metadata["queried_at"],
                    scope=metadata["scope"],
                    message="结果较大，当前展示预览；获准采用的结果已保存，可在当前会话的允许阶段按需读取。",
                )
            except Exception as exc:  # noqa: BLE001 - storage failures become public limitations
                code = getattr(exc, "code", "RESULT_SAVE_FAILED")
                notice.update(
                    reason=code,
                    message="结果已省略，但未能保存或当前不可回读；请勿将预览当作全部结果。",
                )
        payload["result_access"] = notice
        # Keep a valid envelope: never slice the serialized JSON protocol itself.
        if len(canonical_json(payload).encode("utf-8")) > 8192:
            try:
                text = canonical_json(projected)
            except (TypeError, ValueError, RecursionError, UnicodeError):
                text = ""
            payload = {
                **(envelope or {}),
                "ok": True,
                "data": None,
                "preview_format": "json_fragment",
                "preview": "",
                "result_access": notice,
            }
            low, high, best = 0, len(text), ""
            while low <= high:
                length = (low + high) // 2
                payload["preview"] = text[:length]
                if len(canonical_json(payload).encode("utf-8")) <= 8192:
                    best, low = text[:length], length + 1
                else:
                    high = length - 1
            payload["preview"] = best
        self.notices.append(notice)
        self.views[call_id] = payload
        self._source_views[source_ref] = payload
        return payload

    async def flush(self, progress):
        from inspect import isawaitable

        while self._notified < len(self.notices):
            notice = self.notices[self._notified]
            self._notified += 1
            if progress is not None:
                result = progress(
                    {"event": "tool_result_access", "notice": dict(notice)}
                )
                if isawaitable(result):
                    await result

    async def read(self, arguments):
        if self.dispatcher is None:
            return {
                "ok": False,
                "error_code": "RESULT_UNAVAILABLE",
                "error": "当前入口不支持结果回读。",
            }
        self._read_sequence += 1
        context = ToolExecutionContext(
            self.principal, self.run_id, f"result-read-{self._read_sequence}", None
        )
        result = await self.dispatch("read_tool_result", arguments, context)
        return json.loads(result_read_content(result))

    async def dispatch(self, name, arguments, context):
        result = await self.dispatcher.dispatch(name, arguments, context)
        # The shared Dispatcher deliberately validates before claiming. Charge
        # rejected auxiliary input here too, without changing business tools.
        if result.error is not None and result.error.code == "INVALID_ARGUMENTS":
            decision = self.reader.charge_rejected_input(result)
            if not decision.allowed:
                result = ToolResult(
                    context.call_id,
                    name,
                    "1.0.0",
                    ToolStatus.BLOCKED,
                    ToolExecutionState.NOT_STARTED,
                    error=make_tool_error("RESULT_READ_BUDGET"),
                )
        return result

    def prepare_request(self, payload, session):
        if self.closed or (
            self.session_id and self.store is not None and not self.authorized()
        ):
            raise ResultRequestLimit("会话已删除、撤销或执行已结束")
        messages = payload.get("messages", [])
        base_parts = [
            item.get("content", "") for item in messages if item.get("_fab_tool_result")
        ]
        read_parts = [
            item.get("content", "") for item in messages if item.get("_fab_result_read")
        ]
        clean = {
            **payload,
            "messages": [
                {
                    key: value
                    for key, value in item.items()
                    if not key.startswith("_fab_")
                }
                for item in messages
            ],
        }
        endpoint = getattr(session, "endpoint", None)
        prepared = (
            endpoint.prepare_payload(clean)
            if callable(getattr(endpoint, "prepare_payload", None))
            else clean
        )
        base_bytes = read_bytes = 0
        for item in prepared.get("messages", []):
            content = item.get("content", "")
            if content is None and item.get("role") == "assistant":
                content = ""
            if not isinstance(content, str):
                raise ResultRequestLimit("结果消息格式不可用")
            if any(part and part in content for part in read_parts):
                read_bytes += len(content.encode("utf-8"))
            elif item.get("role") == "tool" or any(
                part and part in content for part in base_parts
            ):
                size = len(content.encode("utf-8"))
                if item.get("role") == "tool" and size > 8192:
                    raise ResultRequestLimit("单工具结果视图超限")
                base_bytes += size
        if base_bytes > 24576 or read_bytes > 16384 or base_bytes + read_bytes > 40960:
            raise ResultRequestLimit("工具派生上下文超限，未发送模型请求")
        reserved = 0
        if self.deadline is not None:
            if (
                self.closed
                or time.monotonic() >= self.deadline
                or self.request_count >= 6
                or self.output_remaining < 1
            ):
                raise ResultRequestLimit("综合阶段预算已用尽")
            self.request_count += 1
            reserved = min(
                int(payload.get("max_tokens") or 8192), self.output_remaining
            )
            clean["max_tokens"] = reserved
        return clean, reserved


def current_result_access():
    return _current.get()


async def handle_result_read_round(context, assistant):
    calls = assistant.get("tool_calls") or []
    if not any(
        call.get("function", {}).get("name") == "read_tool_result" for call in calls
    ):
        return False
    access = current_result_access()
    if len(calls) != 1 or access is None or not access.can_read():
        raise ResultRequestLimit("回读必须单独调用且处于允许阶段")
    call = calls[0]
    page = await access.read(call["function"].get("arguments") or "{}")
    context.messages.append(
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "content": canonical_json(page),
            "_fab_result_read": True,
        }
    )
    await context.notify(
        context.progress,
        {
            "event": "tool_result_read",
            "status": "ok" if page.get("format") else "blocked",
        },
    )
    return True


def result_prompt_payload(
    tool, data, *, call_id, source_ref, scope=None, envelope=None
):
    run = current_result_access() or ResultAccessRun()
    return run.render(
        tool,
        data,
        call_id=call_id,
        source_ref=source_ref,
        scope=scope,
        envelope=envelope,
    )


async def stream_result_model(session, payload, progress, state=None):
    run = current_result_access() or ResultAccessRun()
    clean, reserved = run.prepare_request(payload, session)
    usage = None
    try:
        if run.deadline is None:
            response = await session.stream(clean, progress, state)
        else:
            response = await asyncio.wait_for(
                session.stream(clean, progress, state),
                timeout=max(0, run.deadline - time.monotonic()),
            )
        usage = response[1]
        return response
    finally:
        if reserved:
            used = usage.get("completion_tokens") if isinstance(usage, dict) else None
            run.output_remaining -= (
                used if type(used) is int and used >= 0 else reserved
            )


def typed_result_view(agent_run, call, call_id, result):
    access = agent_run.result_access
    if call.name == "read_tool_result":
        access.views[call.call_id] = json.loads(result_read_content(result))
    elif result.status is ToolStatus.SUCCEEDED:
        access.views[call.call_id] = access.render(
            call.name,
            result.data,
            call_id=call_id,
            source_ref=f"TOOL:{call_id}",
            scope=json.loads(call.arguments),
        )
    else:
        access.views[call.call_id] = {
            "ok":False, "data":None,
            **tool_error_details(result.error, result.execution_state),
        }


def present_observations(observations):
    access = current_result_access()
    if access is not None:
        for index, item in enumerate(observations):
            if item.status == "success":
                ref = item.source_ref or f"TOOL:offline-{index}"
                access.render(
                    item.tool,
                    item.result,
                    call_id=ref,
                    source_ref=ref,
                    scope=item.arguments,
                )


async def typed_model_stage(agent_run, request, *, model_stage):
    """Typed callers opt into the same per-run presentation and synthesis limits."""
    from dataclasses import replace

    access = agent_run.result_access
    if access.closed or (
        agent_run.context.cancellation is not None
        and agent_run.context.cancellation.is_cancelled()
    ):
        raise ResultRequestLimit("执行已取消或关闭")
    messages, payload_messages = [], []
    for message in request.messages:
        content = message.content
        if message.role == "tool":
            view = access.views.get(message.tool_call_id)
            if view is None:
                raise ResultRequestLimit("工具消息未绑定当前执行结果")
            content = canonical_json(view)
        messages.append(replace(message, content=content))
        item = {"role": message.role, "content": content}
        if message.role == "tool" and view.get("format") in {"units", "unit_fragment"}:
            item["_fab_result_read"] = True
        payload_messages.append(item)
    tools = json.loads(request.tools_json)
    if access.can_read() and any(
        item.get("status") == "saved" for item in access.notices
    ):
        tools.append(access.tool_view())
    _clean, reserved = access.prepare_request(
        {"messages": payload_messages, "max_tokens": 8192}, None
    )
    request = replace(
        request,
        messages=tuple(messages),
        tools_json=canonical_json(tools),
        max_output_tokens=reserved or None,
    )
    stage = None
    try:
        operation = model_stage(agent_run.context, request, model=agent_run.model)
        stage = (
            await operation
            if access.deadline is None
            else await asyncio.wait_for(
                operation, max(0, access.deadline - time.monotonic())
            )
        )
        return stage
    finally:
        if reserved:
            used = stage.value.usage.completion_tokens if stage is not None else 0
            # The typed legacy default does not distinguish missing usage from
            # a real zero. Keep the reservation unless a positive count exists.
            access.output_remaining -= used if used > 0 else reserved
