# Fab Insight Agent TODO

状态核对：2026-11-17，`feat/pe-ee-duty-workspace`，起点为 `experiment/parallel-platform` 的 `dcca19f`。本入口只列未完成任务、可选候选与索引；已完成任务及验收见[完成索引](docs/todos/completed.md)，历史施工顺序见[执行历史](docs/todos/execution-history.md)。

产品任务共 228 项：已完成 183、未完成 45（用户暂缓 2、企业级暂缓 43）；另有 4 项 OPTIONAL，不计入主统计。未完成定义在分类清单，已完成定义在对应归档，统计口径见[完成索引](docs/todos/completed.md)。模块化另计，未完成 8 项。

## 当前安排

2026-11-18 单项更新：GitHub #2 第 4 项按“完整分离”实现，运行状态默认进入 `runtime`，个人上传状态/索引与历史 SOP/case 分库；旧数据使用带备份的显式维护入口，见[报告](docs/reports/issue-2-runtime-storage-separation.md)。不因此完成 MOD-025 或关闭整个 #2，既有产品统计不变。

2026-11-18 用户确认：值班助手是后续持续优化的最高优先级，不仅是页面调整。本轮完成 GitHub #1 剩余的错误码对应、分类处理和 Tool 失败展示，见[错误码参考](docs/error-code-reference.md)及[验收报告](docs/reports/issue-1-error-standardization.md)。#1 的 Guardrail 已转移至 #3，仍未实现；#2、#3 与其他暂缓项不随本轮完成。

2026-11-17 用户最高优先级：PE / EE 值班工作区与根目录 `display_mock_data/` 展示资料已在 `feat/pe-ee-duty-workspace`（起点 `dcca19f`）完成，并追加报表目录管理、共享上传与原案例入口合并；验收与限制见[报告](docs/reports/pe-ee-duty-workspace.md)。不自动启动其他 MOD 或企业级任务，产品任务统计口径不变。

- 模块化后续为 MOD-025 → MOD-026 → MOD-027 → MOD-028，恢复链 MOD-020 → MOD-021 → MOD-022 → MOD-023 按需求启用；MOD-029 已完成，验收与既有失败见[报告](docs/reports/mod-029-tool-result-access.md)。见[执行计划](docs/todos/execution-plan.md)和[模块化追踪](docs/todos/modularization.md)。
- GitHub [#1](https://github.com/MrJoker06/FAB-Copilot/issues/1)、[#2](https://github.com/MrJoker06/FAB-Copilot/issues/2)、[#3](https://github.com/MrJoker06/FAB-Copilot/issues/3)维护其余改造方向；未实施项不因方向确认或本次归档而完成，不自动启动 LDAP、公司接入或 Live。

## 未完成任务入口

| 工作流 | 清单 | 未完成 | 当前安排 |
| --- | --- | ---: | --- |
| 身份与权限 | [清单](docs/todos/identity-security.md) | 7 | 企业级暂缓；后续身份权限需求另见 GitHub #3 |
| 模型治理 | [清单](docs/todos/model-governance.md) | 4 | 企业级暂缓 |
| RAG 与知识库 | [清单](docs/todos/rag-knowledge.md) | 7 | 企业级暂缓；RAG-024 为 OPTIONAL |
| 企业数据 | [清单](docs/todos/enterprise-data.md) | 11 | 企业级暂缓 |
| 可观测性 | [清单](docs/todos/observability.md) | 6 | 企业级暂缓 |
| 前端与会话 | [清单](docs/todos/frontend-sessions.md) | 1 | UX-029 用户暂缓 |
| 部署架构 | [清单](docs/todos/deployment-architecture.md) | 8 | 企业级暂缓 |
| 测试质量 | [清单](docs/todos/testing-quality.md) | 1 | QA-010 远程 Live 用户暂缓 |
| Agent 架构 | [清单](docs/todos/agent-architecture.md) | 0 | AGENT-039 为 OPTIONAL |
| 代码可维护性 | [清单](docs/todos/code-maintainability.md) | 0 | REF-025、REF-026 为 OPTIONAL |
| Memory System | [清单](docs/todos/memory-system.md) | 0 | 无已排期任务 |
| 模块化（另计） | [追踪](docs/todos/modularization.md) | 8 | 保持原依赖及审核安排 |

## 维护规则

1. 分类清单只保留未完成任务的 `[ ]` 和未激活 OPTIONAL 的完整定义；完成后把 `[x]` 定义、历史方案和验收说明移入对应归档，核心清单只保留完成索引。
2. 只有任务本身实现并有验收证据才能完成；方案形成不代表运行能力完成。保留用户暂缓、企业级暂缓和 OPTIONAL 的区别，不自动激活。
3. 统计按当前分类清单与完成索引列出的归档分别计算；编号稳定，不把汇总表、执行历史或 GitHub 记录重复计数。
4. 执行顺序见[执行计划](docs/todos/execution-plan.md)；验证依据[测试策略](docs/testing-strategy.md)，历史报告不替代当前验收。文本保持 UTF-8/LF。
