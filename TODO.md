# Fab Insight Agent TODO

状态基线：`experiment/parallel-platform`，2026-08-10。

当前统计：共 159 个独立任务，已完成 108 个，待做 51 个。

本文件是项目任务状态的总入口。详细设计继续保留在 `docs/` 的架构文档中，任务是否完成以代码、迁移和测试是否落地为准。

当前执行顺序见 [非企业级 TODO 执行计划](docs/todos/execution-plan.md)：43 项已进入或完成串行队列，39 项企业级任务暂缓。

## 标记规则

- `[x]`：已经实现，并有代码或测试可以验证。
- `[ ]`：尚未实现，或只有设计文档而没有可运行实现。
- 部分完成的事项必须拆成多个独立任务，不能将一个任务同时标记为完成和待做。
- `[ ]` 只表示未完成；是否进入当前队列以执行计划为准。

## 工作流清单

| 工作流 | 清单 | 当前结论 |
|---|---|---|
| Agent 执行架构 | [Agent TODO](docs/todos/agent-architecture.md) | Tool Agent Loop、基于真实消息 ID 的上下文回忆、制造范围门禁、通用制造运营概览、Router、六类 Playbook、Planner、运行时守卫、Validator、Synthesizer、计划审计持久化与 Playbook 黄金集已完成 |
| 身份与权限 | [身份安全 TODO](docs/todos/identity-security.md) | 本地隔离和管理令牌已完成；企业 SSO/RBAC 待做 |
| 模型治理 | [模型治理 TODO](docs/todos/model-governance.md) | 统一 Provider 连接、能力目录、用户选择与 Thinking 服务端门禁已完成；企业凭据与审批待做 |
| RAG 与知识库 | [知识库 TODO](docs/todos/rag-knowledge.md) | L0 本地 RAG、中文双语制程召回治理和自动 Tag 人工保护已完成；OCR 和分布式 RAG 待做 |
| 企业数据 | [企业数据 TODO](docs/todos/enterprise-data.md) | 大规模模拟契约已完成；真实制造系统适配待做 |
| 日志与运行监控 | [可观测性 TODO](docs/todos/observability.md) | 单实例监控与端到端流式聚合诊断已完成；集中式多实例监控待做 |
| 用户体验与会话 | [前端会话 TODO](docs/todos/frontend-sessions.md) | 会话管理、后台 Run 归属、来源折叠去重、流式停滞、版本提示修复、个人知识唯一上传入口及 Tag/元数据编辑已完成；浏览器自动化回归待做 |
| 部署与服务拆分 | [部署架构 TODO](docs/todos/deployment-architecture.md) | Worktree、数据分库、跨 Windows/WSL 链接及运行快照治理已完成；独立服务部署待做 |
| 测试质量 | [测试质量 TODO](docs/todos/testing-quality.md) | QA-001 本地分层质量门、全量审计策略、QA-002 系统测试隔离与 QA-003 启动/迁移/运维脚本风险路径已完成 |

## 更新要求

1. 新需求先加入对应工作流并分配稳定任务编号。
2. 完成任务时同时记录实现文件、迁移和测试。
3. 不以页面存在或文档完成作为后端能力完成的依据。
4. 跨工作流任务分别记录依赖，避免复制同一个完成状态。
