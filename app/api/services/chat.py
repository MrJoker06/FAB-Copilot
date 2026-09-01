from __future__ import annotations

import httpx


class ChatService:
    def __init__(self, deps):
        self._deps = deps

    def prepare_chat(self, request):
        runtime = self._deps()
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
            return session_id, [], cached, None
        history = runtime["session_history"](session_id)
        message = runtime["append_message"](
            session_id,
            "user",
            request.message,
            client_message_id=request.client_message_id,
        )
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
        if request.thinking and not config["capabilities"].get("thinking", False):
            raise runtime["http_problem"](
                400,
                "MODEL_CAPABILITY_UNSUPPORTED",
                "当前模型不支持 Thinking 请求",
                False,
            )
        return principal, config["model"]

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
        principal, selected_model = runtime["_validate_chat_model_capabilities"](
            request
        )
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
            result = await runtime["run_agent"](
                request.message,
                history or [item.model_dump() for item in request.history],
                recorder.observe,
                thinking=request.thinking,
                session_id=session_id,
                user_message_id=user_message["message_id"] if user_message else None,
            )
            recorder.complete(result)
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
