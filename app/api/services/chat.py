from __future__ import annotations

import httpx

from ...bootstrap.duty_chat_skill import (
    ChatSkillRequest,
    DutySkillError,
    allowed_history,
    choose_chat_skill,
    require_skill,
)
from ...memory_system.ports import HistoryReader
from .analysis_attachment import analysis_references, attached_question


async def run_chat_agent(runtime, request, principal, question, history, progress, **options):
    trusted_history = allowed_history(history, principal)
    if getattr(request, "analysis_ref", None) or getattr(request, "tool_result_ref", None):
        return await runtime["run_agent"](question, trusted_history, progress, **options)
    skill = choose_chat_skill(question, getattr(request, "skill_id", None), principal, history)
    selection = ChatSkillRequest(principal, skill)
    with selection.activate():
        result = await runtime["run_agent"](skill.question if skill else question, trusted_history, progress, **options)
        if selection.selected is not None:
            result["skill_execution"] = selection.selected.metadata()
        if getattr(request, "skill_id", None):
            result["requested_skill_id"] = request.skill_id
        return result


class ChatService:
    def __init__(self, deps, history_reader: HistoryReader):
        self._deps = deps
        self._history_reader = history_reader

    def prepare_chat(self, request):
        runtime = self._deps()
        selected = getattr(request, "skill_id", None)
        if selected:
            try:
                require_skill(runtime["current_principal"](), selected)
            except DutySkillError as exc:
                raise runtime["http_problem"](exc.status, exc.code, str(exc), False) from None
        try:
            session = (
                runtime["create_session"](request.message[:50])
                if not request.session_id
                else runtime["get_session"](request.session_id)
            )
        except ValueError as exc:
            raise runtime["http_problem"](
                404, "SESSION_NOT_FOUND", str(exc), False
            ) from exc
        session_id = session["session_id"]
        existing = runtime["client_message_content"](
            session_id, request.client_message_id
        )
        if existing is not None and existing != request.message:
            raise runtime["http_problem"](
                409, "IDEMPOTENCY_CONFLICT", "同一客户端消息编号不能用于不同内容", False
            )
        cached = runtime["cached_agent_result"](session_id, request.client_message_id)
        if cached:
            if cached.get("requested_skill_id") != selected:
                raise runtime["http_problem"](409, "IDEMPOTENCY_CONFLICT", "同一客户端消息编号不能更改技能选择。", False)
            skill_execution = cached.get("skill_execution")
            if isinstance(skill_execution, dict):
                try:
                    require_skill(runtime["current_principal"](), skill_execution["id"])
                except DutySkillError as exc:
                    raise runtime["http_problem"](exc.status, exc.code, str(exc), False) from None
            return session_id, [], cached, None
        history = self._history_reader.read(session_id)
        attached = getattr(request, "analysis_ref", None)
        metadata = {"analysis_ref": attached} if attached else {}
        if selected:
            metadata["requested_skill_id"] = selected
        message = runtime["append_message"](
            session_id,
            "user",
            request.message,
            metadata or None,
            client_message_id=request.client_message_id,
        )
        if message.get("duplicate") and (
            message.get("content", request.message) != request.message
            or (message.get("metadata") or {}).get("requested_skill_id") != selected
        ):
            raise runtime["http_problem"](409, "IDEMPOTENCY_CONFLICT", "同一客户端消息编号不能更改内容或技能。", False)
        if (
            message.get("duplicate")
            and history
            and history[-1].get("role") == "user"
            and history[-1].get("content") == request.message
        ):
            history = history[:-1]
        return session_id, history, None, message

    def validate_chat_model_capabilities(self, request):
        runtime = self._deps()
        principal = runtime["current_principal"]()
        config = runtime["public_user_model_config"](principal)
        thinking = config.get("thinking") if isinstance(config.get("thinking"), dict) else {}
        options = list(thinking.get("options") or [])
        selected_effort = request.thinking_effort
        if selected_effort is None:
            if not request.thinking:
                selected_effort = "off"
            else:
                configured = str(thinking.get("effort") or "off")
                # An explicit "thinking": true must not silently become "off"
                # merely because the model's default happens to be off.
                selected_effort = (
                    configured
                    if configured != "off" and configured in options
                    else (options[0] if options else "high")
                )
        if selected_effort != "off" and selected_effort not in options:
            raise runtime["http_problem"](
                400,
                "MODEL_CAPABILITY_UNSUPPORTED",
                "当前模型不支持该思考档位",
                False,
            )
        if selected_effort != "off" and not config["capabilities"].get("thinking", False):
            raise runtime["http_problem"](
                400,
                "MODEL_CAPABILITY_UNSUPPORTED",
                "当前模型不支持 Thinking 请求",
                False,
            )
        return (
            principal,
            config["model"],
            selected_effort,
            str(thinking.get("dialect") or ""),
        )

    def model_status_error(self, exc: httpx.HTTPStatusError):
        status_code = exc.response.status_code
        detail = f"模型 API 返回 {status_code}"
        try:
            error = exc.response.json().get("error", {}).get("message")
            if error:
                detail += f": {str(error)[:300]}"
        except Exception:
            pass
        return detail, status_code == 429 or status_code >= 500

    async def chat(self, request):
        runtime = self._deps()
        validated = runtime["_validate_chat_model_capabilities"](request)
        if len(validated) == 2:
            principal, selected_model = validated
            thinking_effort, thinking_dialect = "off", ""
        else:
            principal, selected_model, thinking_effort, thinking_dialect = validated
        question = attached_question(runtime, request, principal)
        session_id, history, cached, user_message = runtime["_prepare_chat"](request)
        if cached:
            cached["session_id"] = session_id
            cached["request_id"] = runtime["current_request_id"]()
            return cached
        recorder = runtime["RunExecutionRecorder"](
            session_id,
            user_message["message_id"] if user_message else None,
            request.message,
            selected_model,
        )
        runtime["begin_agent_run"](
            principal, session_id, request.message, selected_model
        )
        try:
            result = await run_chat_agent(
                runtime, request, principal, question,
                history or [item.model_dump() for item in request.history],
                recorder.observe,
                thinking=thinking_effort != "off",
                thinking_effort=thinking_effort,
                thinking_dialect=thinking_dialect,
                session_id=session_id,
                user_message_id=user_message["message_id"] if user_message else None,
                **({"result_ref": request.tool_result_ref, "result_cursor": request.tool_result_cursor} if request.tool_result_ref else {}),
            )
            recorder.complete(result)
            references = analysis_references(result, getattr(request, "analysis_ref", None))
            if references:
                result["analysis_refs"] = references
            result["session_id"] = session_id
            result["request_id"] = runtime["current_request_id"]()
            result["client_message_id"] = request.client_message_id
            message = runtime["append_message"](
                session_id, "assistant", result["answer"], result
            )
            runtime["record_agent_result"](
                session_id,
                message["message_id"],
                result,
                user_message_id=user_message["message_id"] if user_message else None,
                question=request.message,
            )
            runtime["emit"](
                "agent_run_persisted",
                str(result.get("run_id") or session_id),
                session_id=session_id,
                user_message_id=user_message["message_id"] if user_message else None,
                assistant_message_id=message["message_id"],
            )
            runtime["finish_agent_run"](
                principal,
                "success",
                str(result.get("run_id") or ""),
                str(result.get("model") or selected_model),
            )
            return result
        except DutySkillError as exc:
            recorder.fail(str(exc))
            runtime["finish_agent_run"](principal, "error", model=selected_model, error=str(exc))
            raise runtime["http_problem"](exc.status, exc.code, str(exc), False) from None
        except httpx.HTTPStatusError as exc:
            recorder.fail(str(exc))
            runtime["finish_agent_run"](
                principal, "error", model=selected_model, error=str(exc)
            )
            detail, retryable = runtime["_model_status_error"](exc)
            raise runtime["http_problem"](
                502, "MODEL_UPSTREAM_ERROR", detail, retryable
            ) from exc
        except httpx.RequestError as exc:
            recorder.fail(str(exc))
            runtime["finish_agent_run"](
                principal, "error", model=selected_model, error=str(exc)
            )
            raise runtime["http_problem"](
                502, "MODEL_NETWORK_ERROR", f"无法连接模型 API: {exc}", True
            ) from exc
        except Exception as exc:
            recorder.fail(str(exc))
            runtime["finish_agent_run"](
                principal, "error", model=selected_model, error=str(exc)
            )
            raise
