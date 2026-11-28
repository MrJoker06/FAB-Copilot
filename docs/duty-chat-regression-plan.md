# PE / EE 值班聊天回归计划

2026-11-28 已完成本地验收。基线为 `feat/pe-ee-duty-workspace` 的 `156e3cf`。现有开班检查和 PostgreSQL 试点文档及其本地台账改动与本任务独立。

## 目标与范围

使用固定输入和合成数据运行实际聊天链路，核对意图、计划参数、Dispatcher 执行、返回值、来源与限制，以及会话回读。复用 [Issue #2 第 5 项意图路由](reports/issue-2-intent-routing.md)和[第 6 项回答依据](reports/issue-2-duty-answer-evidence.md)的现有契约。以最近的[测试策略](testing-strategy.md)和实际源码为实施依据。

本期从 HTTP 同步或 NDJSON 流式入口进入。报警优先使用隔离数据库中的自有合成记录。若需模拟来源异常，在具名查询的 Port 边界注入，保留真实 Router、Planner、Dispatcher 和综合逻辑。固定日期使用 ISO 格式。班次请求遵循当前只支持日期的来源契约，验证前置澄清和用户确认后查询。公司班次定义、MES、正式身份和量化模型分别留待现场验收。

## 场景与预期

| 编号 | 固定输入 | 必须观测的预期 |
| --- | --- | --- |
| DUTY-REG-01 | 查询 2026-08-07 CMP-02 报警次数 | 识别设备查数，只调设备事件时间线。夹具包含两条目标报警和不应纳入的非报警、其他机台及日期记录。答案为 2 条，披露设备、日期与来源。 |
| DUTY-REG-02 | 追踪批次 LOT-DUTY-001 | 匹配批次追踪，所有加工及异常证据限定同一 Lot。验证固定身份、加工顺序和设备，来源与全历史口径可追溯。 |
| DUTY-REG-03 | 交班时查询 2026-08-07 CMP-02 夜班报警次数，随后回复「改查 2026-08-07 全天」 | 首轮说明查询粒度并等待确认，业务调用为零。后续复用原任务的设备和指标，实际参数为确认日期整日，返回对应计数和来源。 |
| DUTY-REG-04 | 查询 2026-08-07 夜班到 2026-08-08 白班 CMP-02 报警次数 | 披露来源缺少班次口径并澄清。两个日期不能被自动提交为全天查询，业务调用为零，不输出报警数。 |
| DUTY-REG-05 | 查询 2026-08-09 CMP-02 报警次数 | 工具成功且有效范围内 0 条，保留查询范围与来源。 |
| DUTY-REG-06 | 同范围的 CMP-02 报警请求，分别模拟来源故障和当前身份被拒绝 | 故障有明确错误分类与无法核实的说明。拒绝有权限提示与代码，实际来源调用为零。两种情况均无“0 条”结论，无成功证据。 |

## 变更与证据登记

1. 在现有会话系统模块中追加固定用例，测试名保留场景编号。先跑基线模块并记录结果，再运行新用例。
2. 若现有实现与上表不一致，先记录触发输入、基线观察、消费者、预计修改符号与新增断言，再修改该逻辑。仅实现能由现有来源与业务契约证明的行为。
3. 执行定向系统测试、相关 Router / Planner / Evidence 测试和仓库检查。若实现触发完整门，按测试策略在 WSL 离线运行。完整门是否执行、平台、退出状态、跳过与既有失败均登记。
4. 将每个实际改动文件对应到场景或计划/索引维护责任。记录输入、结果字段、测试方法、基线与最终命令。开发文档完成后由 [TODO](../TODO.md) 的完成入口引用。原始命令输出存放在忽略路径 `runtime/quality/`。产品与模块化统计沿用既有台账。

## 基线与实施决策

- 原会话系统模块 18/18。基线 HTTP 探查中，报警正例与零条均有确定性答案；跨班次澄清无业务调用。来源异常得到 `DATA_SOURCE_FAILED` 和读取失败说明。
- DUTY-REG-03 在基线上可复现。第一轮为 `clarification_required`，`missing_inputs` 包含 `supported_time_range`。仅回复「改查 2026-08-07 全天」被识别成未知任务。修复由 `app/planning_runtime/named_playbooks.py` 解析紧邻的日期口径澄清，`app/api/services/chat.py` 在共用执行入口接入。只接受带有效 ISO 日期的全天确认，从已存的紧邻澄清继承一个机台和原 Cpk／报警指标，随后重新走权限、规划与查询。不推断班次时间，不从普通旧回复恢复请求。保留原用户消息，回读执行计划可核对最终范围。
- DUTY-REG-02 使用独立合成 Lot。当前历史黄金集中的示例编号在本地参考数据中为空，因此为系统场景明确写入两道工序和其他 Lot 的对照记录。断言进入综合阶段的实际行、顺序、来源引用和缺项，避免把模型夹具的文字当作工具证据。
- DUTY-REG-06 使用同租户分析员访问部门限定工具的真实拒绝。基线探查中，演示 viewer 在会话结果保护层就提前被拒绝，不能用来断言 Dispatcher 的能力拒绝。本场景检查 `TOOL_DENIED`、无来源调用及会话回读。
- 首轮新增定向测试在基线上的 3 个失败中，DUTY-REG-03 为实际断点。DUTY-REG-02 漏写公开检索参数 `source_types`，DUTY-REG-06 初稿误用内部拒绝码，公开 Ready Trace 为 `TOOL_DENIED`。后两项按既有契约校正测试，运行代码只修复 DUTY-REG-03。

## 改动追踪

| 改动位置 | 对应场景 | 实施与可核对证据 |
| --- | --- | --- |
| [具名 Playbook](../app/planning_runtime/named_playbooks.py) 的 `resolve_duty_date_reply` | DUTY-REG-03 | 从紧邻澄清恢复单机台及报警／Cpk 指标。有效的同日、过期上下文、无上下文和非法日期均由 `test_duty_reg_03_*` 验证。 |
| [聊天服务](../app/api/services/chat.py) 的 `run_chat_agent` | DUTY-REG-03、06 | 同步／流式共用入口在生成计划前解释全天确认，原用户消息继续持久化。部门策略变更后的续查由 `test_duty_reg_06_departments_enforce_tool_deny_before_source` 验证。 |
| [会话系统测试](../tests/system/test_sessions_streaming.py) 的 `DutyChatRegressionTests` | DUTY-REG-01～06 | 新增 9 个用例，隔离的合成表覆盖日期边界、其他机台、非报警事件和其他 Lot。核对实际计划、返回值、调用级来源、证据限制、流式事件及会话回读。 |
| 本文与[已完成索引](todos/completed.md) | DUTY-REG-01～06 | 本文保存基线、场景、执行命令、改动映射及验收边界。验收结果已登记至索引。 |

## 验收记录

- WSL Python 3.11.15，在共享工作树执行基线 `python -m unittest tests.system.test_sessions_streaming` 为 18/18。本次在 WSL 原生文件系统上的隔离副本执行同命令为 27/27，其中新增 9 项。
- WSL 定向单元测试 `python -m unittest tests.test_duty_answer_evidence tests.test_intent_requests tests.test_intent_router tests.test_named_planner tests.test_named_planner_evidence tests.test_context_resolver` 为 98/98。
- Windows 原生 `.venv-win` 的 Python 3.13.5 运行 `python -m unittest tests.system.test_sessions_streaming.DutyChatRegressionTests` 为 9/9。测试客户端依赖产生 Starlette 弃用告警。
- `python scripts/check_repository.py`、`python scripts/check_module_boundaries.py`、`python scripts/check_modularization_boundaries.py` 和 `git diff --check` 通过。MOD-003 扫描 341 个受管文件，零错误。
- 首轮 WSL 完整离线门的 Python、覆盖率、Node 与仓库检查通过。RAG 阶段报 `RUNTIME_STORAGE_MIGRATION_REQUIRED`，因为隔离副本缺少已分离的运行状态库。仅在隔离副本补齐库，再运行同一完整门。
- 完整离线门 `python scripts/run_quality_gate.py full` 复跑退出 0。发现 1638 个 Python 用例，非系统 1533 个（3 个按条件跳过），系统 105/105，系统阶段总计 50.7 秒且低于预算。覆盖率 89%，Node 85/85、Chromium 47/47，RAG、OCR、Playbook、Ready 与 Trace 均通过。
- 原始记录位于 `runtime/quality/`，对应 `duty-regression-baseline.log`、`duty-regression-probe.log`、`duty-regression-red.log`、`duty-regression-system.log`、`duty-regression-unit.log`、`duty-regression-windows.log`、`duty-regression-full.log` 与 `duty-regression-full-rerun.log`。
- 公司 MES、真实身份、生产班次时段、真实 Qwen 和 Live 验收均在本期范围外。Lot 场景核对进入综合的工具证据与失败安全输出，综合响应使用本地夹具。
