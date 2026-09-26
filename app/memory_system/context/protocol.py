"""Structured contextualizer prompt and payload contract."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable


CONTEXTUALIZER_RESPONSE_FORMAT = {"type": "json_object"}


class ContextPayloadValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ContextProtocolError(ValueError):
    def __init__(self, code: str, message: str, content: str = ""):
        super().__init__(message)
        self.code = code
        self.response_length = len(content)
        self.response_fingerprint = _content_fingerprint(content) if content else None


def _content_fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines or not re.fullmatch(r"```(?:json)?\s*", lines[0], re.IGNORECASE):
        return stripped
    if len(lines) < 3 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def context_json_arguments(
    assistant: dict, *, protocol_error: Callable[[str, str, str], Exception] = ContextProtocolError
) -> dict:
    content = assistant.get("content")
    if not isinstance(content, str) or not content.strip():
        raise protocol_error("empty_response", "上下文解析器必须返回一个 JSON 对象", "")
    cleaned = strip_json_fence(content)
    try:
        arguments = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise protocol_error("invalid_json", "上下文解析结果不是合法 JSON", content) from exc
    try:
        return validate_contextualizer_payload(arguments)
    except ContextPayloadValidationError as exc:
        raise protocol_error(exc.code, str(exc), content) from exc


def context_protocol_correction(error: ContextProtocolError) -> dict:
    return {
        "role": "user",
        "content": (
            "上一次上下文分类响应未通过协议校验"
            f"（{error.code}）。请重新返回一个符合最初契约的 JSON 对象；"
            "不要回答用户问题，不要省略必需字段。"
        ),
    }


def normalized_context_protocol_error(
    error: ContextProtocolError, finish_reason: str | None
) -> ContextProtocolError:
    if error.code == "empty_response" and finish_reason == "length":
        normalized = ContextProtocolError("context_budget_exhausted", str(error))
        normalized.response_length = error.response_length
        normalized.response_fingerprint = error.response_fingerprint
        return normalized
    return error


def validate_contextualizer_payload(arguments: object) -> dict:
    """Validate the shared structured-context contract while allowing safe extensions."""
    if not isinstance(arguments, dict):
        raise ContextPayloadValidationError("invalid_object", "上下文解析结果必须是 JSON 对象")
    required_fields = {"relation", "resolved_question", "topic_anchor", "target_message_ids", "confidence", "intent_hint"}
    missing_fields = required_fields - set(arguments)
    if missing_fields:
        raise ContextPayloadValidationError("missing_field", f"上下文解析结果缺少字段：{', '.join(sorted(missing_fields))}")
    relation = arguments["relation"]
    intent_hint = arguments["intent_hint"]
    confidence = arguments["confidence"]
    target_ids = arguments["target_message_ids"]
    valid = (
        isinstance(relation, str) and relation in {"standalone", "followup", "correction", "recall"}
        and isinstance(arguments["resolved_question"], str) and bool(arguments["resolved_question"].strip())
        and isinstance(arguments["topic_anchor"], str)
        and isinstance(target_ids, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in target_ids)
        and isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence <= 1
        and isinstance(intent_hint, str) and intent_hint in {"conversation", "general_knowledge", "manufacturing_analysis", "unclear"}
    )
    if not valid:
        raise ContextPayloadValidationError("invalid_field_type", "上下文解析结果字段类型或枚举值非法")
    return arguments


CONTEXTUALIZER_PROMPT = """你是 Agent Loop 的会话上下文解析器，不负责回答用户问题。

读取最近会话和本轮输入后，只返回一个 JSON 对象，不得输出解释或 Markdown。JSON 必须包含：
- relation：standalone、followup、correction、recall 之一。
- resolved_question：可独立理解并进入路由的完整当前问题。
- topic_anchor：本轮引用的历史主题；独立问题使用空字符串。
- target_message_ids：recall 时填写被引用历史消息的 message_id 数组；其他关系使用空数组。
- confidence：0 到 1 之间的数字。
- intent_hint：conversation、general_knowledge、manufacturing_analysis、unclear 之一。
- turn_actions：可选数组。它不是工具调用；仅在可靠时返回 action 对象。

语义规则：
1. standalone：本轮是完整的新问题，resolved_question 保持本轮原意，不拼接旧主题。
2. followup：本轮省略了对象、条件或动作，需要从最近相关历史补全。
3. correction：本轮修改、替换或限制了上一问题，补全后必须体现修改，而不是保留被否定的要求。
4. recall：用户询问此前说过、问过或助手如何理解时，必须从输入中提供的 message_id 选择 target_message_ids；不得自行生成历史内容。若用户说“更前面的一个”，应选择比上次回忆目标更早的相关消息。
5. resolved_question 必须是可直接进入意图路由的完整任务，保留用户当前比较对象、范围和目标。
6. 只能恢复会话指代，禁止添加历史中不存在的制造事实、参数、结论或证据。
7. 只有主题、范围、对象、否定条件或回答方式，而没有独立信息请求的输入，不是 standalone；应与最近尚未完成的用户目标组合为 followup 或 correction。助手重复索要范围不代表用户已经放弃原目标。
8. 用户补充、限制或纠正回答应使用的知识来源时，resolved_question 必须同时保留最近尚未完成的信息目标和本轮来源偏好；不能只保留“查个人知识库”等来源动作。
9. intent_hint 由完整信息目标决定，而不是由来源名称决定。conversation 表示助手身份、能力、问候以及不请求外部技术或制造事实的交互或元问题；general_knowledge 表示概念、原理、分类、比较或行业常识，即使用户要求优先使用个人或工厂知识；manufacturing_analysis 表示需要当前生产、设备、批次、指标或异常数据；无法可靠判断时使用 unclear。
10. turn_actions 的完整形状为 [{"type":"answer_meta","subject":"capabilities","detail":"detailed"}]。允许 type 仅为 answer_meta、acknowledge、route_task、recall_history、clarify；最多三个动作，最多一个主要动作（answer_meta、route_task、recall_history、clarify），acknowledge 可与它组合。answer_meta 仅可使用 identity、capabilities、usage_help、limitations_policy、runtime_status、response_review、social、other 主题和 brief、standard、detailed 粒度。模型优先只生成 answer_meta/acknowledge；route_task、recall_history、clarify 通常由服务端派生。禁止包含工具名、SQL、URL 或自由参数；无把握时省略。
11. 不输出分析过程、解释或答案。"""
