from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Literal

from .domain_playbooks import DomainPlaybook, EvidenceRequirement, PlaybookSelection
from .intent_router import IntentRoute
from .processes import PROCESS_ALIASES


PlanStatus = Literal["ready", "clarification_required", "unsupported"]
ScopeRole = Literal["primary", "context_only"]


@dataclass(frozen=True)
class PlanBudget:
    planned_tool_calls: int
    max_tool_calls: int
    max_model_iterations: int
    max_rows_per_call: int
    per_tool_limits: dict[str, int]
    max_identical_parameter_calls: int
    max_no_progress_rounds: int
    enforcement: Literal["runtime"] = "runtime"


@dataclass(frozen=True)
class AnalysisScopeContract:
    primary_scope_type: str
    primary_scope_ids: tuple[str, ...]
    primary_scope_labels: tuple[str, ...]
    context_only_tools: tuple[str, ...]


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    title: str
    tool: str
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]
    evidence_ids: tuple[str, ...]
    depends_on: tuple[str, ...]
    required: bool
    success_criteria: tuple[str, ...]
    estimated_result_limit: int
    scope_role: ScopeRole
    # Declarative metadata consumed by evidence validation; it never contains
    # a process-name-specific rule.
    semantic_id: str = "unknown"
    grain: str = "unknown"
    filter_provenance: str = "planner"
    evidence_kind: str = "unknown"
    evidence_scope: dict[str, tuple[str, ...]] | None = None
    evidence_start: str | None = None
    evidence_end: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    schema_version: str
    planner_version: str
    status: PlanStatus
    reason: str
    route_intent: str
    playbook_id: str | None
    playbook_version: str | None
    scope_contract: AnalysisScopeContract
    required_evidence_ids: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    budget: PlanBudget
    missing_inputs: tuple[str, ...]
    clarification_questions: tuple[str, ...]

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, default=str))

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass
class _StepBuilder:
    titles: list[str]
    tool: str
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]
    evidence_ids: list[str]
    dependency_keys: list[str]
    required: bool
    success_criteria: list[str]
    estimated_result_limit: int


_LOT_ID_PATTERN = re.compile(
    r"\b(?:LOT[-_ ]?[A-Z0-9]+(?:-[A-Z0-9]+)*|L\d{4,}-\d{3,})\b",
    re.IGNORECASE,
)
_DATE_TOOLS = {
    "get_fab_overview",
    "get_yield_trend",
    "get_equipment_health",
    "get_equipment_productivity",
    "get_process_capability",
    "get_defect_pareto",
    "get_recent_excursions",
    "get_sensor_summary",
    "get_process_pass_rate",
}


def _analysis_scope_contract(route: IntentRoute, resolved: dict[str, Any] | None = None) -> AnalysisScopeContract:
    resolution = route.scope_resolution
    resolved = resolved or {}
    primary_type = "lot" if route.intent == "lot_trace" and resolved.get("lot_id") else "process" if route.intent == "sop_lookup" and route.process_steps else resolution.scope_type
    primary_ids = (str(resolved["lot_id"]).upper(),) if primary_type == "lot" else tuple(route.process_steps) if primary_type == "process" and route.intent == "sop_lookup" else resolution.resolved_ids
    labels: list[str] = list(primary_ids)
    if primary_type == "process":
        for process_step in route.process_steps:
            labels.extend(PROCESS_ALIASES.get(process_step, ()))
        context_only_tools = ("get_fab_overview", "get_yield_trend")
    elif resolution.scope_type == "equipment":
        context_only_tools = ()
    else:
        context_only_tools = ()
    return AnalysisScopeContract(
        primary_scope_type=primary_type,
        primary_scope_ids=primary_ids,
        primary_scope_labels=tuple(dict.fromkeys(str(item) for item in labels if item)),
        context_only_tools=context_only_tools,
    )


def _plan_id(question: str, route: IntentRoute, selection: PlaybookSelection) -> str:
    playbook = selection.selected_playbook
    identity = {
        "question": " ".join(question.split()),
        "route": route.to_dict(),
        "playbook_id": playbook.playbook_id if playbook else None,
        "playbook_version": playbook.playbook_version if playbook else None,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"plan-{digest}"


def _lot_ids(question: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0).upper().replace(" ", "-") for match in _LOT_ID_PATTERN.finditer(question)))


def _resolved_inputs(question: str, route: IntentRoute, playbook: DomainPlaybook) -> tuple[dict[str, Any], tuple[str, ...]]:
    values: dict[str, Any] = {
        "query": question,
        "time_range": asdict(route.time_range),
    }
    if route.process_steps:
        values["process_step"] = route.process_steps[0]
    if route.equipment_ids:
        values["equipment_id"] = route.equipment_ids[0]
    lot_ids = _lot_ids(question)
    if lot_ids:
        values["lot_id"] = lot_ids[0]
    if route.scope_resolution.scope_type == "product" and route.scope_resolution.resolved_ids:
        values["product"] = route.scope_resolution.resolved_ids[0]
    missing = tuple(name for name in playbook.required_inputs if not values.get(name))
    return values, missing


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _end_exclusive(route: IntentRoute) -> str:
    return (date.fromisoformat(route.time_range.end) + timedelta(days=1)).isoformat()


def _where_filters(route: IntentRoute, timestamp_column: str, include_equipment: bool = False) -> str:
    clauses = [
        f"{timestamp_column} >= {_sql_literal(route.time_range.start)}",
        f"{timestamp_column} < {_sql_literal(_end_exclusive(route))}",
    ]
    if include_equipment and route.equipment_ids:
        clauses.append(f"equipment_id = {_sql_literal(route.equipment_ids[0])}")
    return " AND ".join(clauses)


def _manufacturing_queries(
    evidence_id: str,
    route: IntentRoute,
    resolved: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    if evidence_id == "YLD-02":
        where = _where_filters(route, "complete_time")
        if route.scope_resolution.scope_type == "product" and route.scope_resolution.resolved_ids:
            where += f" AND product = {_sql_literal(route.scope_resolution.resolved_ids[0])}"
        return ((
            "产品与技术节点良率分层",
            "SELECT product, technology_nm, COUNT(*) AS lots, SUM(wafer_count) AS wafers, "
            "ROUND(100.0 * SUM(good_wafers) / NULLIF(SUM(wafer_count), 0), 2) AS yield_pct "
            f"FROM lots WHERE {where} GROUP BY product, technology_nm ORDER BY lots DESC LIMIT 100",
        ),)
    if evidence_id == "EQP-03":
        where = _where_filters(route, "event_time", include_equipment=True)
        return ((
            "设备事件时间线",
            "SELECT equipment_id, event_time, event_type, duration_minutes, severity, reason "
            f"FROM equipment_events WHERE {where} ORDER BY event_time DESC LIMIT 100",
        ),)
    if evidence_id == "EQP-04":
        where = _where_filters(route, "run_time", include_equipment=True)
        process_clause = (
            f" AND process_step = {_sql_literal(route.process_steps[0])}"
            if route.process_steps else ""
        )
        return ((
            "设备关联产品异常",
            "SELECT lot_id, run_time, process_step, equipment_id, excursion_code, "
            "measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl "
            f"FROM process_runs WHERE {where}{process_clause} AND excursion_code IS NOT NULL "
            "ORDER BY run_time DESC LIMIT 100",
        ),)

    lot_id = resolved.get("lot_id")
    if not lot_id:
        return ()
    literal = _sql_literal(str(lot_id))
    if evidence_id == "LOT-01":
        return ((
            "批次身份与状态",
            "SELECT lot_id, product, technology_nm, route, priority, start_time, complete_time, "
            "status, wafer_count, good_wafers, yield_rate, cycle_time_hours, hold_hours "
            f"FROM lots WHERE lot_id = {literal} LIMIT 10",
        ),)
    if evidence_id == "LOT-02":
        return ((
            "批次加工路线",
            "SELECT lot_id, operation_seq, layer_name, process_step, equipment_id, chamber, recipe, "
            "run_time, queue_hours, rework_flag FROM process_runs "
            f"WHERE lot_id = {literal} ORDER BY operation_seq, run_time LIMIT 100",
        ),)
    if evidence_id == "LOT-03":
        return (
            (
                "批次制程异常",
                "SELECT lot_id, operation_seq, run_time, process_step, equipment_id, excursion_code, "
                "measurement_name, measurement_value, measurement_unit, spec_lsl, spec_usl "
                f"FROM process_runs WHERE lot_id = {literal} AND excursion_code IS NOT NULL "
                "ORDER BY operation_seq, run_time LIMIT 100",
            ),
            (
                "批次缺陷与处置",
                "SELECT lot_id, detected_time, process_step, defect_type, count, disposition "
                f"FROM defect_records WHERE lot_id = {literal} ORDER BY detected_time LIMIT 100",
            ),
            (
                "批次晶圆图模式",
                "SELECT lot_id, wafer_no, detected_time, process_step, equipment_id, pattern_class, "
                f"tested_dies, failed_dies FROM wafer_maps WHERE lot_id = {literal} "
                "ORDER BY wafer_no LIMIT 100",
            ),
        )
    return ()


def _base_parameters(
    tool: str,
    question: str,
    route: IntentRoute,
    evidence: EvidenceRequirement,
) -> tuple[dict[str, Any], dict[str, str]]:
    parameters: dict[str, Any] = {}
    sources: dict[str, str] = {}
    if tool in _DATE_TOOLS:
        parameters.update({"start": route.time_range.start, "end": route.time_range.end})
        sources.update({"start": "intent_route.time_range", "end": "intent_route.time_range"})
    if tool in {
        "get_process_pass_rate",
        "get_process_capability",
        "get_recent_excursions",
        "get_sensor_summary",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_defect_pareto",
    } and route.process_steps:
        parameters["process_step"] = route.process_steps[0]
        sources["process_step"] = "intent_route.process_steps[0]"
    if tool in {
        "get_process_pass_rate",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_recent_excursions",
        "get_sensor_summary",
    } and route.equipment_ids:
        parameters["equipment_id"] = route.equipment_ids[0]
        sources["equipment_id"] = "intent_route.equipment_ids[0]"
    if tool == "get_recent_excursions":
        parameters["limit"] = 100
        sources["limit"] = "planner.default"
    if tool == "get_defect_pareto":
        parameters["limit"] = 25
        sources["limit"] = "planner.default"
    if tool == "search_knowledge":
        parameters.update({"query": question, "limit": 10})
        sources.update({"query": "user.question", "limit": "planner.default"})
        if route.process_steps:
            parameters["process_step"] = route.process_steps[0]
            sources["process_step"] = "intent_route.process_steps[0]"
        if route.equipment_ids:
            parameters["equipment_id"] = route.equipment_ids[0]
            sources["equipment_id"] = "intent_route.equipment_ids[0]"
        if evidence.evidence_id in {"SOP-01", "SOP-02"}:
            parameters["source_types"] = ["personal", "knowledge"]
            sources["source_types"] = "playbook.evidence_scope"
        elif evidence.evidence_id == "SOP-03":
            parameters["source_types"] = ["case"]
            sources["source_types"] = "playbook.evidence_scope"
        else:
            parameters["source_types"] = ["personal", "knowledge", "case"]
            sources["source_types"] = "playbook.evidence_scope"
    return parameters, sources


def _step_semantics(tool: str, parameters: dict[str, Any], evidence_ids: tuple[str, ...] = ()) -> tuple[str, str, str]:
    """Planner-owned semantics: fixed reports only, no name-specific branches."""
    semantics = {
        "get_fab_overview": ("metric", "final_wafer_yield", "fab"),
        "get_yield_trend": ("metric", "final_wafer_yield", "week"),
        "get_process_pass_rate": ("metric", "process_run_pass_rate", "equipment" if parameters.get("equipment_id") else "process"),
        "get_process_capability": ("metric", "process_capability_cpk", "equipment_distribution"),
        "get_equipment_health": ("metric", "equipment_health", "equipment"),
        "get_equipment_productivity": ("metric", "equipment_productivity", "equipment"),
        "get_defect_pareto": ("metric", "defect_pareto", "defect_type"),
        "get_recent_excursions": ("event", "process_excursion", "event"),
        "get_sensor_summary": ("metric", "sensor_summary", "equipment_signal"),
        "search_knowledge": ("document", "knowledge_document", "document"),
    }
    if tool == "query_manufacturing_data":
        sql = str(parameters.get("sql", "")).lower()
        if "from wafer_maps" in sql:
            return ("record", "wafer_map_pattern", "wafer")
        if "from defect_records" in sql:
            return ("event", "defect_record", "defect_event")
        if "from process_runs" in sql:
            return ("event" if "excursion_code" in sql else "record", "process_excursion_record" if "excursion_code" in sql else "lot_process_history", "event" if "excursion_code" in sql else "process_run")
        if "from equipment_events" in sql:
            return ("event", "equipment_event", "event")
        if "from lots" in sql and "group by" not in sql:
            return ("record", "lot_identity", "lot")
        # Lots alone do not establish a process-level metric.  The only yield
        # template is product/fab-grain and is therefore background for a
        # process question.
        query = {
            "YLD-02": ("metric", "final_wafer_yield", "product"), "EQP-03": ("event", "equipment_event", "event"),
            "EQP-04": ("record", "process_excursion_record", "process_run"), "LOT-01": ("record", "lot_identity", "lot"),
            "LOT-02": ("record", "lot_process_history", "process_run"), "LOT-03": ("event", "lot_impact_event", "event"),
        }
        return query.get(next(iter(evidence_ids), ""), ("unknown", "unknown", "unknown"))
    return semantics.get(tool, ("unknown", "unknown", "unknown"))


def _step_scope(tool: str, parameters: dict[str, Any], evidence_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Actual result scope derived from handler parameters/template filters only."""
    values = {"fab_ids": (), "process_steps": (), "equipment_ids": (), "products": (), "lot_ids": (), "wafer_ids": (), "chambers": (), "recipes": ()}
    if tool in {"get_fab_overview", "get_process_capability", "get_equipment_health", "get_equipment_productivity", "get_defect_pareto", "get_recent_excursions", "get_sensor_summary"} and not parameters.get("process_step") and not parameters.get("equipment_id"):
        values["fab_ids"] = ("FAB",)
    if tool == "get_yield_trend" and not parameters.get("product"):
        values["fab_ids"] = ("FAB",)
    # Equipment handlers select equipment first, so do not imply a second
    # process filter merely because the planner also knows the route process.
    if parameters.get("equipment_id"):
        values["equipment_ids"] = (str(parameters["equipment_id"]).upper(),)
    elif parameters.get("process_step"):
        values["process_steps"] = (str(parameters["process_step"]).upper(),)
    if parameters.get("product"): values["products"] = (str(parameters["product"]).upper(),)
    if parameters.get("lot_id"): values["lot_ids"] = (str(parameters["lot_id"]).upper(),)
    if tool == "query_manufacturing_data":
        sql = str(parameters.get("sql", ""))
        lot = re.search(r"\blot_id\s*=\s*'([^']+)'", sql, re.I)
        process = re.search(r"\bprocess_step\s*=\s*'([^']+)'", sql, re.I)
        equipment = re.search(r"\bequipment_id\s*=\s*'([^']+)'", sql, re.I)
        product = re.search(r"\bproduct\s*=\s*'([^']+)'", sql, re.I)
        if lot: values["lot_ids"] = (lot.group(1).upper(),)
        if process: values["process_steps"] = (process.group(1).upper(),)
        if equipment: values["equipment_ids"] = (equipment.group(1).upper(),)
        if product:
            values["products"] = (product.group(1).upper(),)
            values["fab_ids"] = ()
        if not any((lot, process, equipment, product)) and "FROM lots" in sql:
            values["fab_ids"] = ("FAB",)
    return values


def _target_scope(route: IntentRoute, resolved: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    scope = {"fab_ids": (), "process_steps": (), "equipment_ids": (), "products": (), "lot_ids": (), "wafer_ids": (), "chambers": (), "recipes": ()}
    if route.scope_resolution.scope_type == "fab": scope["fab_ids"] = ("FAB",)
    elif route.intent == "sop_lookup" and route.process_steps: scope["process_steps"] = tuple(route.process_steps)
    elif route.scope_resolution.scope_type == "process": scope["process_steps"] = tuple(route.process_steps)
    elif route.scope_resolution.scope_type == "equipment": scope["equipment_ids"] = tuple(route.equipment_ids)
    elif (route.scope_resolution.scope_type == "lot" or route.intent == "lot_trace") and resolved.get("lot_id"): scope["lot_ids"] = (str(resolved["lot_id"]).upper(),)
    elif route.scope_resolution.scope_type == "product": scope["products"] = tuple(str(item).upper() for item in route.scope_resolution.resolved_ids)
    return scope


def _scope_role(actual: dict[str, tuple[str, ...]], target: dict[str, tuple[str, ...]]) -> ScopeRole:
    return "primary" if actual == target else "context_only"


def _result_limit(tool: str, parameters: dict[str, Any]) -> int:
    if tool == "search_knowledge":
        return int(parameters.get("limit", 10))
    if tool == "get_defect_pareto":
        return int(parameters.get("limit", 25))
    if tool == "get_recent_excursions":
        return int(parameters.get("limit", 100))
    return 100


def _tool_invocations(
    question: str,
    route: IntentRoute,
    resolved: dict[str, Any],
    evidence: EvidenceRequirement,
) -> tuple[tuple[str, str, dict[str, Any], dict[str, str]], ...]:
    invocations: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
    for tool in evidence.source_tools:
        if tool == "get_process_pass_rate" and not route.process_steps:
            # This optional evidence only has a meaningful, fixed scope when a
            # route resolved a process.  Do not call it as an unfiltered proxy.
            continue
        if tool == "query_manufacturing_data":
            for title, sql in _manufacturing_queries(evidence.evidence_id, route, resolved):
                invocations.append((
                    tool,
                    title,
                    {"sql": sql},
                    {"sql": f"planner.template.{evidence.evidence_id}"},
                ))
            continue
        parameters, sources = _base_parameters(tool, question, route, evidence)
        if tool == "get_yield_trend" and route.scope_resolution.scope_type == "product" and route.scope_resolution.resolved_ids:
            parameters["product"] = route.scope_resolution.resolved_ids[0]
            sources["product"] = "intent_route.scope_resolution"
        invocations.append((tool, evidence.name, parameters, sources))
    return tuple(invocations)


def _ready_steps(
    question: str,
    route: IntentRoute,
    playbook: DomainPlaybook,
    resolved: dict[str, Any],
) -> tuple[PlanStep, ...]:
    builders: dict[str, _StepBuilder] = {}
    scope_contract = _analysis_scope_contract(route, resolved)
    previous_required_group_keys: tuple[str, ...] = ()

    for evidence in playbook.evidence_requirements:
        current_group_keys: list[str] = []
        for tool, title, parameters, parameter_sources in _tool_invocations(question, route, resolved, evidence):
            key = json.dumps({"tool": tool, "parameters": parameters}, ensure_ascii=False, sort_keys=True)
            current_group_keys.append(key)
            builder = builders.get(key)
            if builder is None:
                builder = _StepBuilder(
                    titles=[],
                    tool=tool,
                    parameters=parameters,
                    parameter_sources=parameter_sources,
                    evidence_ids=[],
                    dependency_keys=[],
                    required=False,
                    success_criteria=[],
                    estimated_result_limit=_result_limit(tool, parameters),
                )
                builders[key] = builder
            if title not in builder.titles:
                builder.titles.append(title)
            if evidence.evidence_id not in builder.evidence_ids:
                builder.evidence_ids.append(evidence.evidence_id)
            for dependency_key in previous_required_group_keys:
                if dependency_key != key and dependency_key not in builder.dependency_keys:
                    builder.dependency_keys.append(dependency_key)
            builder.required = builder.required or evidence.required or (
                evidence.evidence_id == "YLD-05" and route.scope_resolution.scope_type in {"process", "equipment"}
            )
            for criterion in evidence.acceptance_criteria:
                if criterion not in builder.success_criteria:
                    builder.success_criteria.append(criterion)
        if current_group_keys and evidence.required:
            previous_required_group_keys = tuple(dict.fromkeys(current_group_keys))

    key_to_step_id = {key: f"S{index:02d}" for index, key in enumerate(builders, start=1)}
    return tuple(
        PlanStep(
            step_id=key_to_step_id[key],
            title=" / ".join(builder.titles),
            tool=builder.tool,
            parameters=builder.parameters,
            parameter_sources=builder.parameter_sources,
            evidence_ids=tuple(builder.evidence_ids),
            depends_on=tuple(key_to_step_id[item] for item in builder.dependency_keys),
            required=builder.required,
            success_criteria=tuple(builder.success_criteria),
            estimated_result_limit=builder.estimated_result_limit,
            scope_role=_scope_role(_step_scope(builder.tool, builder.parameters, tuple(builder.evidence_ids)), _target_scope(route, resolved)),
            evidence_kind=_step_semantics(builder.tool, builder.parameters, tuple(builder.evidence_ids))[0],
            semantic_id=_step_semantics(builder.tool, builder.parameters, tuple(builder.evidence_ids))[1],
            grain=_step_semantics(builder.tool, builder.parameters, tuple(builder.evidence_ids))[2],
            evidence_scope=_step_scope(builder.tool, builder.parameters, tuple(builder.evidence_ids)),
            evidence_start=route.time_range.start if (builder.tool != "query_manufacturing_data" or " >= '" in str(builder.parameters.get("sql", ""))) and builder.tool not in {"search_knowledge"} else None,
            evidence_end=route.time_range.end if (builder.tool != "query_manufacturing_data" or " < '" in str(builder.parameters.get("sql", ""))) and builder.tool not in {"search_knowledge"} else None,
        )
        for key, builder in builders.items()
    )


def _empty_budget() -> PlanBudget:
    return PlanBudget(
        planned_tool_calls=0,
        max_tool_calls=0,
        max_model_iterations=1,
        max_rows_per_call=100,
        per_tool_limits={},
        max_identical_parameter_calls=0,
        max_no_progress_rounds=1,
    )


def _generic_budget() -> PlanBudget:
    return PlanBudget(
        planned_tool_calls=0,
        max_tool_calls=10,
        max_model_iterations=6,
        max_rows_per_call=100,
        per_tool_limits={"*": 3, "search_knowledge": 6, "query_manufacturing_data": 5},
        max_identical_parameter_calls=1,
        max_no_progress_rounds=2,
    )


def create_execution_plan(
    question: str,
    route: IntentRoute,
    selection: PlaybookSelection,
) -> ExecutionPlan:
    plan_id = _plan_id(question, route, selection)
    playbook = selection.selected_playbook
    scope_contract = _analysis_scope_contract(route)
    if route.scope_resolution.scope_type == "product" and route.intent == "fab_diagnostic":
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="clarification_required",
            reason="产品范围无法由当前综合诊断的全部工具一致过滤，必须先确认分析目标。",
            route_intent=route.intent,
            playbook_id=playbook.playbook_id if playbook else None,
            playbook_version=playbook.playbook_version if playbook else None,
            scope_contract=scope_contract,
            required_evidence_ids=(),
            steps=(),
            budget=_empty_budget(),
            missing_inputs=("product_analysis_scope",),
            clarification_questions=(
                "已识别产品范围。请确认只分析该产品的良率和周期，或补充需要关联的具体制程。",
            ),
        )
    if selection.status == "clarification_required" or route.intent == "unknown" or route.clarification_needed:
        if route.scope_resolution.clarification_needed:
            missing_inputs = ("manufacturing_scope",)
            reason = "Router 检测到无法映射的制造范围，确认范围前不得执行工具。"
        elif route.intent == "capability_excursion" and not route.process_steps:
            missing_inputs = ("process_step",)
            reason = "Domain Playbook 的必需输入尚不完整。"
        elif selection.status == "clarification_required":
            missing_inputs = ("primary_intent",)
            reason = "路由匹配多个 Domain Playbook，必须先确认主分析目标。"
        else:
            missing_inputs = ("primary_intent",)
            reason = "Router 未识别明确分析目标，必须先补充问题范围。"
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="clarification_required",
            reason=reason,
            route_intent=route.intent,
            playbook_id=None,
            playbook_version=None,
            scope_contract=scope_contract,
            required_evidence_ids=(),
            steps=(),
            budget=_empty_budget(),
            missing_inputs=missing_inputs,
            clarification_questions=route.clarification_questions,
        )
    if playbook is None:
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="unsupported",
            reason="当前 Planner 仅实例化六类 Domain Playbook；该问题继续使用通用 Agent 路径。",
            route_intent=route.intent,
            playbook_id=None,
            playbook_version=None,
            scope_contract=scope_contract,
            required_evidence_ids=(),
            steps=(),
            budget=_generic_budget(),
            missing_inputs=(),
            clarification_questions=route.clarification_questions,
        )

    resolved, missing = _resolved_inputs(question, route, playbook)
    scope_contract = _analysis_scope_contract(route, resolved)
    if missing:
        questions = list(route.clarification_questions)
        labels = {
            "process_step": "请指定要分析的制程站点。",
            "lot_id": "请提供要追踪的完整批次编号。",
            "time_range": "请提供分析起止日期。",
            "query": "请说明要查询的规范主题。",
        }
        for name in missing:
            question_text = labels.get(name, f"请补充 {name}。")
            if question_text not in questions:
                questions.append(question_text)
        return ExecutionPlan(
            plan_id=plan_id,
            schema_version="1.1",
            planner_version="1.1.0",
            status="clarification_required",
            reason="Domain Playbook 的必需输入尚不完整。",
            route_intent=route.intent,
            playbook_id=playbook.playbook_id,
            playbook_version=playbook.playbook_version,
            scope_contract=scope_contract,
            required_evidence_ids=tuple(
                item.evidence_id for item in playbook.evidence_requirements if item.required
            ),
            steps=(),
            budget=_empty_budget(),
            missing_inputs=missing,
            clarification_questions=tuple(questions),
        )

    steps = _ready_steps(question, route, playbook, resolved)
    planned_calls = len(steps)
    planned_per_tool = Counter(step.tool for step in steps)
    return ExecutionPlan(
        plan_id=plan_id,
        schema_version="1.1",
        planner_version="1.1.0",
        status="ready",
        reason="已将路由范围和 Domain Playbook 证据模板实例化为确定性工具计划。",
        route_intent=route.intent,
        playbook_id=playbook.playbook_id,
        playbook_version=playbook.playbook_version,
        scope_contract=scope_contract,
        required_evidence_ids=tuple(
            item.evidence_id for item in playbook.evidence_requirements if item.required
        ),
        steps=steps,
        budget=PlanBudget(
            planned_tool_calls=planned_calls,
            max_tool_calls=min(16, planned_calls + 2),
            max_model_iterations=6,
            max_rows_per_call=100,
            per_tool_limits={tool: count + 1 for tool, count in planned_per_tool.items()},
            max_identical_parameter_calls=1,
            max_no_progress_rounds=2,
        ),
        missing_inputs=(),
        clarification_questions=(),
    )


def planner_system_message(plan: ExecutionPlan) -> str:
    return (
        "以下 execution_plan 是 Router 与 Domain Playbook 的确定性实例化结果，不是已执行证据。"
        "status=ready 时按 depends_on 满足依赖，优先完成 required=true 的步骤，并使用给定参数。"
        "任一步无法满足 success_criteria 时必须报告证据缺口。"
        "budget 由运行时守卫强制执行，不得超过总调用、单工具、相同参数和无进展轮次限制。"
        "status=clarification_required 时先提出 clarification_questions，不调用工具。"
        "status=unsupported 时继续遵守通用 Agent 规则。\n"
        f"execution_plan={plan.to_prompt()}"
    )
