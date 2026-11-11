"""Single source for the seven existing diagnostic evidence declarations."""

from __future__ import annotations
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class EvidenceRequirement:
    evidence_id: str
    name: str
    purpose: str
    source_tools: tuple[str, ...]
    required_fields: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    required: bool = True


REQUIREMENTS: dict[str, tuple[EvidenceRequirement, ...]] = {
    "capability_excursion": (
        EvidenceRequirement(
            evidence_id="CAP-01",
            name="设备级制程能力",
            purpose="确认目标量测、规格、样本量、均值、波动和设备间 Cpk 差异。",
            source_tools=("get_process_capability",),
            required_fields=(
                "equipment_id",
                "samples",
                "mean_value",
                "sigma",
                "cpk",
                "metric_name",
                "metric_unit",
                "spec_lsl",
                "spec_usl",
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
                "run_time",
                "lot_id",
                "process_step",
                "equipment_id",
                "excursion_code",
                "measurement_name",
                "measurement_value",
                "measurement_unit",
                "spec_lsl",
                "spec_usl",
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
                "process_step",
                "equipment_id",
                "signal_name",
                "samples",
                "missing_samples",
                "flagged_outliers",
                "mean_value",
                "min_value",
                "max_value",
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
            required_fields=(
                "reference_id",
                "source_type",
                "source",
                "section",
                "retrieval",
            ),
            acceptance_criteria=(
                "至少包含适用制程的正式知识来源；历史案例不得替代当前制造数据。",
                "低置信度检索结果不能支持确定性结论。",
            ),
        ),
    ),
    "yield_decline": (
        EvidenceRequirement(
            evidence_id="YLD-01",
            name="工厂基线与良率趋势",
            purpose="确认时间范围、批次与晶圆样本量、总体良率和变化持续性。",
            source_tools=("get_fab_overview", "get_yield_trend"),
            required_fields=(
                "start",
                "end",
                "lots",
                "wafers",
                "yield_pct",
                "period",
                "week_start",
            ),
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
            required_fields=(
                "defect_type",
                "process_steps",
                "defect_count",
                "affected_lots",
                "share_pct",
            ),
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
    "equipment_fault": (
        EvidenceRequirement(
            evidence_id="EQP-01",
            name="设备健康概况",
            purpose="比较运行数、异常数、停机、缺陷密度和设备健康等级。",
            source_tools=("get_equipment_health",),
            required_fields=(
                "equipment_id",
                "runs",
                "excursions",
                "avg_defect_density",
                "pass_pct",
                "events",
                "downtime_minutes",
                "health",
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
                "equipment_id",
                "recorded_minutes",
                "productive_minutes",
                "productive_pct",
                "unscheduled_down_minutes",
                "scheduled_down_minutes",
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
                "equipment_id",
                "event_time",
                "event_type",
                "severity",
                "reason",
                "signal_name",
                "samples",
                "missing_samples",
                "flagged_outliers",
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
            required_fields=(
                "lot_id",
                "run_time",
                "process_step",
                "equipment_id",
                "excursion_code",
            ),
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
            required_fields=(
                "reference_id",
                "source_type",
                "source",
                "section",
                "retrieval",
            ),
            acceptance_criteria=(
                "恢复量产建议必须引用正式 SOP。",
                "历史故障案例不能证明当前部件具有相同失效模式。",
            ),
        ),
    ),
    "fab_diagnostic": (
        EvidenceRequirement(
            evidence_id="FAB-01",
            name="制造基线与趋势",
            purpose="确认分析时间、样本规模、良率、周期、Hold、异常总量及其周度变化。",
            source_tools=("get_fab_overview", "get_yield_trend"),
            required_fields=(
                "start",
                "end",
                "lots",
                "wafers",
                "yield_pct",
                "avg_cycle_hours",
                "avg_hold_hours",
                "held_lots",
                "excursions",
                "period",
                "week_start",
                "cycle_hours",
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
                "process_step",
                "equipment_id",
                "samples",
                "mean_value",
                "sigma",
                "cpk",
                "metric_name",
                "metric_unit",
                "spec_lsl",
                "spec_usl",
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
                "equipment_id",
                "runs",
                "excursions",
                "avg_defect_density",
                "pass_pct",
                "events",
                "downtime_minutes",
                "health",
                "recorded_minutes",
                "productive_minutes",
                "productive_pct",
                "unscheduled_down_minutes",
                "scheduled_down_minutes",
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
                "defect_type",
                "process_steps",
                "defect_count",
                "affected_lots",
                "share_pct",
                "run_time",
                "lot_id",
                "process_step",
                "equipment_id",
                "excursion_code",
                "measurement_name",
                "measurement_value",
                "measurement_unit",
                "spec_lsl",
                "spec_usl",
            ),
            acceptance_criteria=(
                "缺陷频次、占比和受影响批次数必须同时报告。",
                "近期异常只用于定位验证方向，不得与缺陷或良率建立未经验证的因果关系。",
            ),
        ),
    ),
    "lot_trace": (
        EvidenceRequirement(
            evidence_id="LOT-01",
            name="批次身份与状态",
            purpose="确认批次、产品、节点、路线、时间、状态、晶圆数、良率和 Hold。",
            source_tools=("query_manufacturing_data",),
            required_fields=(
                "lot_id",
                "product",
                "technology_nm",
                "route",
                "priority",
                "start_time",
                "complete_time",
                "status",
                "wafer_count",
                "good_wafers",
                "yield_rate",
                "hold_hours",
            ),
            acceptance_criteria=(
                "查询结果必须精确匹配目标 lot_id。",
                "找不到批次时停止推断并请求核对编号。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="LOT-02",
            name="加工路线与设备暴露",
            purpose="按 operation_seq 重建站点、设备、腔体、配方、时间和返工。",
            source_tools=("query_manufacturing_data",),
            required_fields=(
                "lot_id",
                "operation_seq",
                "layer_name",
                "process_step",
                "equipment_id",
                "chamber",
                "recipe",
                "run_time",
                "queue_hours",
                "rework_flag",
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
                "excursion_code",
                "measurement_name",
                "measurement_value",
                "spec_lsl",
                "spec_usl",
                "defect_type",
                "count",
                "disposition",
                "wafer_no",
                "pattern_class",
                "failed_dies",
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
            required_fields=(
                "reference_id",
                "source_type",
                "source",
                "section",
                "retrieval",
            ),
            acceptance_criteria=(
                "优先引用生效中的批次 Hold 与处置规范。",
                "批次未暴露于异常设备或异常发生在加工之后时，不得纳入影响范围。",
            ),
        ),
    ),
    "sop_lookup": (
        EvidenceRequirement(
            evidence_id="SOP-01",
            name="正式规范来源",
            purpose="检索与问题、制程和设备范围匹配的 SOP、控制计划或治理规范。",
            source_tools=("search_knowledge",),
            required_fields=(
                "reference_id",
                "source_type",
                "source",
                "title",
                "section",
                "content",
                "retrieval",
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
                "status",
                "version",
                "effective_date",
                "owner",
                "process_steps",
                "equipment_families",
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
            required_fields=(
                "reference_id",
                "source_type",
                "problem",
                "solution",
                "result",
                "summary",
                "retrieval",
            ),
            acceptance_criteria=(
                "案例必须标记为历史经验，并说明与当前场景的相似点和差异。",
                "案例与正式规范冲突时以生效规范为准。",
            ),
            required=False,
        ),
    ),
    "defect_analysis": (
        EvidenceRequirement(
            evidence_id="DEF-01",
            name="缺陷类型分布",
            purpose="确认各缺陷类型的数量、占比和影响批次，定位主要缺陷。",
            source_tools=("get_defect_pareto",),
            required_fields=(
                "defect_type",
                "defect_count",
                "affected_lots",
                "share_pct",
            ),
            acceptance_criteria=(
                "至少返回一种缺陷类型及其数量与占比。",
                "结论中的首要缺陷必须能对应到 pareto 中的具体类型。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="DEF-02",
            name="缺陷相关异常记录",
            purpose=(
                "查看同期异常记录中的缺陷代码、量测值和规格边界，判断缺陷是否集中在"
                "特定设备或量测项。"
            ),
            source_tools=("get_recent_excursions",),
            required_fields=(
                "run_time",
                "equipment_id",
                "excursion_code",
                "measurement_name",
                "measurement_value",
                "spec_lsl",
                "spec_usl",
            ),
            acceptance_criteria=(
                "异常记录包含设备、缺陷代码与规格对比字段。",
                "仅凭时间重合不得直接断言因果。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="DEF-03",
            name="设备健康与异常频次",
            purpose="对比各设备的健康状态、异常次数与通过率，识别缺陷高发设备。",
            source_tools=("get_equipment_health",),
            required_fields=("equipment_id", "health", "excursions", "pass_pct"),
            acceptance_criteria=(
                "返回设备级异常次数与健康状态。",
                "不得把相关性表述为已证明的设备根因。",
            ),
        ),
        EvidenceRequirement(
            evidence_id="DEF-04",
            name="缺陷处置知识",
            purpose="检索缺陷类型对应的处置经验、验收标准与历史案例。",
            source_tools=("search_knowledge",),
            required_fields=("reference_id", "title", "excerpt"),
            acceptance_criteria=(
                "返回可引用的知识条目；为空时必须明确说明。",
                "历史案例只能作为参考，不替代厂内规范。",
            ),
            required=False,
        ),
    ),
}

_TOOL_REPLACEMENTS = {
    "YLD-02": ("get_product_yield_breakdown",),
    "EQP-03": ("get_equipment_event_timeline",),
    "EQP-04": ("get_equipment_excursion_history",),
    "LOT-01": ("get_lot_identity",),
    "LOT-02": ("get_lot_process_history",),
    "LOT-03": (
        "get_lot_excursion_history",
        "get_lot_defect_history",
        "get_lot_wafer_map_patterns",
    ),
}


def named_requirements(playbook: object) -> tuple[EvidenceRequirement, ...]:
    requirements: list[EvidenceRequirement] = []
    for requirement in playbook.evidence_requirements:
        tools = _TOOL_REPLACEMENTS.get(requirement.evidence_id)
        if tools is None:
            if "query_manufacturing_data" in requirement.source_tools:
                raise ValueError(
                    f"named playbook does not declare {requirement.evidence_id}"
                )
            requirements.append(requirement)
            continue
        replaced: list[str] = []
        for tool in requirement.source_tools:
            if tool == "query_manufacturing_data":
                replaced.extend(tools)
            else:
                replaced.append(tool)
        requirements.append(replace(requirement, source_tools=tuple(replaced)))
    return tuple(requirements)
