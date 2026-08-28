"""Offline answer stage, with live legacy functions supplied by the facade."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class OfflineAnswerDependencies:
    validate_evidence: Callable[..., Any]
    create_answer_contract: Callable[..., Any]
    synthesize_legacy_answer: Callable[..., Any]
    build_meta_response: Callable[..., tuple[str, tuple[str, ...]]]
    fab_overview: Callable[[], Any]
    equipment_health: Callable[[], Any]
    emit: Callable[..., None]
    evidence_observation_type: Any


def _result(
    mode: str,
    intent_route: Any,
    selection: Any,
    plan: Any,
    guard: Any,
    validation: Any,
    contract: Any,
    synthesis: Any,
    trace: list[dict] | None = None,
) -> dict:
    return {
        "answer": synthesis.answer,
        "tool_trace": trace or [],
        "sources": [],
        "mode": mode,
        "intent_route": intent_route.to_dict(),
        "domain_playbook": selection.to_dict(),
        "execution_plan": plan.to_dict(),
        "loop_guard": guard.summary(),
        "evidence_validation": validation.to_dict(),
        "answer_contract": contract.to_dict(),
        "answer_synthesis": synthesis.report.to_dict(),
    }


def offline_answer(
    question: str,
    intent_route: Any,
    playbook_selection: Any,
    execution_plan: Any,
    loop_guard: Any,
    context_resolution: Any = None,
    turn_decision: Any = None,
    runtime_context: dict | None = None,
    run_id: str | None = None,
    fallback_reason: str = "missing_api_key",
    *,
    deps: OfflineAnswerDependencies,
) -> dict:
    if intent_route.intent == "conversation":
        advertised_ids: tuple[str, ...] = ()
        validation = deps.validate_evidence(
            execution_plan, playbook_selection.selected_playbook, []
        )
        contract = deps.create_answer_contract(validation)
        if (
            context_resolution
            and context_resolution.strategy == "context_clarification"
        ):
            lines = [
                "我没能可靠确定你指的是哪一条历史消息。请直接选择一条，或把对象重新写完整："
            ]
            for item in context_resolution.candidate_messages:
                lines.append(
                    f"\n- 消息 #{item.get('message_id')}：{' '.join(str(item.get('content') or '').strip().split())[:240]}"
                )
            answer = "".join(lines)
        elif context_resolution and context_resolution.strategy == "semantic_recall":
            records = context_resolution.recalled_messages
            lines = ["根据当前会话中的原始记录："]
            for item in [row for row in records if row.get("role") == "user"]:
                lines.append(
                    f"\n> 用户消息 #{item.get('message_id')}：{str(item.get('content') or '')[:700]}"
                )
            for item in [row for row in records if row.get("role") == "assistant"]:
                metadata = (
                    item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else {}
                )
                route = (
                    metadata.get("intent_route")
                    if isinstance(metadata.get("intent_route"), dict)
                    else {}
                )
                steps = (
                    route.get("process_steps")
                    if isinstance(route.get("process_steps"), list)
                    else []
                )
                scope = (
                    route.get("scope_resolution")
                    if isinstance(route.get("scope_resolution"), dict)
                    else {}
                )
                tool_trace = (
                    metadata.get("tool_trace")
                    if isinstance(metadata.get("tool_trace"), list)
                    else []
                )
                if str(scope.get("scope_type") or "") == "unknown":
                    unresolved = (
                        scope.get("unresolved_mentions")
                        if isinstance(scope.get("unresolved_mentions"), list)
                        else []
                    )
                    label = (
                        f"（{', '.join(str(value) for value in unresolved)}）"
                        if unresolved
                        else ""
                    )
                    lines.append(
                        f"\n该轮运行将制造范围记录为未知{label}，没有把它映射为具体制程、设备或整厂范围；该轮实际执行了 {len(tool_trace)} 个工具。"
                    )
                elif (
                    route.get("intent") == "fab_diagnostic"
                    and not steps
                    and str(scope.get("scope_type") or "") in {"", "fab"}
                ):
                    lines.append(
                        "\n该轮运行没有解析出具体制程或设备范围，实际按整厂综合诊断执行；因此不能根据运行记录声称某个未解析缩写已被映射为特定制程。"
                    )
                elif scope.get("resolved_ids"):
                    lines.append(
                        f"\n该轮运行记录的分析范围是：{', '.join(str(value) for value in scope['resolved_ids'])}。"
                    )
                lines.append(
                    f"\n> 助手消息 #{item.get('message_id')} 摘要：{str(item.get('content') or '')[:700]}"
                )
            answer = "".join(lines)
        else:
            action = next(
                (
                    row
                    for row in (turn_decision.actions if turn_decision else ())
                    if row.type
                    in {"answer_meta", "recall_history", "route_task", "clarify"}
                ),
                None,
            )
            subject = (
                action.subject if action and action.type == "answer_meta" else None
            )
            detail = action.detail if action else "standard"
            answer, advertised_ids = deps.build_meta_response(
                subject, detail, runtime_context=runtime_context
            )
            if (
                context_resolution
                and context_resolution.strategy == "semantic_correction"
                and subject == "capabilities"
            ):
                answer = "明白，你要的是可验证的具体能力，而不是宽泛介绍。\n\n" + answer
            if run_id:
                deps.emit(
                    "meta_response_built",
                    run_id,
                    template_version="conversation-v2",
                    subject=subject,
                    detail=detail,
                    advertised_capability_count=len(advertised_ids),
                )
        synthesis = deps.synthesize_legacy_answer(answer, contract)
        result = _result(
            "deterministic",
            intent_route,
            playbook_selection,
            execution_plan,
            loop_guard,
            validation,
            contract,
            synthesis,
        )
        if turn_decision:
            result["turn_decision"] = turn_decision.to_dict()
            result["conversation_response"] = {
                "template_version": "conversation-v2",
                "advertised_capability_ids": list(advertised_ids),
                "advertised_capability_count": len(advertised_ids),
            }
        return result
    validation = deps.validate_evidence(
        execution_plan, playbook_selection.selected_playbook, []
    )
    contract = deps.create_answer_contract(validation)
    if execution_plan.status == "clarification_required":
        questions = (
            ("请把希望我回答或执行的内容再写完整一些。",)
            if intent_route.intent == "unknown"
            else execution_plan.clarification_questions
            or ("请补充要分析的制程、设备或时间范围。",)
        )
        synthesis = deps.synthesize_legacy_answer(
            "为了生成可执行的分析路径，请先补充以下信息：\n\n"
            + "\n".join(f"{i}. {item}" for i, item in enumerate(questions, 1)),
            contract,
        )
        return _result(
            "offline",
            intent_route,
            playbook_selection,
            execution_plan,
            loop_guard,
            validation,
            contract,
            synthesis,
        )
    if intent_route.intent == "general_knowledge":
        notice = (
            "当前未配置可用的模型 API，无法生成通用知识回答。请检查服务端模型配置后重试。"
            if fallback_reason == "missing_api_key"
            else "模型暂时不可用，已启用本地规则；通用知识问题暂不能由本地规则可靠回答。"
        )
        synthesis = deps.synthesize_legacy_answer(notice, contract)
        return _result(
            "offline",
            intent_route,
            playbook_selection,
            execution_plan,
            loop_guard,
            validation,
            contract,
            synthesis,
        )
    trace: list[dict] = []
    observations: list[Any] = []

    def call(name: str, handler: Callable[[], Any]) -> Any:
        decision = loop_guard.check_call(name, {})
        if not decision.allowed:
            trace.append(
                {
                    "tool": name,
                    "status": "blocked",
                    "error_code": decision.reason_code,
                    "error": decision.message,
                }
            )
            return None
        value = handler()
        loop_guard.record_result(name, value, True)
        observations.append(deps.evidence_observation_type(name, {}, "success", value))
        trace.append({"tool": name, "status": "local"})
        return value

    loop_guard.begin_round()
    overview = call("get_fab_overview", deps.fab_overview)
    equipment = call("get_equipment_health", deps.equipment_health)
    loop_guard.finish_round()
    unavailable = fallback_reason != "missing_api_key"
    lines = [
        "模型暂时不可用，已启用本地规则分析。"
        if unavailable
        else "当前未配置可用的模型 API，因此返回本地规则分析。"
    ]
    lines.append(
        f"最近90天共完成 {overview['lots']} 个批次，综合良率 {overview['yield_pct']}%，平均周期 {overview['avg_cycle_hours']} 小时。"
        if overview is not None
        else "运行时预算未允许查询工厂总览，因此当前没有可用于汇总的制造数据。"
    )
    risky = (equipment or [])[:3]
    if risky:
        lines.append(
            "优先关注设备："
            + "、".join(
                f"{row['equipment_id']}（{row['health']}，{row['excursions']}次异常）"
                for row in risky
            )
            + "。"
        )
    lines.append(
        "模型恢复后可获得针对问题的多轮工具分析。"
        if unavailable
        else "配置根目录 .env 的 FAB_MODEL_API_KEY 后，可获得针对问题的多轮工具分析。"
    )
    validation = deps.validate_evidence(
        execution_plan, playbook_selection.selected_playbook, observations
    )
    contract = deps.create_answer_contract(validation)
    synthesis = deps.synthesize_legacy_answer("\n\n".join(lines), contract)
    return _result(
        "offline",
        intent_route,
        playbook_selection,
        execution_plan,
        loop_guard,
        validation,
        contract,
        synthesis,
        trace,
    )
