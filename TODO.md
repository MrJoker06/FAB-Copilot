# Fab Insight Agent TODO

状态基线：`experiment/parallel-platform`，2026-08-20。

当前统计：共 167 个独立任务，已完成 125 个，待做 42 个。

另有 1 项 `OPTIONAL` 可选候选，不计入上述主统计。

本文件是项目任务状态的总入口。详细设计继续保留在 `docs/` 的架构文档中，任务是否完成以代码、迁移和测试是否落地为准。

当前结论：`OBS-014` 已完成，下一项为 CI 质量门 `DEPLOY-012`。当前队列共 1 项，另有用户暂缓 1 项、企业级暂缓 40 项；详见 [非企业级 TODO 执行计划](docs/todos/execution-plan.md)。

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
| 当前队列 | `DEPLOY-012` | 严格串行，下一项为 `DEPLOY-012` |
| 用户暂缓 | `UX-029` | 移动端需求暂不进入当前队列 |
| 企业级暂缓 | 40 项 | 等待身份提供方、真实数据接口、部署环境和运维边界明确 |
| 可选候选 | `RAG-024` `OPTIONAL` | 不计入主统计，只在用户明确激活后排期 |

最近一次完整质量门为 2026-08-20 `OBS-014` 宿主 full：333 个 Python 发现项、267 个非系统测试，分支覆盖率 87%、Playwright 10/10；五个系统模块及 82.4 秒总耗时均低于预算。完整基线见 [测试策略](docs/testing-strategy.md)。

## 工作流清单

| 工作流 | 清单 | 当前结论 |
|---|---|---|
| Agent 执行架构 | [Agent TODO](docs/todos/agent-architecture.md) | Tool Agent Loop、基于真实消息 ID 的上下文回忆、制造范围门禁、通用制造运营概览、Router、六类 Playbook、Planner、运行时守卫、Validator、Synthesizer、计划审计持久化与 Playbook 黄金集已完成 |
| 身份与权限 | [身份安全 TODO](docs/todos/identity-security.md) | 本地隔离和管理令牌已完成；企业 SSO/RBAC 属于企业级暂缓 |
| 模型治理 | [模型治理 TODO](docs/todos/model-governance.md) | 统一 Provider 连接、能力目录、用户选择与 Thinking 服务端门禁已完成；企业凭据与审批属于企业级暂缓 |
| RAG 与知识库 | [知识库 TODO](docs/todos/rag-knowledge.md) | L0 本地 RAG、中文双语制程召回治理、自动 Tag 人工保护和离线 OCR 已完成；分布式 RAG 属于企业级暂缓 |
| 企业数据 | [企业数据 TODO](docs/todos/enterprise-data.md) | SQLite 开发替身与大规模模拟契约已完成；通过既有 Oracle 生产接口的适配 `DATA-017` 属于企业级暂缓 |
| 日志与运行监控 | [可观测性 TODO](docs/todos/observability.md) | 单实例监控、端到端流式聚合诊断和完整日志到期治理已完成 |
| 用户体验与会话 | [前端会话 TODO](docs/todos/frontend-sessions.md) | 桌面端关键工作流、无障碍治理和视觉回归已完成；移动端 `UX-029` 由用户暂缓 |
| 部署与服务拆分 | [部署架构 TODO](docs/todos/deployment-architecture.md) | Worktree、数据分库、跨 Windows/WSL 链接及运行快照治理已完成；当前队列以 `DEPLOY-012` CI 质量门收口 |
| 测试质量 | [测试质量 TODO](docs/todos/testing-quality.md) | QA-001 本地分层质量门、全量审计策略、QA-002 系统测试隔离与 QA-003 启动/迁移/运维脚本风险路径已完成 |

## 更新要求

1. 新需求先加入对应工作流并分配稳定任务编号。
2. 完成任务时同时记录实现文件、迁移和测试。
3. 不以页面存在或文档完成作为后端能力完成的依据。
4. 跨工作流任务分别记录依赖，避免复制同一个完成状态。
