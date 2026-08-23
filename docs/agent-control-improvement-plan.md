# Agent 会话控制、范围证据与执行效率改善方案

状态：`AGENT-036` 已实施；其余任务仍待逐任务确认。本文定义当前产品的改进边界，不授权直接实施后续任务；不迁移至 Rasa 或其他 Agent 框架。

## 问题依据

以下记录均来自当前项目的合成非生产数据与真实运行 Trace。

| 链路 | 观察 | 结论 |
|---|---|---|
| Router 失败 `1e0023f6-f88b-4195-ba1a-72809c995a34` | 用户依次询问“介绍一下你自己”→“你有什么功能”→“具体一点”。上下文模型正确输出 `intent_hint=conversation` 和 `answer_meta(capabilities,detailed)`，但扩写文本含“文档”，确定性 Router 改判 `sop_lookup`，TurnDecision 又静默派生 `route_task`。 | 扩写文本被当作新的任务触发器，且多个组件都能改写最终决策。 |
| 通用问题 `9a59da29-4de3-4a03-9f28-581d257bd7de` | 1 次模型轮次、2 次检索、3,734 tokens，首答 3.30 秒、总计 8.35 秒。 | 通用知识路径可作为延迟和 Token 基线。 |
| CMP 产线 `74b30c09-0502-423d-b6fc-03f172ef3c2f` | `yield_decline/PB-YIELD-001`，3 次模型轮次、5 个工具、43,874 tokens，首答/总计约 24.62 秒。计划把整厂概览和良率趋势标为 `context_only`，最终回答仍把整厂良率称为 CMP 良率；产品 SQL 也没有制程过滤。 | 计划的范围角色未被 Validator/Synthesizer 强制执行，制程事实存在证据范围越界。 |
| 整厂综合 `f898a8b9-05d9-4fde-abf3-0d33e66dc267` | `fab_diagnostic/PB-FAB-001`，2 次模型轮次、7 个工具、42,580 tokens，首答/总计约 24.58 秒。 | 整厂范围与工具口径一致；延迟主要来自模型选择工具及最终综合，而非工具执行。 |

## 目标架构

保留现有 `Intent Router → Playbook → ExecutionPlan → Evidence Validator → Answer Synthesizer` 主体。其前增加唯一的会话控制决策点 `DecisionArbiter`，其后禁止其他组件静默改写决策类型。

```text
原始用户文本 + 可见会话状态 + 受限上下文命令
                    │
                    ▼
             DecisionArbiter（唯一决策权）
                    │
      ┌─────────────┼──────────────┐
      ▼             ▼              ▼
  元对话/修复    澄清/回忆      已确认制造任务
  确定性回答                    Intent Router
                                      │
                                      ▼
                         Playbook → Plan → 证据 → 综合
```

采用 Rasa CALM 启发的概念，但不引入 Rasa 运行时或进行框架迁移：

- **command**：仅使用经过校验的 `answer_meta`、`continue_flow`、`start_task`、`clarify`、`recall_history` 等受限命令，不传递自由工具参数。
- **active flow**：记录当前会话的活动目标，例如 `assistant_capabilities`；追问默认继续活动目标，显式新任务才切换。
- **guard**：任务 Flow 的启动条件同时检查原始用户文本、活动目标和结构化命令；模型扩写中新出现的“文档/知识库/规范”等词不能单独启动 SOP Flow。
- **repair pattern**：把“具体一点”、纠正、取消、切换任务、回答复盘和澄清作为会话修复模式，而非再次把短语当完整制造任务路由。

原始用户文本决定言语行为和任务切换；解析后的 `resolved_text` 只补全已确认 Flow 的范围、时间、参数。所有候选决策必须带 `origin=original_text|history|model_expansion`，仲裁应记录选中、拒绝和策略理由，但不得保存模型思维正文、凭据或其他敏感数据。

## 分解任务与依赖

| 任务 | 目标 | 依赖 |
|---|---|---|
| `AGENT-036` | 已建立唯一 `DecisionArbiter`、活动 Flow、来源追踪、Guard 与修复模式，消除 Router/TurnDecision 多重改写；真实失败回放、变形扩写与显式任务切换均离线验证。 | 已完成 |
| `AGENT-037` | 已完成范围角色和指标语义治理，制程结论不能引用整厂背景数据。 | 无 |
| `AGENT-038` | 已完成 `ready` 计划确定性执行、仅综合模型路径与 Prompt 压缩。 | `AGENT-037` |
| `OBS-017` | 已完成审计/TurnDecision schema 分离、候选仲裁、三类引用计数、六阶段耗时与旧日志兼容。 | `AGENT-036`、`AGENT-038` |
| `QA-004` | 已建立 7-case 脱敏离线 Trace 回放与黄金矩阵，并以三条真实链路的 HTTP 系统测试跨层验证流式与持久化。 | `AGENT-036`、`AGENT-037`、`AGENT-038`、`OBS-017` |

`DEPLOY-012` 仅在这些当前队列任务及其测试完成后执行，作为 CI 收口。

## 非目标

- 不增加无限增长的追问或关键词词典。
- 不进行完整 Rasa、LangGraph 或其他框架迁移，不替换现有 Planner、Playbook 或 Evidence 架构。
- 不降低只读工具、范围确认、循环守卫、证据门禁或未验证结论的流式保护。
- 不在普通 CI 中调用真实 LLM、外网或生产数据；性能比较使用固定的脱敏合成 Trace 与基线报告。

## 风险与回退

- 仲裁错误可能把真正制造请求留在元对话 Flow；以显式 `start_task`、Guard、冲突澄清和真实任务反例防止该风险。
- 范围校验可能把历史回答降级；先将不兼容声明明确标记为背景或待验证，再逐步收紧为拒绝，保留旧日志读取兼容。
- 确定性计划执行会改变模型工具选择的轨迹；保留循环 Guard、失败回退、进度流和结构化提交，并以特征开关或旧路径回退为上线保障。
- Prompt 压缩可能漏失约束；每项压缩需由离线黄金矩阵验证证据覆盖、提交结构和引用语义。

## 总体验收与验证

- Router 失败 Trace 可离线复现，且“具体一点”的模型扩写含“文档/知识库/规范”时仍继续能力 Flow；明确“查 SOP/规范”的新问题仍进入 SOP 路径。
- CMP、ETCH、设备及整厂反例中，答案不得将背景整厂指标声明为制程或设备事实；不兼容来源须被拒绝、降级或显式标为背景。
- `ready` 计划的业务工具调用由服务端按依赖顺序执行；离线测试证明没有模型选择业务工具的额外轮次，模型仅作综合提交。
- 固定合成问题相对于本文所列基线，报告 Token 和首个最终答案时延均至少降低 20%；CI 检查报告和调用次数契约，不依赖实时网络时延。
- Trace 可区分审计 schema 与 TurnDecision schema、知识来源和工具证据计数，并显示 context/routing/retrieval/tools/synthesis/stream 阶段耗时。

建议的验证命令（实施各任务时再按变更范围执行）：

```bash
python -m unittest tests.test_context_resolver tests.test_intent_router tests.test_turn_decision -v
python -m unittest discover -s tests -p 'test_*.py'
python scripts/run_quality_gate.py full
git diff --check
```
