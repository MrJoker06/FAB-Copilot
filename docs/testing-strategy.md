# 测试策略与质量门

## QA-001 审计基线（2026-08-01）

审计前有 166 个 Python 测试、19 个 JavaScript 断言和 15 条 RAG 黄金集。完整宿主 Python 回归当时有 2 个失败；`app` 分支覆盖率为 81%。低覆盖重点为 `seed.py`（25%）、`database.py`（76%）、`agent.py`（77%）、`context_resolver.py`（78%）和 `personal_knowledge.py`（80%）。在 coverage run 中，`scripts/evaluate_rag.py`、`scripts/manage_databases.py` 和 `scripts/smoke_stream.py` 均为 0%；其中 RAG 评估另以独立命令实际通过 15/15。

系统测试现有 54 项，按数据报表、知识与个人上传、HTTP/企业契约、模型治理、会话与流式拆分至 `tests/system/`。完整门为每个模块启动独立进程：fixture 在导入 app 前以 SQLite backup 创建参考部门数据库的一致临时快照，并使用独立个人知识目录、日志目录，进程退出时清理。Playwright 覆盖 1440x900 Chromium 的用户总览、管理端锁定/已认证工作区，以及真实隔离 FastAPI 上的模型 Thinking 能力切换、个人知识上传就绪、Thinking 流式回答与会话归档；Axe WCAG 2.0/2.1/2.2 A/AA（含颜色对比度）扫描用户关键视图/模型对话框和管理端认证、运行、模型目录与发布对话框，并验证键盘导航、Dialog 焦点和认证弹窗 Escape 策略。视觉回归使用固定 `zh-CN`、`Asia/Hong_Kong`、浅色主题、CSS 像素缩放和 reduced motion，覆盖长 Markdown 回答及超长多语言个人知识文件名，并同时断言页面与目标区域没有横向溢出。它使用 8899 临时服务、隔离快照和固定测试令牌，不调用真实模型；临时 AI 运营库固定提供一个不支持和一个支持 Thinking 的已发布模型，视觉内容也只写入临时 AI 运营库和知识库快照。失败时保留 trace 与截图至被 Git 忽略的 `test-results/` 和 `playwright-report/`；移动端不在本项范围。

## 分层与原则

- 单元测试覆盖纯规则、解析、计划、RAG 决策和质量门命令构造。
- HTTP 契约测试覆盖公开 API 的成功、认证、脱敏和输入边界；系统测试覆盖跨库与后台任务工作流。
- RAG 黄金集独立评估召回、来源覆盖和禁止命中；Playbook 黄金集以固定日期驱动真实 Router、Playbook 选择和 Planner，并断言严格工具路径、必需证据覆盖与预算一致性；两者均不访问真实模型。
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

快速门运行非 `tests.system.*` Python、全部 Node 测试、全部静态 JS 语法检查、RAG 黄金集和 Playbook 黄金集：

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

```bash
python scripts/run_quality_gate.py full
```

质量门在执行前以 AST 统计 unittest 风格测试方法，避免导入测试时污染环境；发现少于最近完整审计确认的 175 个测试即失败。只有完整审计确认的有意删测才能调整此基线；命令首次失败即非零退出。覆盖数据写入 `runtime/quality/`，Playbook 报告同时写入 `runtime/quality/playbook_gold_report.json`。

## 完整审计触发条件

在发布或打标签前必须运行完整审计；以下变更也必须触发：依赖或 Python/FastAPI/SQLite 升级、Schema/API/认证/RAG/流式链路重大变化，或上次审计后累计约 5 个 feature/fix 任务。
