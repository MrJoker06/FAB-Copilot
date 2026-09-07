# 测试策略与质量门

## QA-001 审计基线（2026-08-01）

审计前有 166 个 Python 测试、19 个 JavaScript 断言和 15 条 RAG 黄金集。完整宿主 Python 回归当时有 2 个失败；`app` 分支覆盖率为 81%。低覆盖重点为 `seed.py`（25%）、`database.py`（76%）、`agent.py`（77%）、`context_resolver.py`（78%）和 `personal_knowledge.py`（80%）。在 coverage run 中，`scripts/evaluate_rag.py`、`scripts/manage_databases.py` 和 `scripts/smoke_stream.py` 均为 0%；其中 RAG 评估另以独立命令实际通过 15/15。

系统测试现有 54 项，按数据报表、知识与个人上传、HTTP/企业契约、模型治理、会话与流式拆分至 `tests/system/`。完整门为每个模块启动独立进程：fixture 在导入 app 前以 SQLite backup 创建参考部门数据库的一致临时快照，并使用独立个人知识目录、日志目录，进程退出时清理。Playwright 覆盖 1440x900 Chromium 的用户总览、管理端锁定/已认证工作区，以及真实隔离 FastAPI 上的模型 Thinking 能力切换、个人知识上传就绪、Thinking 流式回答与会话归档；Axe WCAG 2.0/2.1/2.2 A/AA（含颜色对比度）扫描用户关键视图/模型对话框和管理端认证、运行、模型目录与发布对话框，并验证键盘导航、Dialog 焦点和认证弹窗 Escape 策略。视觉回归使用固定 `zh-CN`、`Asia/Hong_Kong`、浅色主题、CSS 像素缩放和 reduced motion，覆盖长 Markdown 回答及超长多语言个人知识文件名，并同时断言页面与目标区域没有横向溢出。它使用 8899 临时服务、隔离快照和固定测试令牌，不调用真实模型；临时 AI 运营库固定提供一个不支持和一个支持 Thinking 的已发布模型，视觉内容也只写入临时 AI 运营库和知识库快照。所有桌面用例通过自动 fixture 拦截未声明的页面异常、控制台错误、同源请求失败和 HTTP 5xx；例外必须在当前用例精确声明。`evaluations/e2e_critical_paths.json` 与 Node 契约精确比对 `test(...)` 声明中的 10 条稳定 ID，防止关键用例被删除、重复或只在注释中残留 ID。测试服务依次记录快照准备、端口启动和实际 loopback `/api/health` 成功；Playwright 管道会保留服务 stdout/stderr 以定位失败阶段。失败时保留 trace 与截图至被 Git 忽略的 `test-results/` 和 `playwright-report/`；移动端不在本项范围。

## 分层与原则

- 单元测试覆盖纯规则、解析、计划、RAG 决策和质量门命令构造。
- HTTP 契约测试覆盖公开 API 的成功、认证、脱敏和输入边界；系统测试覆盖跨库与后台任务工作流。
- RAG 黄金集独立评估召回、来源覆盖和禁止命中；Playbook 黄金集以固定日期驱动真实 Router、Playbook 选择和 Planner，并断言严格工具路径、必需证据覆盖与预算一致性；两者均不访问真实模型。
- ready 执行性能门以固定制程能力、Lot 追踪和整厂诊断问题重建旧模型选取依赖批次的路径，与服务端确定性执行后单次综合路径比较。Token 使用 UTF-8 字节/版本化比例估算，首答时延使用固定模型调用、Prompt 和工具成本；它只用于离线架构回归，不代表供应商计费、真实 Tokenizer 或网络 SLA。
- QA-004 Trace 回放矩阵使用 `synthetic_redacted` 固定数据，调用生产 Context Resolver、Decision Arbiter、Router、Playbook、Planner、Validator 与 Synthesizer 契约。7 个 case 跨层覆盖三条真实请求链路、三种 Router 失败扩写和显式 SOP 反例；HTTP 系统测试再验证相同三条链路的 NDJSON 增量与 Session 元数据持久化。回放器不调用真实模型或网络，并拒绝凭据和隐藏推理字段。
- 测试必须确定、隔离和可重复，负向路径与边界值和正常路径同等重要。测试日志可记录完整轨迹，但 API Key、Authorization、Password、Secret、Cookie 和 Token 始终脱敏。

在受限沙箱中，FastAPI 的同步端点会由 `anyio.to_thread` 调度；测试应避免把该调度限制误判为 API 契约失败，并不得以真实模型或浏览器依赖绕过隔离。

## QA-003 脚本契约

`tests/test_startup_script.py` 在临时 Git 仓库中复制 `run.sh`，用假 Conda 记录 seed 和 uvicorn 调用，因此不会启动真实服务或网络；同时验证默认 8888 端口、运行实例隔离、快照标记和锁失败。`tests/test_database_manager.py` 只使用临时 SQLite 库，覆盖只读检查、在线备份的 staging 原子发布、失败清理、迁移和 checkpoint。`tests/test_runtime_manager.py` 覆盖无效 manifest、锁、保留边界、路径和符号链接拒绝。`tests/test_smoke_stream.py` 通过 fake transport 覆盖 NDJSON 成功和协议/HTTP 失败，无真实模型调用。

可单独运行这些离线脚本契约：

```bash
python -m unittest tests.test_startup_script tests.test_database_manager tests.test_runtime_manager tests.test_smoke_stream
```

## 本地质量门

先安装测试依赖：

```bash
python -m pip install -r requirements-test.txt
```

快速门运行非 `tests.system.*` Python、全部 Node 测试、全部静态 JS 语法检查、RAG/OCR/Playbook 黄金集、ready 执行性能门和 QA-004 Trace 回放矩阵：

```bash
python scripts/run_quality_gate.py quick
```

完整门先运行非系统 Python 的 `coverage --branch --source=app`，再逐个运行系统模块的 `coverage --append`，要求合并后的 `app/*` 至少 80%，然后执行同一组 Node、语法、RAG、Playbook 和 Playwright 桌面检查。每个系统模块及总耗时均按版本化预算检查：达到告警阈值会输出警告，超过失败阈值则失败；结构化报告写入 `runtime/quality/system_test_timings.json`。2026-08-02 首次宿主完整门实测：数据报表 16.5 秒、HTTP/企业契约 23.0 秒、知识上传 15.5 秒、模型治理 16.7 秒、会话流式 19.1 秒，总计 90.7 秒；据此校准模块告警/失败预算为 45/75、60/90、45/75、45/75、50/80 秒，总计 180/300 秒。

2026-08-12 `UX-012` 宿主 full 实测全通过：发现 267 个 Python 测试，其中 202 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 12、模型治理 17、会话与流式 9；`app` 分支覆盖率 86%，Node 33 项、RAG 15/15、Playbook 12/12，Playwright 桌面 2/2。

2026-08-12 `RAG-011` 宿主 full 实测全通过：发现 276 个 Python 测试，其中 211 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 12、模型治理 17、会话与流式 9；`app` 分支覆盖率 86%，Node 33 项、RAG 15/15、Playbook 12/12，Playwright 桌面 2/2。结构化系统耗时报告总计约 149.0 秒，所有模块及总计均低于预算。

`RAG-012` 增加固定离线 OCR 黄金集及 `evaluate_ocr.py`：报告 CER、英文 WER、关键字段/表格单元格/公式 token 召回和页码保留率，并按版本化阈值失败退出；样本与人工标准答案固定在仓库，评估不联网、不生成资产。该集是最小人工回归集，不构成生产 OCR 准确率证明。

2026-08-13 宿主 full 实测全通过：发现 317 个 Python 测试，其中 251 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 33 项、RAG 15/15、OCR 黄金集 8/8 类别通过、Playbook 12/12，Playwright 桌面 2/2。系统耗时总计 72.4 秒，五个模块及总计均低于版本化预算。

2026-08-13 `RAG-016` 宿主 full 实测全通过：发现 324 个 Python 测试，其中 258 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 34 项、RAG 15/15、OCR 黄金集 8/8 类别通过、Playbook 12/12，Playwright 桌面 2/2。结构化运行时报告总计 82.9 秒，五个模块及总计均低于版本化预算。

2026-08-13 `UX-013` 宿主 full 实测全通过：发现 326 个 Python 测试，其中 260 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 34 项、RAG 15/15、OCR 黄金集 8/8 类别通过、Playbook 12/12，Playwright 桌面 5/5。`runtime/quality/system_test_timings.json` 总计 74.7 秒，五个模块及总计均低于版本化预算。

2026-08-13 `UX-014` 宿主 full 实测全通过：发现 326 个 Python 测试，其中 260 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 35 项、RAG 15/15、OCR 黄金集 8/8 类别通过、Playbook 12/12，Playwright 桌面 8/8，Axe WCAG 2.0/2.1/2.2 A/AA 扫描零违规。`runtime/quality/system_test_timings.json` 总计 76.4 秒，五个模块及总计均低于版本化预算。

2026-08-19 `UX-015` 宿主 full 实测全通过：发现 327 个 Python 测试，其中 261 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 35 项、RAG 15/15、OCR 黄金集 8/8 类别通过、Playbook 12/12，Playwright 桌面 10/10。两张 Linux Chromium 基线覆盖长 Markdown 回答和超长多语言个人知识文件名，均经人工检查及非更新模式复验；`runtime/quality/system_test_timings.json` 总计 75.1 秒，五个模块及总计均低于版本化预算。

2026-08-20 `OBS-014` 宿主 full 实测全通过：发现 333 个 Python 测试，其中 267 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 契约文件 13/13、RAG 15/15、OCR 黄金集 8/8 类别通过、Playbook 12/12，Playwright 桌面 10/10。`runtime/quality/system_test_timings.json` 总计 82.4 秒，五个模块及总计均低于版本化预算。

2026-08-23 `AGENT-034`/`OBS-016` 宿主 full 实测全通过：发现 358 个 Python 测试，其中 292 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 87%，Node 36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Playwright 桌面 10/10。`runtime/quality/system_test_timings.json` 总计 90.3 秒，五个模块及总计均低于版本化预算。

2026-08-23 `AGENT-038` 宿主 full 实测全通过：发现 395 个 Python 测试，其中 328 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 86%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 确定性执行合成基准 3/3、Playwright 桌面 10/10。`runtime/quality/system_test_timings.json` 总计 76.0 秒，五个模块及总计均低于版本化预算。个人知识可访问性断言同步为验证唯一上传入口存在，不再错误要求位于长文档列表首屏。

2026-08-23 `OBS-017` 宿主 full 实测全通过：发现 401 个 Python 测试，其中 334 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；`app` 分支覆盖率 86%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Playwright 桌面 10/10。`runtime/quality/system_test_timings.json` 总计 80.5 秒，五个模块及总计均低于版本化预算；新增契约覆盖版本字段防覆盖、旧 Trace 读取、三类引用计数、安全仲裁候选和六阶段耗时聚合。

2026-08-24 `QA-004` 宿主 full 实测全通过：发现 408 个 Python 测试，其中 340 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 15.8、16.0、19.5、16.3、16.7 秒，总计 84.3 秒，全部低于版本化预算；回放与系统链路均未调用真实 LLM 或网络。

2026-08-25 `REF-001` 宿主 full 实测全通过：发现 411 个 Python 测试，其中 343 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 14.1、26.9、17.5、13.5、16.3 秒，总计 88.3 秒，全部低于版本化预算；新增边界契约固定工具目录旧导出、模型流包装器回调和隐藏推理审计行为。

2026-08-26 `REF-002` 宿主 full 实测全通过：发现 416 个 Python 测试，其中 348 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 14.8、14.1、16.6、16.9、17.6 秒，总计 80.0 秒，全部低于版本化预算；`refactor_contract_v1.json` 与只读检查器开始作为后续目录化重构的跨层等价门。

2026-08-26 `REF-003` 宿主 full 实测全通过：发现 424 个 Python 测试，其中 356 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 12.4、18.4、16.6、13.6、15.8 秒，总计 76.8 秒，全部低于版本化预算；新增 8 项 Agent Runtime 边界测试，`refactor_contract_v1.json` 冻结兼容契约通过。

2026-08-26 `REF-004` 宿主 full 实测全通过：发现 430 个 Python 测试，其中 362 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 12.2、14.1、16.1、12.7、14.8 秒，总计 69.8 秒，全部低于版本化预算；新增 6 项准备阶段边界测试、116 项定向回归及 `refactor_contract_v1.json` 冻结兼容契约通过。`app.agent` 已由 2860 行降至 2476 行（减少 384 行）。

2026-08-27 `REF-005` 宿主 full 实测全通过：发现 435 个 Python 测试，其中 367 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 14.6、13.5、15.8、12.7、15.9 秒，总计 72.5 秒，全部低于版本化预算；新增 5 项工具运行时边界测试、108 项定向回归及冻结 `refactor_contract_v1.json` 兼容契约通过。工具 catalog/registry 的对象身份与实时 patch registry 保持兼容。

2026-08-28 `REF-006` 宿主 full 实测全通过：发现 438 个 Python 测试，其中 370 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 12.3、15.3、17.6、13.2、14.9 秒，总计 73.2 秒，全部低于版本化预算；新增 3 项执行边界测试、105 项定向回归及冻结 `refactor_contract_v1.json` 兼容契约通过。`app.agent` 由 2478 行降至 1801 行（减少 677 行）；Ready 确定性服务端执行、模型业务工具选择数 0、兼容 patch 注入及重试/首个正文前降级语义保持不变。

2026-08-28 `REF-007` 宿主 full 实测全通过：发现 442 个 Python 测试，其中 374 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 13.7、15.5、17.3、13.9、15.7 秒，总计 76.1 秒，全部低于版本化预算；新增 4 项离线检索边界测试，`test_agent_retrieval_boundaries`、`test_knowledge_decision`、`test_context_resolver`、`test_intent_router`、`test_agent_module_boundaries`、`test_agent_execution_boundaries`、`test_refactor_contracts` 共 94 项通过，冻结 `refactor_contract_v1.json` 兼容契约通过。`app.agent` 由 1801 行降至 1613 行（减少 188 行）；覆盖实时 `TOOL_HANDLERS`/`emit`/`_notify` facade 注入、原始与改写查询的 scope 顺序、低置信度来源过滤、检索错误降级、答案 normalize、披露识别与旧 SOP fallback。

```bash
python scripts/run_quality_gate.py full
```

质量门在执行前以 AST 统计 unittest 风格测试方法，避免导入测试时污染环境；发现少于最近完整审计确认的 175 个测试即失败。只有完整审计确认的有意删测才能调整此基线；命令首次失败即非零退出。覆盖数据写入 `runtime/quality/`，Playbook 与 Trace 回放报告分别写入 `runtime/quality/playbook_gold_report.json` 和 `runtime/quality/trace_replay_report.json`。

2026-08-28 `REF-008` 宿主 full 实测全通过：发现 452 个 Python 测试，其中 384 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 88%，Node 36/36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统测试总耗时 73.5 秒，全部低于版本化预算；新增 10 项合成边界测试、141 项定向回归、冻结 `refactor_contract_v1.json` 兼容契约及仓库检查通过。`app.agent` 由 1613 行降至 1256 行（减少 357 行），Ready 仅暴露 `submit_analysis`、原始正文空白与实时 fallback facade patch 均保持兼容。

2026-08-29 `QA-005` 宿主 full 实测全通过：发现 455 个 Python 测试，其中 387 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10；`app` 分支覆盖率 88%，Node 契约文件 15/15、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 桌面 10/10。系统模块耗时依次为 16.9、14.8、16.3、13.9、16.2 秒，总计 78.2 秒，全部低于版本化预算；Playwright 通过管道输出快照准备、端口启动和真实 loopback 健康成功阶段，10 条稳定 ID 用例在 30.1 秒内通过且无未声明浏览器失败。

2026-08-29 `QA-006` 已完成双通道验证：宿主 full 发现 471 个 Python、403 个非系统测试；系统模块依次为 13、15、13、17、10，耗时依次为 12.5、13.4、15.8、13.6、15.9 秒，总计 71.2 秒且低于预算，`app` 覆盖率 88%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 10/10（28.9 秒）。Loopback 协议夹具覆盖 429、500、非法 JSON/SSE、首正文超时、截断 partial response 与 graceful 缺失 `[DONE]`。浏览器和模型治理测试均显式安排隔离模型目录基线，不依赖可变的 Admin 参考状态。`deepseekv4-pro` 真实兼容性于 2026-08-29T05:52:38.410+00:00 通过（12556.2ms；connectivity_streaming、tool_calls、context_load、structured_context、thinking_answer、thinking_tool_roundtrip、limits；context_chars=32768）。授权 Chromium `LIVE_PROVIDER` 五轮矩阵 5/5 通过：provider=deepseek、provider_model=deepseek-v4-pro、calls=9、input/output=66859/22083、313235.3ms、fallback/degraded=0，报告未保存正文、密钥或隐藏推理。

2026-08-30 `QA-007` 宿主 full 实测全通过：发现 471 个 Python 测试，其中 403 个非系统测试；系统模块分别为数据报表 13、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 10，耗时依次为 25.2、20.4、21.2、17.5、21.4 秒，总计 105.6 秒，全部低于预算。`app` 分支覆盖率 88%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 12/12（36.7 秒）。新增个人知识确定性 E2E 真实执行 FastAPI、后台 Job、抽取/分块、SQLite FTS 与临时存储，覆盖多选、跨选择去重/移除、共同 metadata/tags、逐项状态、部分失败和仅失败项重试、编辑/重命名、删除与失败处理重试；普通 full 继续零外网、零真实模型。最终管理员授权 Chromium Live 运行两个场景 2/2（个人知识场景 6.8 秒）：provider=deepseek、provider_model=deepseek-v4-pro、model_id=deepseekv4-pro、runs=6、real calls=11、input/output=69165/21325、354527.9ms、fallback/degraded=0；每个 run 均成功，报告仅保存 metadata，未含正文、请求体、密钥或隐藏推理。

## 托管 CI

`.github/workflows/quality.yml` 在 `experiment/parallel-platform` 的 push、PR 和手动触发时，在固定 Ubuntu 24.04 上使用 Python 3.11、Node 22 执行完整门。视觉回归显式安装 `fonts-noto-core` 和 `fonts-noto-cjk`，避免 Hosted Runner 镜像字体变化被误判为页面回归。CI 只允许在 `CI=true` 时运行 `scripts/prepare_ci_data.py`：它拒绝已存在的部门库，生成固定 730 天、截至 2026-12-25 的合成数据，补齐默认模型目录后再执行治理检查。因此不会读取本地开发数据，不会调用真实模型、Oracle 或生产端点。

失败且未被取消时，只允许通过 `actions/upload-artifact@v7` 上传 `playwright-report/`、`test-results/` 和 `runtime/quality/` 诊断；数据库、日志及完整内容均不在 artifact 范围。workflow 使用最小 `contents: read` 权限与同一分支并发取消。远程分支保护已要求与基线严格同步，并要求由 GitHub Actions App 产生的 `Full quality gate`；CI 失败会阻止受保护的合并。

`QA-010` 的本地工作流实现新增 `.github/workflows/live-quality.yml`，它只接受管理员 `workflow_dispatch`，并通过 `live-e2e` Environment Secret `FAB_MODEL_API_KEY` 和必填 `model_id` 执行完整七轮 Live 门。它不在 push 或 PR 触发，标准 `Full quality gate` 名称和离线路径也不变。`evaluations/live_e2e_budgets.json` 为 `full` 与仅诊断用途的 `provider-matrix` 分别版本化 runs、调用数、input/output/total token、启动、单测和总时长硬上限；环境变量只能收紧，不能放宽。Live artifact 始终仅为精确的 metadata-only `runtime/quality/live_e2e_report.json`，不上传 Playwright 报告、截图、数据库、日志、正文、请求体或密钥。2026-09-04 本地完整 7-run 已通过，但 2026-09-05 用户暂缓远程 Environment、Secret 和 full workflow 验收；私有仓库的 required reviewer API 返回 422，未将其替代为自审。发布或打标签前仍必须对目标 commit 手动运行远程完整 `full` Live 门，`provider-matrix` 不可替代它；本地故障协议夹具、标准确定性门和真实 Provider 门需分别统计。

2026-08-31 `REF-011` 宿主 full 离线验证通过：发现 493 个 Python 测试，其中 425 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 30.2/30.5/35.0/40.5/39.6 秒，总计 175.8 秒，全部低于失败预算（总计低于 180 秒 warning，但接近该阈值）。`app` 分支覆盖率 88%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17；真实模型和外网调用均为 0。主代理定向复验为 94/94（17.909 秒），冻结契约、仓库检查和 diff 检查均通过。`QA-010` 的完整 7-run Live 门未运行，仍由用户暂缓且未完成。

2026-09-01 `REF-012` 宿主 full 离线验证通过：发现 502 个 Python 测试，其中 434 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 13.8/15.8/17.8/15.1/16.1 秒，总计 78.6 秒，均低于预算。`app` 分支覆盖率 89%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（42.8 秒）；真实模型和外网调用均为 0。主代理定向复验 66/66（11.826 秒），冻结契约、仓库检查和 diff 检查均通过。`QA-010` 完整 7-run Live 门未运行，仍由用户暂缓且未完成。

2026-09-01 `REF-013` 宿主 full 离线验证通过：发现 504 个 Python 测试，其中 436 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 12.8/15.7/17.9/15.7/17.4 秒，总计 79.5 秒，均低于预算。`app` 分支覆盖率 89%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（43.9 秒）；真实模型和外网调用均为 0。主代理定向复验 75/75（11.958 秒），冻结契约、仓库检查和 diff 检查均通过。`QA-010` 完整 7-run Live 门未运行，仍由用户暂缓且未完成。

2026-09-01 `REF-014` 宿主 full 离线验证通过：发现 504 个 Python 测试，其中 436 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 17.5/19.2/22.4/15.9/18.9 秒，总计 94.0 秒，均低于预算。`app` 分支覆盖率 89%，Node 50/50、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（41.8 秒）；真实模型和外网调用均为 0。主代理定向复验 Node 50/50（1.120 秒）、44 项 Python（12.681 秒），递归 JS syntax、冻结契约、仓库检查和 diff 检查均通过。`QA-010` 完整 7-run Live 门未运行，仍由用户暂缓且未完成。

2026-09-02 `REF-015` 宿主 full 全通过：504 个 Python 发现项、436 个非系统测试；系统模块为数据 13、HTTP 15、知识 13、模型 17、会话 10，耗时 14.4536/20.5346/18.2821/16.2205/16.4219 秒、总计 85.9129 秒；分支覆盖率 89%，Node 56/56、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 17/17（42.2 秒）均通过。个人知识控制器另有 2/2 定向 Playwright 回归（57.2 秒，含服务准备，不计为完整门时间）；普通 full 的真实模型与外网调用均为 0，`QA-010` 完整 7-run Live 仍未运行且由用户暂缓。

2026-09-03 `REF-016` 必要回归通过：JS 语法与 diff 检查通过，Node 58/58、相关 Python 契约 24/24、五组系统测试 13/15/13/17/10、确定性 Playwright 17/17（2.0 分钟，含隔离快照和服务准备）均通过；普通测试的真实模型与外网调用为 0。一次宿主 full 尝试完成 436/436 非系统测试及前三组系统断言，但 WSL 进程退出墙钟分别为 67.2/87.6/91.6 秒，知识组超过 75 秒失败预算而提前停止；知识组测试体为 13/13、5.215 秒，后两组随后脱离 coverage 单独验证为 17/17 和 10/10。该记录只证明 REF-016 必要回归，不宣称本次 full 或 `QA-010` 完整 7-run Live 通过；最近一次完整 full 基线仍为 `REF-015`。

2026-09-05 `REF-017` 宿主 full 通过：发现 Python 505 个、非系统 437/437；系统数据、HTTP、知识、模型、会话为 13/15/13/17/10，宿主墙钟 18.8463/19.2610/23.5279/16.7825/19.7337 秒、总计 98.1517 秒，全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、最终 Playwright 17/17（46.3 秒）通过，普通门真实模型和外网调用均为 0。首次 Playwright 为 15/17：layout 在 sessions 前创建，捕获默认 no-op `loadSessionLibrary`，两个会话旅程进入 sessionsView 后列表停在“正在加载”；未放宽测试，改为先创建 sessions、再显式将其注入 layout，并新增 Node 创建顺序/注入回归。修复后 targeted Journey/Workflow 6/6（28.9 秒），最终 full Playwright 17/17。递归 JS syntax、冻结契约、仓库检查和 diff 检查均通过。QA-010 的本地完整 Live 已于 2026-09-04 通过（浏览器 3/3、runs 7/7、calls 18、input/output/total=72538/19260/91798、fallback/degraded=0），远程 Environment/Secret/full 验收于 2026-09-05 由用户暂缓，仍不得宣称远程通过。

2026-09-06 `REF-018` 标准环境 full 通过：发现 Python 510 个、非系统 442/442；系统数据、HTTP、知识、模型、会话为 13/15/13/17/10，墙钟 15.0381/17.6511/19.2154/17.6434/19.2673 秒、总计 88.8155 秒，全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（45.1 秒）通过，repository/refactor contract/diff 均通过，普通 full 的真实模型和外网调用均为 0。该任务只迁移错误、Pydantic 契约、标签/ACL 序列化和文件安全校验；Facade 的 OCR 限制与配置 patch 继续按调用实时传递，未改变 API、OpenAPI、数据库或 Job 状态机。`QA-010` 远程 Live 继续由用户暂缓。

2026-09-06 `REF-019` 标准环境 full 通过：发现 Python 515 个、非系统 447/447；系统数据、HTTP、知识、模型、会话均通过，墙钟 14.9755/23.3130/20.4623/18.6199/25.3240 秒、总计 102.6949 秒，全部预算通过；coverage 89%，Node 20/20、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17 通过，repository/refactor contract/diff 均通过，普通 full 的真实模型和外网调用均为 0。抽取器、Job 与入库迁出后，Facade 的运行时依赖仍按调用解析；QA-010 远程 Live 继续由用户暂缓，下一项为 `REF-020`。`refactor_contracts.py` 无参数检查模式已通过。

2026-09-07 `REF-020` 标准环境 full 通过：发现 Python 517 个、非系统 449/449；系统数据、HTTP、知识、模型、会话为 13/15/13/17/10，墙钟 22.4605/37.5268/34.3948/19.7824/18.1820 秒、总计 132.3467 秒，全部预算通过；coverage 89%，Node 20/20、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（47.1 秒）通过，repository/refactor contract/diff 均通过，普通 full 的真实模型和外网调用均为 0。沙箱首轮因三个 loopback fixture 无 socket 权限停止，宿主权限同命令重跑成功；个人知识文档和检索实现迁入两个 runtime 模块后，Facade 原导出、ACL、SQLite FTS/排序/引用和实时 patch 契约保持不变。QA-010 远程 Live 继续由用户暂缓，下一项为只读审计 `REF-021`。

2026-09-07 `REF-022` 标准环境 full 通过：Coordinator 五阶段目录化、依赖分组和单一状态实时视图均未改变确定性离线门的事件、Trace、Ready、Loop、降级或返回契约。定向 Agent runtime/execution/preparation/tool/ready/synthesis 39/39、`refactor_contracts.py`、`check_repository.py` 和 `git diff --check` 通过；完整质量门仍保持真实模型和外网调用为 0。完整 Live `QA-010` 仍由用户暂缓。

2026-09-07 `REF-023` 标准环境 full 通过：Intent Router 的 contracts、规则、范围、日期和路由目录化后，门面导出、规则快照、日期边界和制造范围契约不变。定向 130/130、冻结契约、仓库和 diff 检查通过；普通 full 真实模型和外网调用均为 0。

2026-09-07 `REF-024` 标准环境 full 通过：Planner 的 contracts、范围、查询、步骤和服务边界目录化后，计划契约、SQL、参数和 Ready 执行语义不变。定向 62/62、冻结契约、仓库和 diff 检查通过；普通 full 真实模型和外网调用均为 0。

## 完整审计触发条件

在发布或打标签前必须运行完整审计；以下变更也必须触发：依赖或 Python/FastAPI/SQLite 升级、Schema/API/认证/RAG/流式链路重大变化，或上次审计后累计约 5 个 feature/fix 任务。

## QA-009 基线（2026-08-30）

宿主 full 发现 476 个 Python 测试，其中 408 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 12.7/15.3/16.8/13.7/15.9 秒，总计 74.4 秒，全部低于预算。`app` 分支覆盖率 88%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 17/17（39.6 秒）；普通 full 的真实模型和外网调用均为 0。

新增 `E2E-JOURNEY-001` 至 `003` 后，稳定 E2E ID 总数为 17。确定性路径覆盖 Session 全生命周期、来源默认折叠与个人/工厂/案例分组、同文档双 chunk、三类来源导航、复制脱敏与 Trace；固定日期 dashboard、ETCH capability、knowledge/case 真实 API，以及无桌面横向溢出和未声明 browser failure 门。

首次完整 Live 尝试为 runs=3、calls=11、input/output=12672/3300、duration=128780.9ms、fallback/degraded=0，因 Admin compatibility 等待仍为 30 秒和 Markdown 列表可见文本归一化断言而失败，非 Provider fallback。修复后，用户选择只运行必要的 `FAB_LIVE_E2E_TARGET=provider-matrix`：其白名单固定 grep `LIVE-PROVIDER-001` 和 expected=5，默认完整 7-run 行为不变、非法 target fail-closed。最终五轮 Provider 矩阵为 provider=deepseek、provider_model=deepseek-v4-pro、model_id=deepseekv4-pro，runs=5 全部 success、calls=11、input/output=64753/19058、duration=298100ms、fallback/degraded=0，报告 metadata-only；断言浏览器正文首尾、Session 五轮刷新恢复、sourcePresenter 分组/link 数和 Trace/run_id 一致。两轮累计 22 calls，未超过批准的 30；未重跑非必要 Admin/personal 场景，因此不能将该结果表述为完整 7-run Live 门通过。

## REF-009 基线（2026-08-30）

宿主 full 发现 485 个 Python 测试，其中 417 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 13.6/18.2/17.5/14.1/15.6 秒，总计 79.1 秒，全部低于预算。`app` 分支覆盖率 88%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 17/17（40.0 秒）；普通 full 的真实模型和外网调用均为 0。

## REF-010 基线（2026-08-31）

宿主 full 发现 490 个 Python 测试，其中 422 个非系统测试；系统模块数据报表、HTTP/企业契约、知识与个人上传、模型治理、会话与流式分别为 13/15/13/17/10，耗时 13.5/15.4/18.0/15.6/17.0 秒，总计 79.4 秒，全部低于预算。`app` 分支覆盖率 88%，Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 17/17（41.8 秒）；普通 full 的真实模型和外网调用均为 0。
