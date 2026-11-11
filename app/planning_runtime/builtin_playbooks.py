"""Existing domain declarations, preserved pending MOD-031 policy review."""
from __future__ import annotations

from .playbook_contracts import DomainPlaybook
from ..skills.policies.manufacturing import REQUIREMENTS


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
    evidence_requirements=REQUIREMENTS['capability_excursion'],
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
    evidence_requirements=REQUIREMENTS['yield_decline'],
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
    evidence_requirements=REQUIREMENTS['equipment_fault'],
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
    evidence_requirements=REQUIREMENTS['fab_diagnostic'],
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
    evidence_requirements=REQUIREMENTS['lot_trace'],
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
    evidence_requirements=REQUIREMENTS['sop_lookup'],
    analysis_questions=(
        "用户要查的是强制要求、操作步骤、规格门槛还是历史经验？",
        "文档版本、状态、生效日期和适用制程是否匹配？",
        "多个来源是否冲突，哪一项具有更高权威性？",
        "哪些内容来自正式规范，哪些仅来自历史案例？",
    ),
    answer_sections=("适用规范", "关键要求", "适用范围与版本", "历史经验补充", "缺口与确认人"),
    safety_constraints=_COMMON_SAFETY_CONSTRAINTS,
)


DEFECT_ANALYSIS_PLAYBOOK = DomainPlaybook(
    playbook_id="PB-DEFECT-001",
    schema_version="1.0",
    playbook_version="1.0.0",
    released_at="2026-11-05",
    intent="defect_analysis",
    title="缺陷分布与设备关联分析",
    objective=(
        "确认缺陷类型构成、主要缺陷的同期异常与设备分布，判断哪些设备或工序可能"
        "贡献了主要缺陷；设备级归因只能作为待验证假设。"
    ),
    required_inputs=("time_range",),
    evidence_requirements=REQUIREMENTS['defect_analysis'],
    analysis_questions=(
        "缺陷类型的构成与占比如何，哪一类最值得优先处理？",
        "主要缺陷是否集中在特定设备或工序？",
        "异常记录与缺陷类型是否存在时间与设备上的重合？",
        "现有证据是否足以支持设备级根因判断，还缺哪些证据？",
    ),
    answer_sections=("缺陷构成", "设备关联", "待验证假设", "证据限制", "建议"),
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
        DEFECT_ANALYSIS_PLAYBOOK,
    )
}
