# Fab Insight Agent TODO

状态基线：`experiment/parallel-platform`，2026-07-18。

当前统计：共 135 个独立任务，已完成 77 个，待做 58 个。

本文件是项目任务状态的总入口。详细设计继续保留在 `docs/` 的架构文档中，任务是否完成以代码、迁移和测试是否落地为准。

当前执行顺序见 [非企业级 TODO 执行计划](docs/todos/execution-plan.md)：29 项进入串行队列，39 项企业级任务暂缓。

## 标记规则

- `[x]`：已经实现，并有代码或测试可以验证。
- `[ ]`：尚未实现，或只有设计文档而没有可运行实现。
- 部分完成的事项必须拆成多个独立任务，不能将一个任务同时标记为完成和待做。
- `[ ]` 只表示未完成；是否进入当前队列以执行计划为准。

## 工作流清单

| 工作流 | 清单 | 当前结论 |
|---|---|---|
| Agent 执行架构 | [Agent TODO](docs/todos/agent-architecture.md) | Tool Agent Loop、语义上下文、来源偏好纠正、Router、六类 Playbook、Planner、运行时守卫、Validator、Synthesizer 与计划审计持久化已完成；黄金集待做 |
| 身份与权限 | [身份安全 TODO](docs/todos/identity-security.md) | 本地隔离和管理令牌已完成；企业 SSO/RBAC 待做 |
| 模型治理 | [模型治理 TODO](docs/todos/model-governance.md) | 模型目录和用户选择已完成；企业凭据与审批待做 |
| RAG 与知识库 | [知识库 TODO](docs/todos/rag-knowledge.md) | L0 本地 RAG 和中文双语制程召回治理已完成；自动 Tag、OCR 和分布式 RAG 待做 |
| 企业数据 | [企业数据 TODO](docs/todos/enterprise-data.md) | 大规模模拟契约已完成；真实制造系统适配待做 |
| 日志与运行监控 | [可观测性 TODO](docs/todos/observability.md) | 单实例监控已完成；集中式多实例监控待做 |
| 用户体验与会话 | [前端会话 TODO](docs/todos/frontend-sessions.md) | 会话管理、后台 Run 归属及来源折叠去重已完成；Tag 编辑、流式停滞修复和浏览器自动化回归待做 |
| 部署与服务拆分 | [部署架构 TODO](docs/todos/deployment-architecture.md) | Worktree 和数据分库已完成；独立服务部署待做 |

## 更新要求

1. 新需求先加入对应工作流并分配稳定任务编号。
2. 完成任务时同时记录实现文件、迁移和测试。
3. 不以页面存在或文档完成作为后端能力完成的依据。
4. 跨工作流任务分别记录依赖，避免复制同一个完成状态。
