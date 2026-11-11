# Fab Insight Agent TODO

状态核对：`experiment/parallel-platform`，2026-11-10；应用源码合入 local-Qwen `5e2d3f4`（Thinking 配置），MOD-024 工具基线 `a4739e0`，源码提交与合并关系以 Git 记录为准。

当前产品统计：共 228 个独立任务，已完成 183 个，待做 45 个；以各分类清单中的 `[x]` / `[ ]` 实算，模块化 `MOD-*` 工作包另计。

另有 4 项 `OPTIONAL` 可选候选，不计入上述主统计。

本文件是项目任务状态的总入口。详细设计继续保留在 `docs/` 的架构文档中，任务是否完成以代码、迁移和测试是否落地为准。

当前结论：`REF-035`、Memory 的 MEM-001 至 MEM-004 结构抽离，以及 `AGENT-040` 至 `AGENT-044` 答案综合改善均已完成。既有产品当前队列为 0；待做 45 项为用户暂缓 2 项（`QA-010` 远程 Live、`UX-029` 移动端）与企业级暂缓 43 项。另有 4 项 `OPTIONAL` 候选保持不排期，详见 [非企业级 TODO 执行计划](docs/todos/execution-plan.md)。

模块化计划单独维护：`MOD-001` 至 `MOD-019`、`MOD-024` 及 `MOD-030` 已交付；030 的双平台迁移与阶段验收范围及既有失败见 [报告](docs/reports/mod-030e-acceptance.md)，full 门未通过。`MOD-020` 至 `MOD-023` 的 Checkpoint/只读恢复、`MOD-025` 至 `MOD-028` 的 Adapter/演示/内网集成仍待完成；`MOD-029` 暂缓待标准与 Validator 职责结论后重审。新增 `MOD-031` [确定版方案](docs/validator-responsibility-plan.md)，未实施；台账未完成 10 项，产品 228/183/45 不变。兼容 facade 与配置锚点由 `MOD-027` 承接，见 [追踪](docs/todos/modularization.md)。

## 标记规则

- `[x]`：已经实现，并有代码或测试可以验证。
- `[ ]`：尚未实现，或只有设计文档而没有可运行实现。
- `OPTIONAL`：可选候选/不一定需要；有稳定编号，但不使用 `[ ]` 或 `[x]`，不纳入总任务、已完成或待做统计，不进入当前串行队列，也不构成检查点依赖。只有用户明确激活后才转为普通 `[ ]` 并计数和排期。
- `OPTIONAL` 不同于“用户暂缓”（确定需要但由用户延后）和“企业级暂缓”（确定需要但因企业级前置条件暂缓）；后二者仍是 `[ ]` 任务并计入主统计。
- 部分完成的事项必须拆成多个独立任务，不能将一个任务同时标记为完成和待做。
- `[ ]` 只表示未完成；是否进入当前队列以执行计划为准。

## 当前执行快照

| 类型 | 任务 | 当前结论 |
|---|---|---|
| 产品当前队列 | 0 项 | `AGENT-040` 至 `AGENT-044` 已完成；不自动激活暂缓或 `OPTIONAL` 任务 |
| 模块化本轮完成 | `MOD-030` | Skill/Tool 标准与旧目录退出已交付；保留既有失败和 full 未通过，已同步两个分支 |
| 模块化下一项方案 | `MOD-031` | [验证职责与业务证据策略确定版](docs/validator-responsibility-plan.md) v1.0，未实施；获明确实施指令后按 a～e 执行 |
| 模块化暂缓项 | `MOD-029` | 待 MOD-030 标准与第 8 条 Validator 职责讨论后再修订旧草案 |
| 模块化待办（另计） | `MOD-020` 至 `MOD-023`、`MOD-025` 至 `MOD-029`、`MOD-031` | 共 10 项：恢复 4、后续交付/内网集成 4、大结果处理 1、验证职责 1；031 后再重审 029 |
| 用户暂缓 | `QA-010`、`UX-029` | 远程 Live 验收和移动端需求暂不进入当前队列 |
| 企业级暂缓 | 43 项 | 等待身份提供方、真实数据接口、部署环境和运维边界明确 |
| 可选候选 | `RAG-024`、`AGENT-039`、`REF-025`、`REF-026` `OPTIONAL` | 不计入主统计，只在用户明确激活后排期 |

已有完整离线门记录见 [MOD-009 验收报告](docs/reports/mod-009-tool-sources.md)：2026-11-06 记录退出码 0，Python 1226 项（含 2 个平台跳过）、覆盖率 88%、Node 61/61、浏览器 17/17。后续 [MOD-012](docs/reports/mod-012-model-gateway.md) 与 [MOD-015](docs/reports/mod-015-runtime-convergence.md) 按各自范围验证；MOD-015e 的 WSL 1301 项逐模块对照没有新增失败，但保留与基线一致的既有环境失败，未重跑浏览器、覆盖率或性能门。各轮历史基线保留，当前验证索引见 [测试策略](docs/testing-strategy.md)。

## 工作流清单

| 工作流 | 清单 | 当前结论 |
|---|---|---|
| Memory System | [Memory TODO](docs/todos/memory-system.md) | MEM-001 至 MEM-004 已通过完整离线验收；长期记忆 OPTIONAL |
| Agent 执行架构 | [Agent TODO](docs/todos/agent-architecture.md) | Tool Agent Loop、四态上下文安全降级、历史回忆、制造范围门禁、Router/Playbook/Planner、证据与综合、计划审计、ready 确定性执行及 `AGENT-040` 至 `AGENT-044` 答案展示、声明支持、多证据推断、措辞和局部协议修复均已完成；Trace 语义由 `OBS-017` 收口 |
| 身份与权限 | [身份安全 TODO](docs/todos/identity-security.md) | 本地隔离和管理令牌已完成；企业 SSO/RBAC 属于企业级暂缓 |
| 模型治理 | [模型治理 TODO](docs/todos/model-governance.md) | 统一 Provider 连接、能力目录、用户选择与 Thinking 服务端门禁已完成；企业凭据与审批属于企业级暂缓 |
| RAG 与知识库 | [知识库 TODO](docs/todos/rag-knowledge.md) | L0 本地 RAG、中文双语制程召回治理、自动 Tag 人工保护和离线 OCR 已完成；分布式 RAG 属于企业级暂缓 |
| 企业数据 | [企业数据 TODO](docs/todos/enterprise-data.md) | SQLite 开发替身与大规模模拟契约已完成；既有 Oracle 生产接口适配 `DATA-017`、生产规模多消费者语义层 `DATA-018` 与多数据库存储/知识检索后端适配 `DATA-019` 均属企业级暂缓 |
| 日志与运行监控 | [可观测性 TODO](docs/todos/observability.md) | 单实例监控、端到端流式聚合诊断、上下文降级可观测性、消息持久化关联、完整日志到期治理、Trace 语义治理与 `QA-004` 脱敏回放均已完成 |
| 用户体验与会话 | [前端会话 TODO](docs/todos/frontend-sessions.md) | 桌面端关键工作流、无障碍治理和视觉回归已完成；移动端 `UX-029` 由用户暂缓 |
| 部署与服务拆分 | [部署架构 TODO](docs/todos/deployment-architecture.md) | Worktree、数据分库、跨 Windows/WSL 链接、运行快照治理、受保护的远程 CI 质量门和跨平台本地模型启动器（`DEPLOY-019`）已完成；其余项均为企业级暂缓 |
| 测试质量 | [测试质量 TODO](docs/todos/testing-quality.md) | QA-001 至 QA-009 已完成；QA-010 本地完整 Live 通过、远程验收暂缓 |
| 代码可维护性 | [代码可维护性 TODO](docs/todos/code-maintainability.md) | REF-001 至 REF-024、REF-027 至 REF-034 已完成；REF-035 已完成；`REF-025`、`REF-026` 仍为 `OPTIONAL` |
| 模块化与内网迁移（另计） | [模块化追踪](docs/todos/modularization.md) | MOD-001～019、MOD-024 及 MOD-030 已交付；030 保留基线失败/full 未过；020～023、025～028 计划中，031 方案确定未实施，029 暂缓；共 10 项未完成，不计入产品 228 项 |

## 更新要求

1. 新需求先加入对应工作流并分配稳定任务编号。
2. 完成任务时同时记录实现文件、迁移和测试。
3. 不以页面存在或文档完成作为后端能力完成的依据。
4. 跨工作流任务分别记录依赖，避免复制同一个完成状态。
