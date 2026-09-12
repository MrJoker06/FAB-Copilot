"""Verified, deterministic user-facing Fab Copilot capability catalogue."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    title: str
    description: str
    examples: tuple[str, ...]
    limitations: tuple[str, ...]
    backing_references: tuple[str, ...]
    visibility: Literal["user", "admin"] = "user"

CAPABILITIES = (
    CapabilityDefinition("manufacturing_analysis", "制造数据分析", "分析良率、设备健康、Cpk、缺陷和异常。", ("分析昨天 CMP 良率",), ("结果来自演示系统的可复现模拟数据，不是生产观测。",), ("TOOL_HANDLERS:get_yield_trend", "TOOL_HANDLERS:get_process_capability", "TOOL_HANDLERS:get_equipment_health", "TOOL_HANDLERS:get_defect_pareto", "TOOL_HANDLERS:get_recent_excursions")),
    CapabilityDefinition("knowledge_retrieval", "知识与案例检索", "检索当前用户可访问的个人知识、工厂知识和历史案例。", ("查找 CMP 划伤处置 SOP",), ("案例只能形成待验证假设，不能证明当前根因。",), ("TOOL_HANDLERS:search_knowledge",)),
    CapabilityDefinition("session_context", "会话理解", "支持追问、纠正和基于真实消息记录的回忆。", ("具体展开刚才的第二点",), ("无法可靠绑定历史时会请求澄清，不会猜测。",), ("MODULE:app.context_resolver",)),
    CapabilityDefinition("evidence_governance", "证据约束", "把事实、推断、建议和证据限制分开呈现。", ("给出良率下降的证据和限制",), ("缺少数据时不会把推断表述为已证实结论。",), ("MODULE:app.evidence_validator", "MODULE:app.answer_synthesizer")),
    CapabilityDefinition("personal_knowledge", "个人文档管理", "支持个人知识上传、检索与引用。", ("上传并检索我的工艺笔记",), ("仅当前用户可访问的文档会参与检索。",), ("MODULE:app.personal_knowledge",)),
    CapabilityDefinition("model_governance", "模型治理", "管理员可以配置模型能力和兼容性测试。", ("管理员检查模型 Thinking 兼容性",), ("普通用户不能查看或修改管理员配置。",), ("MODULE:app.model_registry",), "admin"),
)

def user_capabilities(*, is_admin: bool = False) -> tuple[CapabilityDefinition, ...]:
    return tuple(item for item in CAPABILITIES if is_admin or item.visibility == "user")

def build_meta_response(subject: str | None, detail: str, *, runtime_context: dict | None = None, is_admin: bool = False) -> tuple[str, tuple[str, ...]]:
    caps = user_capabilities(is_admin=is_admin)
    ids = tuple(item.capability_id for item in caps)
    if subject == "identity": return "我是 Fab Copilot，一个面向半导体制造分析、知识检索与证据约束回答的助手。", ()
    if subject == "social": return "你好。我可以协助制造分析、知识检索和会话中的问题澄清。", ()
    if subject == "usage_help": return "你可以直接描述目标，例如“分析昨天 CMP 良率”“查找 CMP 划伤 SOP”，或追问“把刚才的证据展开”。", ()
    if subject == "limitations_policy": return "我只执行受控的只读查询；高风险生产动作需要工程师复核。演示数据会明确标记为模拟数据，证据不足时会说明限制。", ()
    if subject == "runtime_status":
        runtime_context = runtime_context or {}
        requested = bool(runtime_context.get("thinking_requested"))
        return (f"本轮 Thinking 请求状态：{'已请求' if requested else '未请求'}；上下文分类始终关闭 Thinking（effective=false），本轮对话回答使用确定性模板（answer effective=false）。", ())
    if subject == "response_review":
        review = (runtime_context or {}).get("previous_metadata")
        if isinstance(review, dict):
            route = (review.get("intent_route") or {}).get("intent") if isinstance(review.get("intent_route"), dict) else None
            context = review.get("context_resolution") if isinstance(review.get("context_resolution"), dict) else {}
            decision = review.get("turn_decision") if isinstance(review.get("turn_decision"), dict) else {}
            if route or context or decision:
                return f"上一轮记录显示路由为 {route or '未知'}，上下文状态为 {context.get('resolution_state', '未记录')}，决策来源为 {decision.get('source', '未记录')}。这只解释已保存元数据，不推测未记录原因。", ()
        return "当前没有足够的上一轮运行元数据可供复盘，因此我不能推测原因。", ()
    if subject == "capabilities":
        if detail == "detailed":
            lines = ["我当前可验证的具体能力如下："]
            for item in caps:
                lines.append(f"\n- {item.title}：{item.description}\n  例如：{item.examples[0]}\n  限制：{item.limitations[0]}")
            return "".join(lines), ids
        return "Fab Copilot 可以提供制造数据分析、知识与案例检索、会话追问与回忆、证据约束回答，以及个人文档管理。制造结果会标注模拟数据与证据限制。", ids
    return "你想了解我的身份、具体能力、使用方式、限制，还是当前运行状态？", ()
