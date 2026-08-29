# TODO 执行历史

状态基线：`experiment/parallel-platform`，归档于 2026-08-28。

本文件只保留已完成任务的历史执行顺序和阶段检查点，不是任务状态来源，不使用复选框，不参与任务统计。任务的定义和完成状态始终以各分类 TODO 为准。

## 已完成补丁队列

| 历史顺序 | 任务 | 交付主题 |
|---:|---|---|
| 1 | `QA-001` | 全量测试治理 |
| 2 | `UX-027` | 统一个人知识上传入口 |
| 3 | `UX-018` | 个人文档元数据编辑 |
| 4 | `UX-026` | 个人知识批量上传工作台 |
| 5 | `AGENT-024` | 连续对话来源偏好理解 |
| 6 | `RAG-022` | 中文领域实体与双语召回治理 |
| 7 | `UX-019` | 来源折叠、分组与去重 |
| 8 | `UX-021` | 个人知识重命名 |
| 9 | `AGENT-025` | 通用制造运营概览路由与范围下推 |
| 10 | `AGENT-026` | 未知制造范围解析门禁 |
| 11 | `AGENT-027` | 制造范围证据契约 |
| 12 | `AGENT-028` | 基于 Session 消息 ID 的历史回忆 |
| 13 | `AGENT-029` | 上下文协议容错与失败降级 |
| 14 | `AGENT-030` | 回忆审计范围一致性 |
| 15 | `AGENT-031` | 推理型上下文空响应恢复 |
| 16 | `AGENT-032` | 语义助手对话路由与降级披露 |
| 17 | `RAG-023` | 入库自动 Tag 与人工修订保护 |
| 18 | `OBS-015` | 端到端流式停顿诊断 |
| 19 | `UX-020` | 流式中途停滞修复 |
| 20 | `UX-022` | 增量 Markdown DOM 渲染 |
| 21 | `UX-023` | 自然流式回答呈现 |
| 22 | `UX-028` | 实时回答复制顺序 |
| 23 | `AGENT-034` | 上下文四态安全降级与语义能力路由 |
| 24 | `OBS-016` | 降级运行可观测性、关联与监控聚合 |
| 25 | `AGENT-035` | TurnDecision 会话动作与真实能力目录 |
| 26 | `AGENT-036` | DecisionArbiter、活动 Flow、来源追踪与任务 Guard |

## 已完成主队列

| 历史顺序 | 任务 | 交付主题 |
|---:|---|---|
| 1-8 | `AGENT-009`、`AGENT-010`、`AGENT-011`、`AGENT-016`、`AGENT-012`、`AGENT-013`、`AGENT-014`、`AGENT-015` | Router、Playbook、Planner、预算、Validator、Synthesizer、持久化与黄金集 |
| 9-17 | `MODEL-014`、`MODEL-015`、`UX-017`、`MODEL-009`、`MODEL-016`、`MODEL-017`、`MODEL-013`、`AGENT-033`、`MODEL-018` | Provider、能力、Thinking、兼容测试与模型可靠性 |
| 18-24 | `UX-012`、`RAG-011`、`RAG-012`、`RAG-016`、`UX-013`、`UX-014`、`UX-015` | 桌面 Playwright、OCR、进度 SSE、关键工作流、无障碍与视觉回归 |
| 25 | `OBS-014` | 完整日志显式测试开关、24 小时到期回退与管理端策略可见性 |
| 26 | `AGENT-037` | 通用范围安全证据语义与制造声明 fail-closed 验证 |
| 27 | `AGENT-038` | ready 计划服务端确定性执行、仅综合模型路径与离线性能门 |
| 28 | `OBS-017` | Trace 版本、引用计数、仲裁候选、六阶段耗时与旧日志兼容治理 |
| 29 | `QA-004` | 脱敏离线 Trace 回放、跨层黄金矩阵、流式持久化与零外部调用门禁 |
| 30 | `DEPLOY-012` | GitHub Actions 完整质量门、Hosted Runner 视觉环境固定与分支 required check |
| 31 | `REF-001` | Agent 工具目录与模型流协议叶子模块提取，保留兼容入口且不调整主编排 |
| 32 | `REF-002` | 版本化离线重构兼容契约，覆盖工具、Agent/Trace/SSE、OpenAPI/HTTP 与前端 DOM/脚本顺序 |
| 33 | `REF-003` | Agent Runtime contracts、telemetry 与协调入口，保留旧入口和高频 patch 点 |
| 34 | `REF-004` | Context、Router、DecisionArbiter、Playbook 与 Planner 准备阶段等价迁移 |
| 35 | `REF-005` | 工具 Schema、注册表与单次执行器目录化，保留唯一 catalog/registry 对象 |
| 36 | `REF-006` | Ready Plan、兼容 Agent Loop 与模型失败传播执行阶段迁移 |
| 37 | `REF-007` | 通用知识检索、来源过滤、降级披露与引用阶段迁移，保留 Agent 实时 facade |
| 38 | `REF-008` | Ready 综合、离线降级、结构化提交解析与最终结果组装阶段迁移 |

`DATA-016` 的市场锚点模拟数据和 `UX-028` 的回答复制顺序也在这一阶段完成；它们的状态分别以企业数据和用户体验分类 TODO 为准。

## 已完成阶段检查点

### 检查点 A：Agent 执行架构

`AGENT-009` 至 `AGENT-016` 相关结构化路由、Playbook、Planner、运行时守卫、Validator、Synthesizer、持久化和黄金集已完成，并经 CMP、光刻、刻蚀、批次追踪和 SOP 路径回归。

### 检查点 B：模型运行可靠性

2026-08-12 宿主 full 质量门全通过：263 个 Python 发现项，198 个非系统测试；系统数据 12、HTTP 15、知识 12、模型 17、会话 9；分支覆盖率 86%，Node 32，RAG 15/15，Playbook 12/12。管理员能力声明、显式兼容性测试、structured context、DeepSeek Thinking answer/tool roundtrip、能力约束和离线降级已收口。

### 检查点 C：OCR 与浏览器交互

2026-08-19 `UX-015` 宿主 full 质量门全通过：327 个 Python 发现项，261 个非系统测试；系统数据 12、HTTP 15、知识 13、模型 17、会话 9；分支覆盖率 87%，Node 35、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Playwright 10/10。桌面长回答和个人知识超长多语言文件名的两张 Chromium 视觉基线已生成、人工检查并在非更新模式复验，系统测试总耗时 75.1 秒且低于预算。

2026-08-20 `OBS-014` 宿主 full 质量门全通过：333 个 Python 发现项，267 个非系统测试；系统数据 12、HTTP 15、知识 13、模型 17、会话 9；分支覆盖率 87%，Node 契约文件 13/13、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Playwright 10/10。系统测试总耗时 82.4 秒且低于预算，完整内容日志的显式测试开关、服务启动后最长 24 小时窗口、到期实时回退和管理端只读策略展示均已收口。

### 检查点 D：上下文安全降级与运行可观测性

2026-08-23 `AGENT-034` 与 `OBS-016` 宿主 full 质量门全通过：发现 358 个 Python 测试，其中 292 个非系统测试；系统模块分别为数据报表 12、HTTP/企业契约 15、知识与个人上传 13、模型治理 17、会话与流式 9；总耗时 90.3 秒，分支覆盖率 87%，Node 36、RAG 15/15、OCR 黄金集 8/8、Playbook 12/12、Playwright 桌面 10/10。上下文失败不再伪造历史歧义，降级 Run、阶段时延与消息持久化关联均可审计。

2026-08-23 `AGENT-036` 针对性回归通过：`tests.test_turn_decision`、`tests.test_intent_router`、`tests.test_context_resolver` 共 87 项。覆盖真实“介绍一下你自己→你有什么功能→具体一点”失败链、文档/知识库/规范扩写变形、显式 SOP/良率/制程任务切换、旧 metadata 与低置信度安全退化，以及同任务 Flow 续接、跨任务拒绝和原始问题对 Planner 的受控传递；未执行完整质量门时不将其表述为 full 结果。

2026-08-23 `AGENT-038` 宿主 full 质量门全通过：395 个 Python 发现项、328 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 9；分支覆盖率 86%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 确定性执行合成基准 3/3、Playwright 10/10。系统测试总耗时 76.0 秒且低于预算；ready 计划不再让模型选择业务工具，并在验证前禁止正文输出。

2026-08-23 `OBS-017` 宿主 full 质量门全通过：401 个 Python 发现项、334 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 9；分支覆盖率 86%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Playwright 10/10。系统测试总耗时 80.5 秒且低于预算；审计 schema 1.4、旧 Trace 归一化、三类引用计数、安全仲裁候选和六阶段耗时均由契约测试覆盖。

2026-08-24 `QA-004` 宿主 full 质量门全通过：408 个 Python 发现项、340 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统测试总耗时 84.3 秒且低于预算；通用问题、CMP 制程能力和整厂综合三条脱敏链路均通过路由、动作、计划、范围、工具、证据、提交、流式与持久化断言，普通质量门没有真实 LLM 或网络调用。

2026-08-24 `DEPLOY-012` 完成远程 CI 收口：`.github/workflows/quality.yml` 在 Ubuntu 24.04、Python 3.11、Node 22 与显式 Noto 字体环境执行 full 质量门，并只在失败时上传限定诊断目录。`experiment/parallel-platform` 分支已启用严格同步的 `Full quality gate` required check，且绑定 GitHub Actions App，避免同名外部状态冒充通过。

2026-08-25 `REF-001` 宿主 full 质量门全通过：411 个 Python 发现项、343 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统测试总耗时 88.3 秒且低于预算；工具目录和模型流协议迁出后，`app.agent` 的旧导出、测试 patch 点、事件与调用路径保持兼容。

2026-08-26 `REF-002` 宿主 full 质量门全通过：416 个 Python 发现项、348 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统测试总耗时 80.0 秒且低于预算；版本化离线契约固定工具完整 Schema、三条 Agent 回放的结果/轨迹/事件、完整 OpenAPI、51 条路由以及两端 DOM ID 与脚本顺序，契约采集期间真实模型和网络调用均为 0。

2026-08-26 `REF-003` 宿主 full 质量门全通过：424 个 Python 发现项、356 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统模块耗时依次为 12.4、18.4、16.6、13.6、15.8 秒，总计 76.8 秒，全部低于预算；新增 8 项 Agent Runtime 边界测试，冻结 `refactor_contract_v1.json` 兼容契约通过。

2026-08-26 `REF-004` 宿主 full 质量门全通过：430 个 Python 发现项、362 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统模块耗时依次为 12.2、14.1、16.1、12.7、14.8 秒，总计 69.8 秒，全部低于预算；新增 6 项准备阶段边界测试、116 项定向回归与冻结 `refactor_contract_v1.json` 兼容契约通过，`app.agent` 已由 2860 行降至 2476 行（减少 384 行）。

2026-08-27 `REF-005` 宿主 full 质量门全通过：435 个 Python 发现项、367 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统模块耗时依次为 14.6、13.5、15.8、12.7、15.9 秒，总计 72.5 秒，全部低于预算；新增 5 项工具运行时边界测试、108 项定向回归与冻结 `refactor_contract_v1.json` 兼容契约通过。工具 catalog/registry 保留唯一对象身份，`app.agent` facade 继续在调用时读取实时 patch registry。

2026-08-28 `REF-006` 宿主 full 质量门全通过：438 个 Python 发现项、370 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统模块耗时依次为 12.3、15.3、17.6、13.2、14.9 秒，总计 73.2 秒，全部低于预算；新增 3 项执行边界测试、105 项定向回归与冻结 `refactor_contract_v1.json` 兼容契约通过。`app.agent` 由 2478 行降至 1801 行（减少 677 行）；Ready 仍由服务端确定性执行，模型业务工具选择数为 0，兼容 patch 注入及重试/首个正文前降级语义保持不变。

2026-08-28 `REF-007` 宿主 full 质量门全通过：442 个 Python 发现项、374 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 87%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统模块耗时依次为 13.7、15.5、17.3、13.9、15.7 秒，总计 76.1 秒，全部低于预算；`agent_runtime/retrieval/general_knowledge.py` 接管查询重写、scope 检索、来源过滤、ToolLoopGuard、Observation/Trace、进度/审计、RetrievalDecision 与降级披露，`app.agent` 保留实时依赖注入 facade。新增 4 项离线边界测试、94 项定向回归与冻结 `refactor_contract_v1.json` 兼容契约通过；`app.agent` 由 1801 行降至 1613 行（减少 188 行）。

2026-08-28 `REF-008` 宿主 full 质量门全通过：452 个 Python 发现项、384 个非系统测试；系统数据 13、HTTP 15、知识 13、模型 17、会话 10；分支覆盖率 88%，Node 36/36、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 基准 3/3、Trace 回放 7/7、Playwright 10/10。系统测试总耗时 73.5 秒，全部低于预算；`agent_runtime/synthesis/` 接管 Ready synthesis、离线降级、结构化提交解析及最终结果组装，`app.agent` 保留实时依赖注入 facade。新增 10 项合成边界测试、141 项定向回归、冻结 `refactor_contract_v1.json` 兼容契约及仓库检查通过；原始正文空白与实时 fallback facade patch 保持兼容，`app.agent` 由 1613 行降至 1256 行（减少 357 行）。

2026-08-29 `QA-005` 完成桌面 E2E 基础契约：10 条 Chromium 用例改用自动 browser failure fixture，未声明的 `pageerror`、`console.error`、同源 `requestfailed` 和 HTTP 5xx 均会失败；工作流中唯一允许的 jobs SSE `ERR_ABORTED` 以 method/path/error 就地声明。版本化 `e2e_critical_paths.json` 与 Node 契约只从 `test(...)` 标题发现稳定 ID，阻止删除、重复或注释残留伪通过；服务诊断覆盖快照准备、端口启动和禁用环境代理的真实 loopback `/api/health`。针对性 Node 3 项、Python 20 项和 Playwright 清单 10 条均通过；宿主三次独立 Playwright 为 10/10，耗时 26.6、27.7、27.0 秒。宿主 full 发现 455/387 个 Python 测试、分支覆盖率 88%、Node 契约文件 15/15、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 10/10；系统测试总计 78.2 秒并低于预算。

2026-08-29 `QA-006` 完成真实模型与故障协议双通道 E2E：loopback OpenAI 兼容夹具覆盖 429、500、非法 JSON/SSE、首正文超时、截断 partial response 与 graceful 缺失 `[DONE]`；Live server 使用隔离快照、服务端密钥、metadata-only 报告、DeepSeek Thinking 32768 token ready synthesis 与 Live-only 4 次重试。`deepseekv4-pro` 真实兼容性于 2026-08-29T05:52:38.410+00:00 通过（12556.2ms，7 项检查，context_chars=32768）。授权 Chromium `LIVE_PROVIDER` 五轮矩阵 5/5 通过：provider=deepseek、provider_model=deepseek-v4-pro、calls=9、input/output=66859/22083、313235.3ms、fallback/degraded=0；全部 run success，报告未保存正文、密钥或隐藏推理。宿主 full 为 471/403 Python、系统 13/15/13/17/10 耗时依次为 12.5/13.4/15.8/13.6/15.9 秒、共 71.2 秒、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 10/10（28.9 秒）；浏览器与模型治理测试显式安排隔离模型目录基线，不依赖可变的 Admin 参考状态；普通 quick/full 继续零真实模型和外网调用。

更新的完整测试基线统一保留在 [测试策略](../testing-strategy.md)。
