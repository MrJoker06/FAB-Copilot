# GitHub Issue #1 收尾：值班助手错误规范

日期：2026-11-18。实施分支 `feat/pe-ee-duty-workspace`，起点 `3415428`；提交、远程及 Issue 关闭状态以 Git/GitHub 实际记录为准。

## 范围与结果

用户确认 PE / EE 值班助手为后续持续最高优先级，已写入 AGENTS、项目索引、TODO、执行计划与架构方向。本轮完成 #1 第 7 项错误码对应、同类命名/描述及场景处理；第 2 项大结果卸载已由 MOD-029 完成，本轮只核对记录，不重复实现。#1 第 9 项 Guardrail 已转移至 #3，仍未实现；#2 的意图/证据方向、#3 LDAP 和其他暂缓任务不在本轮范围。

错误码与触发含义见[参考](../error-code-reference.md)。没有更改公司 Qwen 配置、默认工具名称/描述/输入 Schema 或 21 项业务工具集合。

## 设计与实际改动

1. 在现有 `app/agent_runtime/tools/contracts.py` 维护不可变的 Tool 错误描述源，集中错误类别、安全公开描述、中文提示和处置建议。复用 ToolError/ToolResult，无新增应用目录、通用异常框架或重试引擎；ToolResult 数据类字段不变，BLOCKED 允许 dependency 分类。
2. Dispatcher 不再把所有策略/预算拒绝压成一个泛化原因。已知且分类匹配的 ROLE_DENIED、SCOPE_DENIED、DUPLICATE_ARGUMENTS 等保留；未知策略码回退通用拒绝，并忽略任意外部拒绝文本。授权与预算仍在实际执行路径生效。
3. Ready、Loop、旧执行分支、检索预取和离线综合使用相同公开错误语义。前置失败使用 DEPENDENCY_FAILED 并跳过依赖处理器；来源失败仍是失败，不转为空数据或模拟来源成功。旧分支内部异常不直接写入模型反馈、证据错误或用户轨迹，原诊断日志仍由已有遥测脱敏策略管理。
4. 工具模型反馈、tool_finished 与最终 tool_trace 携带 error_code、error_kind、execution_state、retryable、recovery_action、user_message。unknown 强制先核实状态且不可直接重试。处理器已进入后抛出的参数/权限异常不会伪称未开始；解析阶段拒绝才记 not_started。
5. 前端实时与恢复轨迹统一显示安全中文说明和转义后的错误码；没有增加自动重试、越权回读或预算豁免。结果回读错误也使用同一来源，返回字节仍按真实内容计入预算。
6. 独立 Dispatcher CLI 因新增中文提示暴露出原生 Windows 子进程编码差异，输出采用 JSON ASCII 转义；解析后中文内容保持不变，不依赖控制台编码或修改用户环境。

命名采用现有项目的 UPPER_SNAKE_CASE。旧 Guard 小写原因可作为输入兼容别名，新增公开码统一大写；历史会话不重写。已有 HTTP/领域协议保留，参考文档分别列出其归属和处理方式，不宣称已改写全部 HTTP 错误或完成 Guardrail。

## 冻结预期审阅

`tests/fixtures/agent_loop_split_golden.json` 的六个场景更新是本轮有意改变错误协议的结果：tool_round_then_synthesis、tool_round_no_progress_then_empty_answer、iteration_limit、dispatched_round_then_text、dispatched_explicit_binding、cancelled_mid_stream_dispatched。

独立按已批准的码、固定公开文本及新增元数据修改旧预期，未调用被测错误工厂或场景生成器重录期望值。差异只涉及失败码/描述/建议及其在历史模型请求中的重复投影；成功结果、调用顺序、模型参数、预算与业务数据不变。原始场景比较与结构测试保持执行，不删除失败断言。默认装配的 viewer 断言由泛化 POLICY_DENIED 改为真实 ROLE_DENIED，拒绝时来源不可打开的检查保留。

## 验证

原始命令输出和隔离目录在忽略的 `runtime/quality/issue1-*`，不提交数据库、凭据或日志。

解释器：WSL `.venv-linux/bin/python`（3.11.15）；Windows `.venv-win/Scripts/python.exe -X utf8`（3.13.5）。浏览器由 WSL Node 22.22.2/Chromium 执行，临时端口 27941。实际命令均在仓库根目录执行，未调用真实模型/公司接口。

| 验证 | 命令与结果 |
| --- | --- |
| 两端核心与可移植切片 | `python -m unittest tests.test_tool_errors tests.test_tool_contracts tests.test_tool_dispatcher tests.test_tool_result_bridge tests.test_ready_dispatcher tests.test_loop_dispatcher tests.test_ready_plan_execution tests.test_loop_guard tests.test_result_read_tool tests.test_result_access_runtime tests.test_loop_dispatcher_portable tests.test_ready_dispatcher_portable tests.test_tool_sources_portable tests.system.test_sessions_streaming.SessionsStreamingSystemTests.test_tool_failure_code_survives_real_http_stream_and_session_reload`：两端各 121 项通过 |
| 最终错误/快照/默认装配/独立安装 | WSL `python -m unittest tests.test_tool_errors tests.test_agent_loop_split tests.test_default_tool_assembly tests.test_dispatcher_bundle_install`：41 项通过；Windows `python -m unittest tests.test_agent_loop_split tests.test_default_tool_assembly tests.test_dispatcher_bundle_install`：33 项通过；新增旧分支场景另由 WSL 8 项验证，完整 Windows 最终审计覆盖 |
| HTTP 真实链路 | 真实 TestClient、Dispatcher 角色拒绝、NDJSON、Session 保存与 GET 回读；外层模型离线替换，断言来源未调用、错误码/中文说明保存一致且未泄露测试异常文本 |
| Node | `node --test tests/*.test.js`：65/65，含恢复轨迹中文与错误码、HTML 转义 |
| 浏览器完整回归 | `PLAYWRIGHT_PORT=27941 npm run test:e2e`：27/27，通过真实隔离服务，未访问外部模型 |
| 仓库与边界 | `python scripts/check_repository.py`、`python scripts/check_module_boundaries.py`、`python scripts/check_modularization_boundaries.py`：通过，受管源码 324，errors=0；`git diff --check` 通过 |
| 静态检查 | `python -m ruff check --output-format json app tests` 与起点逐项比较；最终数量及差异见下方审计结论 |

### 首次失败与修正

最初定向测试出现依赖错误分类/大小写旧断言、验证 fixture 错误地使用 TypeError（实际被归为配置故障），已按真实协议修正。一次命令写错两个测试模块名导致 ImportError，改用实际模块名重跑。新增 HTTP 测试第一次把字符串当作认证 Principal，已修正 fixture，未修改真实身份流程。

首次 Windows 全量为 1539 项、19 失败/12 错误/3 跳过。新增差异包括六个旧快照、viewer 旧断言和两项独立 CLI 安装的编码错误。后两项在同解释器、同隔离审计器的 `3415428` 导出树均通过（基线 4/4，改前当前树 2 错误），据此修复当前 CLI；没有把它们归为既有失败。快照和 viewer 按上节逐项审阅后更新。

### 最终完整审计

命令：Windows `python -X utf8 runtime/quality/persistence_audit.py . runtime/quality/issue1-audit-windows-final`。该本地审计器使用独立子进程、SQLite backup、隔离数据/上传/报表目录并禁用真实模型凭据，内部运行完整 `unittest discover`；不能只看审计器退出码，以下结论来自测试摘要及日志。

最终 **1539 项，13 失败、10 错误、3 跳过**；测试运行 393.926 秒，含发现/装配的审计耗时 396.058 秒。相比起点留存的 `autosystem-audit-windows`（1530 项，13 失败、10 错误、3 跳过），新增 8 项 Tool 错误行为测试和 1 项真实 HTTP/会话测试；失败、错误、跳过的完整 ID 集合逐项完全一致，没有新增或消失项。旧失败包括：

- 13 项失败：data_reports 4、sessions_streaming 1、context_resolver 1、modularization_baseline 3、modularization_fixture_clock 1、refactor_contracts 2、version_contract 1。
- 10 项错误：sessions_streaming 6（含三条链路子场景）、agent_assembly 1、operational_reports_runtime 2、personal_job_sse 1。
- 3 项跳过：OCR 生成器、平台文件交换保护、Linux 非可执行模型文件。

本轮未重新对旧树运行完整套件，完整集合对照使用起点留存日志，基线来源见[前轮报告](pe-ee-duty-workspace.md)；只针对新出现的独立安装错误在 `3415428` 导出树重跑，以相同 venv 和隔离审计器证明旧树 4/4 通过，再修复当前树。首次与最终失败均保留记录，不用最终一次通过掩盖最初差异。

Ruff 全量从 506 条降至 430 条，以标准化文件路径、规则和描述作多重集比较，没有新增问题；仍有既有问题，未宣称全量 Ruff 通过。仓库规定的静态检查集及两个边界检查通过。所有本次改动文件 UTF-8、LF、单一末尾换行和相关文档本地链接检查通过。未重录 OpenAPI/DOM 等既有失败的冻结契约。

## 未验证与限制

未运行真实模型、公司接口、LDAP、Live、性能门或完整覆盖率。没有重启/更改用户正在使用的模型服务；本轮独立安装在两平台验证，不把 TestClient 通过称为重新验证所有启动包装器。远程 CI 未验证。既有完整门失败不因本任务完成而消失，不宣称 full 全绿。
