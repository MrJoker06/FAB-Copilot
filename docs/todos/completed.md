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

模块化另计：已完成 MOD-001～019、MOD-024～025、MOD-029～031 共 24 项，见[定义及验收归档](archive/modularization.md)；其余 7 项见[当前追踪](modularization.md)。保留 full 未通过、既有失败及未验证范围，不因移入归档宣称全绿。

历史施工顺序和检查点见[执行历史](execution-history.md)，当前验证记录见[测试策略](../testing-strategy.md)。

## PE / EE 值班工作区

2026-11-18 补充：GitHub #1 剩余错误码统一和场景处理已实现，完成门及既有失败见[报告](../reports/issue-1-error-standardization.md)；产品重心持续为值班助手。此项不新增产品/MOD 编号，#3 Guardrail 保持未完成。

2026-11-17，按用户确认的页面方向优先完成导航调整、折叠旧功能、基础报表和 SOP&历史case 页面，以及根目录 `display_mock_data/` 合成展示资料。新工作分支从 experiment 分出，未修改旧 main。实现、跨平台验证和既有完整门失败见[报告](../reports/pe-ee-duty-workspace.md)。此项不重复分配产品或 MOD 编号，不改变 228/183/45 统计，不代表公司系统接入。

## 值班聊天的 Skill 选择与执行

光刻 Cpk Skill 的手动指定、按意图选择、缺参澄清、部门授权和会话回读已完成本地验收。关联 GitHub #2 第 3 项。见[开发清单](../duty-chat-skill-execution-plan.md)及[验收报告](../reports/duty-chat-skill-execution.md)。

## TODO 文档治理

2026-11-12，关联 GitHub [Issue #2 第 1 项](https://github.com/MrJoker06/FAB-Copilot/issues/2)。文档整理完成；提交与推送状态以 Git 记录为准，不新增产品或 MOD 编号。

核心 TODO、分类清单、执行计划和模块化追踪只保留待办及索引；完成定义、专属验收和旧设计移至本页链接的归档，执行检查点迁至执行历史。历史证据的消费者链接同步调整，迁移前的未提交 MOD-029 重审方案保留。

按迁移前工作树逐项对照：183 项完成定义移入归档，45 项未完成定义及顺序不变，4 项 OPTIONAL 定义及状态不变；模块化 22 项完成记录和 9 项未完成状态保留。验证只覆盖文档结构、统计、链接与编码，不代表重新验证历史业务能力。

WSL 的 `python scripts/check_repository.py` 通过，模块化边界为 `files=309 errors=0`；逐项迁移对照及 UTF-8/LF、相对链接与章节锚点检查通过。纯文档任务未运行应用回归、浏览器、性能门或 Live，不改变既有 full 未通过的结论。

## persistence 功能拆分与模拟数据分离

2026-11-12，关联 GitHub [Issue #2 第 2 项](https://github.com/MrJoker06/FAB-Copilot/issues/2)。应用状态与演示 Schema/初始化分离，新增仓库外 `application_storage` Profile；定义、接口迁移和实际验证及既有失败见[报告](../reports/persistence-demo-separation.md)。此项不新增产品或 MOD 编号，后续运行 DB 物理分离与 LDAP 仍未实施，提交与远程状态以 Git 记录为准。

## MOD-029：结果卸载与 Session 级回读

2026-11-16 完成，源码基线 `0cae608`；独立结果库、默认开启及后台开关、共享预算回读、旧结果复核及可靠 Session 删除已接入。两端仓库外交付、进程重启和浏览器验收见[报告](../reports/mod-029-tool-result-access.md)；保留 Windows/WSL 完整门既有失败，不自动开始下一项或关闭 Issue。

## 维护方式

1. 未完成任务的完整定义只放在对应分类清单；执行计划维护排期，不复制任务正文。
2. 完成且有验收证据后，将任务定义、专属说明与结果移入对应归档，保留稳定编号，并更新本索引和总统计；不删除历史失败或把历史测试当成当前测试。
3. 归档 Markdown 的相对链接按新目录修正；引用已移走章节的消费者须同步改向归档。
4. 新需求若仍由 GitHub Issue 维护，链接原 Issue 即可；正式纳入分类台账时再分配编号，避免重复计数。

## GitHub #2 运行存储治理

第 4 项按用户确认的完整范围实现：运行状态与个人上传状态/索引默认进入运行目录，历史 SOP/case 独立；显式停服迁移保留模型配置、会话及结果引用。验收、既有失败与实际部署迁移范围见[报告](../reports/issue-2-runtime-storage-separation.md)。仅为单项交付记录，不增加产品主清单或 MOD 的完成计数，不关闭 #2 的其他条目。

## GitHub #2 请求类型与业务主题

第 5 项实现请求类型/业务主题分离、上下文仲裁及实际 Tool 限制；固定预期样例、真实 HTTP/会话与交付验证见[报告](../reports/issue-2-intent-routing.md)。本条不增加产品/MOD 完成计数；Issue #2 第 6 项及其他未实施需求保持待办。
