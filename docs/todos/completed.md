# 已完成任务索引

核对日期：2026-11-12。产品已完成 183 项，归档保留原任务编号、定义和验收记录；核心 TODO 只列未完成事项。历史描述不代表当前实现，当前源码与最新报告优先。

| 分类 | 已完成 | 定义与验收归档 | 当前待办 |
| --- | ---: | --- | --- |
| Agent 执行架构 | 43 | [归档](archive/agent-architecture.md) | [清单](agent-architecture.md)（0 项） |
| 代码可维护性 | 33 | [归档](archive/code-maintainability.md) | [清单](code-maintainability.md)（0 项） |
| 部署与服务拆分 | 11 | [归档](archive/deployment-architecture.md) | [清单](deployment-architecture.md)（8 项） |
| 企业数据 | 8 | [归档](archive/enterprise-data.md) | [清单](enterprise-data.md)（11 项） |
| 用户体验与会话 | 28 | [归档](archive/frontend-sessions.md) | [清单](frontend-sessions.md)（1 项） |
| 身份与权限 | 6 | [归档](archive/identity-security.md) | [清单](identity-security.md)（7 项） |
| Memory System 抽离任务 | 4 | [归档](archive/memory-system.md) | [清单](memory-system.md)（0 项） |
| 模型治理 | 14 | [归档](archive/model-governance.md) | [清单](model-governance.md)（4 项） |
| 日志与运行监控 | 11 | [归档](archive/observability.md) | [清单](observability.md)（6 项） |
| RAG 与知识库 | 16 | [归档](archive/rag-knowledge.md) | [清单](rag-knowledge.md)（7 项） |
| 测试质量 | 9 | [归档](archive/testing-quality.md) | [清单](testing-quality.md)（1 项） |

产品总量 228 = 本页各归档的 183 个已完成任务 + 当前分类清单的 45 个未完成任务；4 个 OPTIONAL 候选不计入主统计。统计只读取本页列出的分类文件及对应归档，不扫描执行历史或重复汇总表。

模块化另计：已完成 MOD-001～019、MOD-024、MOD-030、MOD-031 共 22 项，见[定义及验收归档](archive/modularization.md)；其余 9 项见[当前追踪](modularization.md)。保留 full 未通过、既有失败及未验证范围，不因移入归档宣称全绿。

历史施工顺序和检查点见[执行历史](execution-history.md)，当前验证记录见[测试策略](../testing-strategy.md)。

## TODO 文档治理

2026-11-12，关联 GitHub [Issue #2 第 1 项](https://github.com/MrJoker06/FAB-Copilot/issues/2)。文档整理完成；提交与推送状态以 Git 记录为准，不新增产品或 MOD 编号。

核心 TODO、分类清单、执行计划和模块化追踪只保留待办及索引；完成定义、专属验收和旧设计移至本页链接的归档，执行检查点迁至执行历史。历史证据的消费者链接同步调整，迁移前的未提交 MOD-029 重审方案保留。

按迁移前工作树逐项对照：183 项完成定义移入归档，45 项未完成定义及顺序不变，4 项 OPTIONAL 定义及状态不变；模块化 22 项完成记录和 9 项未完成状态保留。验证只覆盖文档结构、统计、链接与编码，不代表重新验证历史业务能力。

WSL 的 `python scripts/check_repository.py` 通过，模块化边界为 `files=309 errors=0`；逐项迁移对照及 UTF-8/LF、相对链接与章节锚点检查通过。纯文档任务未运行应用回归、浏览器、性能门或 Live，不改变既有 full 未通过的结论。

## 维护方式

1. 未完成任务的完整定义只放在对应分类清单；执行计划维护排期，不复制任务正文。
2. 完成且有验收证据后，将任务定义、专属说明与结果移入对应归档，保留稳定编号，并更新本索引和总统计；不删除历史失败或把历史测试当成当前测试。
3. 归档 Markdown 的相对链接按新目录修正；引用已移走章节的消费者须同步改向归档。
4. 新需求若仍由 GitHub Issue 维护，链接原 Issue 即可；正式纳入分类台账时再分配编号，避免重复计数。
