from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Literal

from ..intent_runtime.contracts import IntentRoute


PlaybookIntent = Literal[
    "capability_excursion",
    "yield_decline",
    "equipment_fault",
    "lot_trace",
    "sop_lookup",
    "fab_diagnostic",
]
SelectionStatus = Literal["selected", "clarification_required", "unsupported"]


@dataclass(frozen=True)
class EvidenceRequirement:
    evidence_id: str
    name: str
    purpose: str
    source_tools: tuple[str, ...]
    required_fields: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class DomainPlaybook:
    playbook_id: str
    schema_version: str
    playbook_version: str
    released_at: str
    intent: PlaybookIntent
    title: str
    objective: str
    required_inputs: tuple[str, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    analysis_questions: tuple[str, ...]
    answer_sections: tuple[str, ...]
    safety_constraints: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlaybookReference:
    playbook_id: str
    playbook_version: str
    intent: str
    title: str


@dataclass(frozen=True)
class PlaybookSelection:
    status: SelectionStatus
    route_intent: str
    selected_playbook: DomainPlaybook | None
    candidate_playbooks: tuple[PlaybookReference, ...]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


_COMMON_SAFETY_CONSTRAINTS = (
    "不得执行写库、停机、放行、返工、报废或配方变更操作。",
    "停机、放行、返工、报废、配方变更和恢复量产建议必须要求对应工程与制造人员复核。",
    "相关性、时间重合和历史案例相似性只能形成假设，不能单独证明因果。",
    "缺少必需证据时必须明确列出缺口并降低结论强度，不得补造数据。",
)


CAPABILITY_EXCURSION_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-CAPABILITY-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-07-18",
    intent="capability_excursion",
    title="制程能力异常分析",
    objective="判断能力不足来自均值偏移、波动扩大、局部设备异常还是样本与口径问题，并形成可验证的根因假设。",
    required_inputs=("process_step", "time_range"),
    evidence_requirements=(
        EvidenceRequirement(
            evidence_id="CAP-01",
            name="设备级制程能力",
            purpose="确认目标量测、规格、样本量、均值、波动和设备间 Cpk 差异。",
            source_tools=("get_process_capability",),
            required_fields=(
                "equipment_id", "samples", "mean_value", "sigma", "cpk",
                "metric_name", "metric_unit", "spec_lsl", "spec_usl",
            ),
            acceptance_criteria=(
                "时间范围和制程与路由一致。",
                "至少返回一台设备，并同时报告样本量与规格限。",
                "按统一门槛区分 Cpk<1.33、1.33<=Cpk<1.67 和 Cpk>=1.67。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="CAP-02",
            name="异常批次明细",
            purpose="定位超规时间、批次、设备、异常代码和量测偏移方向。",
            source_tools=("get_recent_excursions",),
            required_fields=(
                "run_time", "lot_id", "process_step", "equipment_id", "excursion_code",
                "measurement_name", "measurement_value", "measurement_unit", "spec_lsl", "spec_usl",
            ),
            acceptance_criteria=(
                "异常明细使用与能力计算相同的制程和时间口径。",
                "明确是否集中于单设备、连续时间窗或多个设备。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="CAP-03",
            name="设备传感器上下文",
            purpose="检查能力变化是否伴随可观测设备信号异常、缺失或离群。",
            source_tools=("get_sensor_summary",),
            required_fields=(
                "process_step", "equipment_id", "signal_name", "samples",
                "missing_samples", "flagged_outliers", "mean_value", "min_value", "max_value",
            ),
            acceptance_criteria=(
                "优先覆盖低 Cpk 或超规集中的设备。",
                "传感器异常仅作为关联线索，不直接认定根因。",
            ),
            required=False,
        ),
        EvidenceRequirement(
            evidence_id="CAP-04",
            name="控制计划与历史案例",
            purpose="取得适用规格、处置要求以及经过验证的相似根因假设。",
            source_tools=("search_knowledge",),
            required_fields=("reference_id", "source_type", "source", "section", "retrieval"),
            acceptance_criteria=(
                "至少包含适用制程的正式知识来源；历史案例不得替代当前制造数据。",
                "低置信度检索结果不能支持确定性结论。",
            ),
        ),
    ),
    analysis_questions=(
        "样本量和规格口径是否足以比较设备能力？",
        "低 Cpk 主要由均值靠近规格限、sigma 扩大，还是两者共同造成？",
        "异常是否集中于单设备、特定时间段、产品或配方？",
        "传感器、维护和历史案例能否提出可验证且相互区分的根因假设？",
    ),
    answer_sections=("结论", "能力与样本证据", "异常分层", "根因假设与待验证项", "处置建议与风险"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


YIELD_DECLINE_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-YIELD-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-07-18",
    intent="yield_decline",
    title="良率下降分析",
    objective="确认良率变化是否真实，并区分产品组合、制程、设备、缺陷和小样本效应。",
    required_inputs=("time_range",),
    evidence_requirements=(
        EvidenceRequirement(
            evidence_id="YLD-01",
            name="工厂基线与良率趋势",
            purpose="确认时间范围、批次与晶圆样本量、总体良率和变化持续性。",
            source_tools=("get_fab_overview", "get_yield_trend"),
            required_fields=("start", "end", "lots", "wafers", "yield_pct", "period", "week_start"),
            acceptance_criteria=(
                "必须同时给出起止日期和批次或晶圆样本量。",
                "趋势至少区分单周波动与连续下降。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="YLD-02",
            name="产品与节点分层",
            purpose="排除产品组合变化掩盖或制造总体良率变化。",
            source_tools=("get_yield_trend", "query_manufacturing_data"),
            required_fields=("product", "technology_nm", "lots", "wafers", "yield_pct"),
            acceptance_criteria=(
                "至少按产品分层；跨节点问题还需按 technology_nm 分层。",
                "总体变化必须与产品内变化和产品权重变化分开描述。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="YLD-03",
            name="缺陷与制程贡献",
            purpose="识别主要缺陷类型、受影响批次数和可能的制程集中度。",
            source_tools=("get_defect_pareto", "get_recent_excursions"),
            required_fields=("defect_type", "process_steps", "defect_count", "affected_lots", "share_pct"),
            acceptance_criteria=(
                "Pareto 同时报告缺陷数和受影响批次数，避免单批极值误导。",
                "异常与良率同期只能作为候选关联。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="YLD-04",
            name="良率分析规范与案例",
            purpose="取得分层口径、小样本要求和已验证的相似分析方法。",
            source_tools=("search_knowledge",),
            required_fields=("reference_id", "source_type", "source", "retrieval"),
            acceptance_criteria=(
                "正式分析规范与历史案例分开引用。",
                "案例仅用于生成待验证假设。",
            ),
            required=False,
        ),
        EvidenceRequirement(
            evidence_id="YLD-05",
            name="制程运行通过率",
            purpose="当问题范围是制程或设备时，提供直接运行通过率；它不等同于最终晶圆良率。",
            source_tools=("get_process_pass_rate",),
            required_fields=("process_step", "runs", "passed_runs", "pass_pct"),
            acceptance_criteria=("必须包含目标制程、时间范围和运行样本量。",),
            required=False,
        ),
    ),
    analysis_questions=(
        "下降幅度是否超过正常周间波动，样本量是否充足？",
        "产品或技术节点权重变化能解释多少总体变化？",
        "产品内下降是否集中于制程、设备、配方、缺陷或时间窗口？",
        "是否存在与低良率同期但尚未证明因果的设备或异常事件？",
    ),
    answer_sections=("结论", "趋势与样本", "产品组合分解", "缺陷与制程分层", "根因假设与后续验证"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


EQUIPMENT_FAULT_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-EQUIPMENT-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-07-18",
    intent="equipment_fault",
    title="设备故障与健康分析",
    objective="连接设备事件、E10 状态、传感器和产品影响，区分偶发报警、持续退化与维护后复发。",
    required_inputs=("time_range",),
    evidence_requirements=(
        EvidenceRequirement(
            evidence_id="EQP-01",
            name="设备健康概况",
            purpose="比较运行数、异常数、停机、缺陷密度和设备健康等级。",
            source_tools=("get_equipment_health",),
            required_fields=(
                "equipment_id", "runs", "excursions", "avg_defect_density",
                "pass_pct", "events", "downtime_minutes", "health",
            ),
            acceptance_criteria=(
                "目标设备与同族设备使用相同时间范围比较。",
                "不得只根据健康标签下结论，必须引用底层计数与时长。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="EQP-02",
            name="E10 生产状态",
            purpose="区分生产、计划停机和非计划停机，并量化生产效率影响。",
            source_tools=("get_equipment_productivity",),
            required_fields=(
                "equipment_id", "recorded_minutes", "productive_minutes", "productive_pct",
                "unscheduled_down_minutes", "scheduled_down_minutes",
            ),
            acceptance_criteria=(
                "记录时间覆盖度必须足以支持比例比较。",
                "计划停机与非计划停机分开报告。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="EQP-03",
            name="事件与传感器时间线",
            purpose="重建设备报警、维护和关键传感器异常的先后关系。",
            source_tools=("query_manufacturing_data", "get_sensor_summary"),
            required_fields=(
                "equipment_id", "event_time", "event_type", "severity", "reason",
                "signal_name", "samples", "missing_samples", "flagged_outliers",
            ),
            acceptance_criteria=(
                "事件和传感器必须限定到目标设备及同一时间窗口。",
                "维护后复发需明确维护前、维护时和维护后的证据。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="EQP-04",
            name="产品影响",
            purpose="确认故障是否伴随制程超规、缺陷或受影响批次。",
            source_tools=("get_recent_excursions", "query_manufacturing_data"),
            required_fields=("lot_id", "run_time", "process_step", "equipment_id", "excursion_code"),
            acceptance_criteria=(
                "设备事件和产品异常按时间及暴露关系对齐。",
                "无产品影响证据时不得声称已经影响良率或批次质量。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="EQP-05",
            name="设备恢复 SOP 与案例",
            purpose="取得恢复检查、签核要求和相似故障验证方法。",
            source_tools=("search_knowledge",),
            required_fields=("reference_id", "source_type", "source", "section", "retrieval"),
            acceptance_criteria=(
                "恢复量产建议必须引用正式 SOP。",
                "历史故障案例不能证明当前部件具有相同失效模式。",
            ),
        ),
    ),
    analysis_questions=(
        "故障是偶发、重复、持续退化还是维护后复发？",
        "非计划停机和生产效率相对同族设备是否显著异常？",
        "报警、传感器变化与产品异常的先后顺序是什么？",
        "哪些候选故障模式可通过校准、监控片或部件检查相互区分？",
    ),
    answer_sections=("结论", "设备健康与停机", "事件和传感器时间线", "产品影响", "故障假设与恢复验证"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


FAB_DIAGNOSTIC_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-FAB-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-07-18",
    intent="fab_diagnostic",
    title="制造综合诊断与改善优先级",
    objective="从产出、良率、周期、Hold、能力、设备损失、缺陷和异常多个维度识别当前制造短板，并形成有证据边界的改善优先级。",
    required_inputs=("time_range",),
    evidence_requirements=(
        EvidenceRequirement(
            evidence_id="FAB-01",
            name="制造基线与趋势",
            purpose="确认分析时间、样本规模、良率、周期、Hold、异常总量及其周度变化。",
            source_tools=("get_fab_overview", "get_yield_trend"),
            required_fields=(
                "start", "end", "lots", "wafers", "yield_pct", "avg_cycle_hours",
                "avg_hold_hours", "held_lots", "excursions", "period", "week_start", "cycle_hours",
            ),
            acceptance_criteria=(
                "必须报告起止日期、批次和晶圆样本量。",
                "当前总体值必须与周度趋势结合，不得仅凭单点指标判断改善方向。",
                "制程级请求中的整厂基线只作为背景，不得表述为该制程自身的良率、周期或 Hold 指标。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="FAB-02",
            name="全站点制程能力短板",
            purpose="按设备和关键量测比较样本量、均值、波动、规格与 Cpk，定位能力改善优先级。",
            source_tools=("get_process_capability",),
            required_fields=(
                "process_step", "equipment_id", "samples", "mean_value", "sigma", "cpk",
                "metric_name", "metric_unit", "spec_lsl", "spec_usl",
            ),
            acceptance_criteria=(
                "覆盖用户请求的制程范围；整厂请求覆盖全部可用站点，制程级请求只比较该制程设备。",
                "优先级同时考虑 Cpk、样本量、均值偏移和 sigma，不得只按单一最低值排序。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="FAB-03",
            name="设备健康与生产率损失",
            purpose="连接运行、异常、缺陷密度、停机、健康等级和 SEMI E10 状态，识别设备侧损失。",
            source_tools=("get_equipment_health", "get_equipment_productivity"),
            required_fields=(
                "equipment_id", "runs", "excursions", "avg_defect_density", "pass_pct",
                "events", "downtime_minutes", "health", "recorded_minutes", "productive_minutes",
                "productive_pct", "unscheduled_down_minutes", "scheduled_down_minutes",
            ),
            acceptance_criteria=(
                "设备健康和生产率使用一致时间范围，并区分计划与非计划停机。",
                "设备风险排序同时报告底层计数、时长和覆盖时间，不得仅引用健康标签。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="FAB-04",
            name="质量损失与近期异常集中度",
            purpose="结合缺陷 Pareto、受影响批次和近期超规记录，定位质量改善候选制程。",
            source_tools=("get_defect_pareto", "get_recent_excursions"),
            required_fields=(
                "defect_type", "process_steps", "defect_count", "affected_lots", "share_pct",
                "run_time", "lot_id", "process_step", "equipment_id", "excursion_code",
                "measurement_name", "measurement_value", "measurement_unit", "spec_lsl", "spec_usl",
            ),
            acceptance_criteria=(
                "缺陷频次、占比和受影响批次数必须同时报告。",
                "近期异常只用于定位验证方向，不得与缺陷或良率建立未经验证的因果关系。",
            ),
        ),
    ),
    analysis_questions=(
        "当前良率、周期、Hold 和异常相对近期趋势的主要偏离是什么？",
        "哪些站点和设备同时存在低 Cpk、均值偏移或波动扩大？",
        "哪些设备的非计划停机、低生产率和产品异常风险同时较高？",
        "缺陷 Pareto 与近期异常分别集中在哪些制程，二者有哪些待验证的交集？",
        "按影响、证据强度、实施风险和验证成本排序后，前三项改善机会是什么？",
    ),
    answer_sections=("执行摘要", "制造基线与趋势", "能力和设备风险排序", "质量损失集中度", "改善优先级", "证据限制与验证计划"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


LOT_TRACE_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-LOT-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-07-18",
    intent="lot_trace",
    title="批次追踪与影响范围分析",
    objective="重建批次主数据、加工路线、设备暴露、异常、缺陷和 Hold 处置，不越过可证明的影响边界。",
    required_inputs=("lot_id",),
    evidence_requirements=(
        EvidenceRequirement(
            evidence_id="LOT-01",
            name="批次身份与状态",
            purpose="确认批次、产品、节点、路线、时间、状态、晶圆数、良率和 Hold。",
            source_tools=("query_manufacturing_data",),
            required_fields=(
                "lot_id", "product", "technology_nm", "route", "priority", "start_time",
                "complete_time", "status", "wafer_count", "good_wafers", "yield_rate", "hold_hours",
            ),
            acceptance_criteria=("查询结果必须精确匹配目标 lot_id。", "找不到批次时停止推断并请求核对编号。"),
        ),
        EvidenceRequirement(
            evidence_id="LOT-02",
            name="加工路线与设备暴露",
            purpose="按 operation_seq 重建站点、设备、腔体、配方、时间和返工。",
            source_tools=("query_manufacturing_data",),
            required_fields=(
                "lot_id", "operation_seq", "layer_name", "process_step", "equipment_id",
                "chamber", "recipe", "run_time", "queue_hours", "rework_flag",
            ),
            acceptance_criteria=(
                "路线按 operation_seq 和 run_time 排序。",
                "重复步骤必须区分正常重复与返工。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="LOT-03",
            name="异常、缺陷与晶圆图",
            purpose="定位该批次的超规、缺陷、处置和空间模式。",
            source_tools=("query_manufacturing_data",),
            required_fields=(
                "excursion_code", "measurement_name", "measurement_value", "spec_lsl", "spec_usl",
                "defect_type", "count", "disposition", "wafer_no", "pattern_class", "failed_dies",
            ),
            acceptance_criteria=(
                "只汇总目标批次记录，并保留异常发生的制程与时间。",
                "缺陷处置记录与工程建议必须明确区分。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="LOT-04",
            name="Hold 与处置规范",
            purpose="验证围堵边界、复测、返工、放行和报废所需审批。",
            source_tools=("search_knowledge",),
            required_fields=("reference_id", "source_type", "source", "section", "retrieval"),
            acceptance_criteria=(
                "优先引用生效中的批次 Hold 与处置规范。",
                "批次未暴露于异常设备或异常发生在加工之后时，不得纳入影响范围。",
            ),
        ),
    ),
    analysis_questions=(
        "批次编号是否唯一匹配，当前状态和产品口径是什么？",
        "完整路线、返工和设备暴露顺序是什么？",
        "异常、缺陷或 Hold 在路线中的哪个时间点发生？",
        "基于暴露关系和最近合格检查点，可证明的影响边界是什么？",
    ),
    answer_sections=("批次状态", "加工路线", "异常与缺陷", "影响范围", "处置要求与待确认项"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


SOP_LOOKUP_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-SOP-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-07-18",
    intent="sop_lookup",
    title="SOP 与控制规范查询",
    objective="返回适用、可定位、可引用的正式知识，并将规范要求与历史经验明确分离。",
    required_inputs=("query",),
    evidence_requirements=(
        EvidenceRequirement(
            evidence_id="SOP-01",
            name="正式规范来源",
            purpose="检索与问题、制程和设备范围匹配的 SOP、控制计划或治理规范。",
            source_tools=("search_knowledge",),
            required_fields=(
                "reference_id", "source_type", "source", "title", "section", "content", "retrieval",
            ),
            acceptance_criteria=(
                "至少一个 knowledge 或 personal 正式文档结果具有非低置信度。",
                "回答中的规范性要求必须逐项引用 reference_id。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="SOP-02",
            name="版本与适用范围",
            purpose="确认文档状态、版本、生效日期、所有者、制程和设备适用范围。",
            source_tools=("search_knowledge",),
            required_fields=(
                "status", "version", "effective_date", "owner", "process_steps", "equipment_families",
            ),
            acceptance_criteria=(
                "存在多个版本或冲突要求时优先使用生效且权威等级更高的来源。",
                "缺少版本或适用范围时必须标记为待文档所有者确认。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="SOP-03",
            name="历史案例补充",
            purpose="提供执行经验、验证方法和常见失效模式，但不替代正式要求。",
            source_tools=("search_knowledge",),
            required_fields=("reference_id", "source_type", "problem", "solution", "result", "summary", "retrieval"),
            acceptance_criteria=(
                "案例必须标记为历史经验，并说明与当前场景的相似点和差异。",
                "案例与正式规范冲突时以生效规范为准。",
            ),
            required=False,
        ),
    ),
    analysis_questions=(
        "用户要查的是强制要求、操作步骤、规格门槛还是历史经验？",
        "文档版本、状态、生效日期和适用制程是否匹配？",
        "多个来源是否冲突，哪一项具有更高权威性？",
        "哪些内容来自正式规范，哪些仅来自历史案例？",
    ),
    answer_sections=("适用规范", "关键要求", "适用范围与版本", "历史经验补充", "缺口与确认人"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


DOMAIN_PLAYBOOKS: dict[str, DomainPlaybook] = {
    playbook.intent: playbook
    for playbook in (
        CAPABILITY_EXCURSION_PLAYBOOK,
        YIELD_DECLINE_PLAYBOOK,
        EQUIPMENT_FAULT_PLAYBOOK,
        FAB_DIAGNOSTIC_PLAYBOOK,
        LOT_TRACE_PLAYBOOK,
        SOP_LOOKUP_PLAYBOOK,
    )
}


def _reference(playbook: DomainPlaybook) -> PlaybookReference:
    return PlaybookReference(
        playbook_id=playbook.playbook_id,
        playbook_version=playbook.playbook_version,
        intent=playbook.intent,
        title=playbook.title,
    )


def select_playbook(route: IntentRoute) -> PlaybookSelection:
    selected = DOMAIN_PLAYBOOKS.get(route.intent)
    if selected is not None:
        return PlaybookSelection(
            status="selected",
            route_intent=route.intent,
            selected_playbook=selected,
            candidate_playbooks=(_reference(selected),),
            reason="路由意图与版本化 Domain Playbook 精确匹配。",
        )

    if route.intent == "ambiguous":
        candidates = tuple(
            _reference(DOMAIN_PLAYBOOKS[intent])
            for intent in route.candidate_intents
            if intent in DOMAIN_PLAYBOOKS
        )
        if candidates:
            return PlaybookSelection(
                status="clarification_required",
                route_intent=route.intent,
                selected_playbook=None,
                candidate_playbooks=candidates,
                reason="多个 Domain Playbook 同时匹配；澄清主目标前不执行任一模板。",
            )

    return PlaybookSelection(
        status="unsupported",
        route_intent=route.intent,
        selected_playbook=None,
        candidate_playbooks=(),
        reason="当前六类 Domain Playbook 不覆盖该意图，继续使用通用 Agent 规则。",
    )


def playbook_system_message(selection: PlaybookSelection) -> str:
    return (
        "以下是 Domain Playbook 选择结果。Playbook 是取证与回答契约，不是执行结果，也不证明任何制造事实。"
        "status=selected 时，在形成结论前覆盖全部 required=true 的证据；无法取得时必须列出缺口。"
        "status=clarification_required 时先澄清，不得混合执行候选模板。"
        "不得绕过 safety_constraints，历史案例不得替代当前数据或正式规范。\n"
        f"domain_playbook={selection.to_prompt()}"
    )
