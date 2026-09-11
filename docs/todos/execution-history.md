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

2026-08-30 `QA-007` 完成个人知识浏览器闭环：新增两条稳定 E2E ID，在真实 FastAPI、后台 Job、抽取/分块、SQLite FTS 与隔离存储上验证多选、跨选择去重/移除、共同 metadata/tags、逐项状态、首次精确 5xx 的部分失败、仅失败项重试、编辑/重命名、删除及空白文本的失败处理重试；正向上传与检索均未拦截。授权 Live 第二场景将查询键与仅文档可见值分离，验证新上传个人文档被真实模型召回、个人来源分组/跳转、复制不含实际 document/chunk/reference ID，以及删除后真实 search-preview 不再命中。最终 Live 报告两个浏览器场景 2/2（个人知识场景 6.8 秒），deepseek/deepseek-v4-pro（model_id=deepseekv4-pro）runs=6、real calls=11、input/output=69165/21325、354527.9ms、fallback/degraded=0；全部 run success，metadata-only 报告不含正文、密钥或隐藏推理。此前一次受限尝试出现 invalid_json 后 ReadTimeout 导致 contextualization 降级；随后的干净有界重跑通过，未将该临时结果作为最终验证。宿主 full 为 471/403 Python、系统 13/15/13/17/10 耗时 25.2/20.4/21.2/17.5/21.4 秒（105.6 秒）、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 12/12（36.7 秒）；普通 full 继续零真实模型和外网调用。

记录：2026-08-30 `QA-008` 完成管理端真实治理闭环。确定性 E2E 通过实际令牌表单验证错误/正确令牌、登出与真实 401 重锁；临时目录模型发布严格四能力、能力变更使兼容性失效、成功及非法参数/图片拒绝/上游不可用分类、兼容时间/健康/Trace、用户可见性与 Thinking 同步、停用/重新发布。认证流程不写 `sessionStorage`，Key 不进浏览器或数据库；HTML pattern `/v` 修复由浏览器原生合法/非法 `checkValidity()` 覆盖，稳定 ID 总数为 14。宿主 full 为 473/405 Python、系统 13/15/13/17/10 耗时 13.1/17.7/18.6/23.6/36.8 秒（109.9 秒）、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、确定性 Playwright 14/14（39.8 秒）；普通 full 继续零真实模型和外网调用。
第一次授权 Live 尝试中，管理场景在二次导航后未等待 `data-app-ready`，模型设置点击早于事件绑定，导致 900 秒超时；临时 clone 随后污染下一场景。该次失败记录为 calls=8、input/output=4423/143，是测试时序和清理缺陷，不是 Provider 质量失败。修复为二次导航等待 app-ready、模型 dialog 可见断言、30 秒普通 action timeout、afterEach 恢复原模型并退役 clone，以及 HTML pattern 修复；确定性全门通过后，经新增授权干净重跑成功。最终 Live 三个浏览器场景 3/3：deepseek/deepseek-v4-pro（model_id=deepseekv4-pro），runs=7 全部 success、real calls=22、input/output=72515/19433、duration=338309.0ms、fallback/degraded=0；报告 metadata-only，不含正文、请求体、Key 或隐藏推理。4 次短暂 ConnectError 均由重试恢复，最终未降级。

记录：2026-08-30 `QA-009` 完成桌面关键旅程收口。新增 `E2E-JOURNEY-001` 至 `003`，稳定 ID 由 14 增至 17：真实 UI/API 覆盖 Session 新建、持久化、重命名、归档、恢复、继续、批量删除和刷新恢复；来源默认折叠、个人/工厂/案例三类分组、同文档双 chunk、三类导航、复制内部 ID 脱敏与 Trace；固定日期 dashboard、ETCH capability、knowledge/case 真实 API，以及无桌面横向溢出和 browser failure monitor。最终确定性 full 为 476/408 Python、系统 13/15/13/17/10 耗时 12.7/15.3/16.8/13.7/15.9 秒（74.4 秒）、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（39.6 秒）；普通 full 未调用真实模型或外网。

首次完整 Live 尝试产生 runs=3、calls=11、input/output=12672/3300、duration=128780.9ms、fallback/degraded=0，但失败原因是 Admin compatibility `waitForResponse` 仍为 30 秒及 Markdown 列表标记与浏览器可见文本的归一化断言，而非 Provider fallback。修复为该 probe 使用 300 秒 Live 超时并在归一化中移除行首列表标记。用户选择不重跑非必要的 Admin/personal 全套；新增 fail-closed 白名单 `FAB_LIVE_E2E_TARGET=provider-matrix`，只固定 grep `LIVE-PROVIDER-001`、expected=5，默认完整 7-run 行为不变。最终用户选择的必要 Live 仅五轮 Provider 矩阵：provider=deepseek、provider_model=deepseek-v4-pro、model_id=deepseekv4-pro，runs=5 全部 success、calls=11、input/output=64753/19058、duration=298100ms、fallback/degraded=0；报告 metadata-only，正文首尾、五轮 Session 刷新恢复、sourcePresenter 真实分组/link 数、Trace/run_id 一致均已验证。两轮累计 calls=22，未超过批准的 30；该记录不代表完整 7-run Live 门已重新通过。

更新的完整测试基线统一保留在 [测试策略](../testing-strategy.md)。

2026-08-30 `REF-009` 完成 Agent coordinator 与兼容门面收口：每次调用由 `AgentCompatibilityFacade` 快照 `app.agent` namespace，保持 async/sync wrapper 语义与实时 patch；`CoordinatorRunState` 将执行流明确为 prepare、availability、model、ready、loop 五阶段，`run_agent` 继续负责运行生命周期。`app/agent.py` 由 1256 行降至 164 行，coordinator 降至 108 行；174 项定向回归、冻结契约与仓库检查均通过。宿主 full 为 485/417 Python、系统 13/15/13/17/10 耗时 13.6/18.2/17.5/14.1/15.6 秒（79.1 秒）、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（40.0 秒）；普通 full 的真实模型和外网调用均为 0。`QA-010` 的完整 7-run Live 验收仍由用户暂缓，未因本次结构重构而标记完成。

2026-08-31 `REF-010` 完成 API 基础边界收口：`app/api/` 分离 application、errors、schemas 与 dependencies，`app.main` 保留 app、lifespan、异常 handler、Pydantic schema 和个人用户/Admin 鉴权兼容导出，并在调用时保持实时 patch；URL、OpenAPI、认证、状态码和响应不变。新增 5 项 API 边界测试、78 项必要回归、冻结契约与仓库检查均通过，`app/main.py` 由 1267 行降至 1125 行。宿主 full 为 490/422 Python、系统 13/15/13/17/10 耗时 13.5/15.4/18.0/15.6/17.0 秒（79.4 秒）、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（41.8 秒）；普通 full 的真实模型和外网调用均为 0。`QA-010` 的完整 7-run Live 验收仍由用户暂缓，未因本次结构重构而标记完成。

2026-08-31 `REF-011` 完成领域 Router 收口：system、enterprise、reports、models、admin、knowledge、sessions 和 monitor 拆为 8 个 `APIRouter`，在调用时由 `app.main` namespace 提供运行时依赖，保留 `app.main` 同名兼容导出与实时 patch；Personal Job SSE 迁至 `app/api/services/personal_job_events.py`。全部 URL、HTTP 方法、认证、状态码、响应结构和 OpenAPI 保持等价；Chat、`chat_stream`、NDJSON、取消/异常处理和消息持久化留待 `REF-012`。新增 3 项 Router 边界测试，`app/main.py` 1125→697（减少 428 行）。主代理定向复验 94/94（17.909 秒），冻结契约、仓库检查与 diff 检查均通过。宿主 full 为 493/425 Python、系统 13/15/13/17/10 耗时 30.2/30.5/35.0/40.5/39.6 秒（175.8 秒，低于失败预算且接近 180 秒 warning）、覆盖率 88%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17；普通 full 的真实模型和外网调用均为 0。`QA-010` 完整 7-run Live 未运行，仍由用户暂缓且未完成；下一项为 `REF-012`。

2026-09-01 `REF-012` 完成 Chat 与流式服务收口：新增 `app/api/routers/chat.py`；`services/chat.py` 接管 `_prepare_chat`、模型能力校验/状态分类及非流式生命周期和持久化，`services/chat_stream.py` 接管 NDJSON、队列与 delivery metrics、成功、取消、HTTP/network/unexpected 错误和 finally。`app.main` 同名兼容导出与每调用 namespace patch 保持，`run_agent`、`emit` 和 helper patch 实时；URL、HTTP 方法、认证、状态码、响应、OpenAPI、事件顺序、首答、Session 关联和遥测均不变。`app/main.py` 697→352（减少 345 行），Chat Router 成为第 9 个领域模块，新增 9 项 Chat 边界测试。主代理定向复验 66/66（11.826 秒），冻结契约、仓库检查与 diff 检查均通过。宿主 full 为 502/434 Python、系统 13/15/13/17/10 耗时 13.8/15.8/17.8/15.1/16.1 秒（78.6 秒）、覆盖率 89%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（42.8 秒）；普通 full 的真实模型和外网调用均为 0。`QA-010` 完整 7-run Live 未运行，仍由用户暂缓且未完成；下一项为 `REF-013`。

2026-09-01 `REF-013` 完成 main composition 收口：新增 `app/api/runtime_dependencies.py`，显式发布 103 个 runtime dependencies 到 `app.main`，对象身份和 live `app.main.*` patch 保持；统一 bundle 注册/导出，9 个 Router bundle 及路由顺序不变。app/lifespan、错误、鉴权、schemas、Chat aliases、URL/OpenAPI、状态码与响应兼容不变。`app/main.py` 352→227（减少 125 行），达到 150～250 行目标；新增 2 项边界测试，冻结全部 103 项 runtime dependency 身份、Router export 身份、无 `_routes` 临时泄漏及无迁回领域实现。主代理定向复验 75/75（11.958 秒），冻结契约、仓库检查与 diff 检查均通过。宿主 full 为 504/436 Python、系统 13/15/13/17/10 耗时 12.8/15.7/17.9/15.7/17.4 秒（79.5 秒）、覆盖率 89%、Node 42/42、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（43.9 秒）；普通 full 的真实模型和外网调用均为 0。`QA-010` 完整 7-run Live 未运行，仍由用户暂缓且未完成；下一项为 `REF-014`。

2026-09-01 `REF-014` 完成前端核心层拆分：新增 `app/static/app/core/{state,dom,api,toast,version}.js` 五个 UMD/CommonJS+globalThis 模块，state 全字段/容器、DOM/格式、身份 headers、FabApiError/API、Toast 与版本检查等价迁移。index 保持普通 defer，core 按 state→dom→api→toast→version 在原 8 个辅助脚本前加载，原相对顺序不变、app.js 最后；冻结契约仅更新 index script_sources。错误文案、状态含义、API、Toast、版本 Banner/focus/visibility、DOM IDs 和视觉行为不变。`app/static/app.js` 1959→1879（减少 80 行），新增 8 项 `tests/app_core.test.js` 边界测试，Node 42→50。主代理定向复验 Node 50/50（1.120 秒）、44 项 Python（12.681 秒），递归 JS syntax、冻结契约、仓库检查与 diff 检查均通过。宿主 full 为 504/436 Python、系统 13/15/13/17/10 耗时 17.5/19.2/22.4/15.9/18.9 秒（94.0 秒）、覆盖率 89%、Node 50/50、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（41.8 秒）；普通 full 的真实模型和外网调用均为 0。`QA-010` 完整 7-run Live 未运行，仍由用户暂缓且未完成；下一项为 `REF-015`。

2026-09-02 `REF-015` 完成前端业务控制器拆分：新增 `app/static/app/{knowledge,model,dashboard}/controller.js` 三个 UMD/CommonJS+globalThis controller，以显式依赖注入迁移个人知识上传/文档/Job SSE、工厂知识/历史案例、Dashboard/Capability/图表及 Thinking/模型配置；`app.js` 保留同名 facade，shared state 与 `personalUploadQueue` 对象身份和事件绑定保持不变。index 维持普通 defer，leaf helpers 后加载 controller、app.js 最后；冻结契约仅更新 script_sources。DOM、API、上传队列、选择状态、Thinking、SSE 与取消语义不变。`app.js` 1879→1153（减少 726 行），新增 6 项 Node 边界测试，Node 50→56；版本和系统静态契约随新拓扑更新。主代理定向复验 JS syntax、Node 56/56（1.160 秒）、Python 59/59（17.130 秒）、冻结契约/仓库/diff 均通过，个人知识 Playwright 2/2（57.2 秒，含服务准备）。宿主 full 为 504/436 Python、系统 13/15/13/17/10 耗时 14.4536/20.5346/18.2821/16.2205/16.4219 秒（85.9129 秒）、覆盖率 89%、Node 56/56、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（42.2 秒）；普通 full 真实模型和外网调用均为 0。`QA-010` 完整 7-run Live 未运行，仍由用户暂缓且未完成；下一项为 `REF-016`。

2026-09-03 `REF-016` 完成 Session、聊天流与 Live Answer 拆分：新增 `app/static/app/chat/{presenter,controller}.js` 和 `app/static/app/sessions/controller.js`，显式注入 Markdown/来源/复制呈现、Session Library/对话状态及 NDJSON/Live Answer/重试/遥测依赖；`app.js` 保留同名 facade 与 REF-017 的布局、面板和 `init()`，由 1153 行降至 426 行。普通 defer 脚本顺序和冻结 `script_sources` 已同步，API、localStorage、stale guard、流事件、增量 Markdown、来源位置、复制、相同 client message ID 重试、取消/drain、归档与遥测不变；新增 2 项 Node 边界测试。主代理复验 JS syntax/diff、Node 58/58、Python 契约 24/24、系统五组 13/15/13/17/10 与确定性 Playwright 17/17 均通过。宿主 full 尝试完成 436/436 非系统及前三组系统断言，但 WSL 进程退出墙钟 67.2/87.6/91.6 秒使知识组超过 75 秒预算后提前停止；测试体 13/13、5.215 秒，后两组脱离 coverage 补跑 27/27。故本次只记录必要回归通过，不宣称 full 通过；最近完整 full 仍为 REF-015。`QA-010` 完整 7-run Live 未运行且仍由用户暂缓；下一项为 `REF-017`。

2026-09-05 `REF-017` 完成布局与启动收口：新增 `app/static/app/layout/controller.js` 和 `app/static/app/bootstrap.js`，迁移 `showView`、Agent 面板开合/ARIA/宽度持久化与 pointer/keyboard resize、完整页面初始化与全部事件绑定；`app.js` 由 426 行降至 89 行，保留 composition 及 late-bound layout wrapper，shared state、DOM、API、CSS、视觉和 defer 依赖顺序不变。新增 layout view/ARIA、宽度 clamp/persist、init 顺序/appReady 和迁移 selector/event 完整性回归；冻结 script_sources 更新。首次 Playwright 15/17 发现 layout 在 sessions 前创建、捕获默认 no-op `loadSessionLibrary`，两个会话旅程进入 sessionsView 后列表停在“正在加载”；未放宽测试，改为先创建 sessions、再显式注入 layout，并增加 Node 创建顺序/注入契约。修复后 targeted Journey/Workflow 6/6（28.9 秒）、最终 Playwright 17/17（46.3 秒）。宿主 full 为 Python 505 发现项、非系统 437/437，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 18.8463/19.2610/23.5279/16.7825/19.7337 秒、总计 98.1517 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7，普通门真实模型/外网为 0。递归 JS syntax、冻结契约、仓库检查及 diff 检查均通过。QA-010 仍未完成：2026-09-04 本地完整 Live 通过，2026-09-05 用户暂缓远程 Environment/Secret/full 验收；下一项为 `REF-018`。

2026-09-06 `REF-018` 完成个人知识基础边界拆分：新增 `app/personal_knowledge_runtime/{contracts,metadata,storage}.py`，将 `PersonalKnowledgeError`、Pydantic Metadata/Patch、`ExtractedSection`、标签与 ACL 序列化、文件类型/内容/图片 OCR 限制及安全路径迁出；`app.personal_knowledge` 保留原有导出，并以薄 wrapper 在调用时传入 facade 当前 OCR 限制和 `get_settings`，因此既有 patch、异常身份、自动标签顺序/上限、ACL 脱敏、错误文本、API、OpenAPI、SQLite 与 Job 状态机不变。新增 5 项模块边界测试。标准环境 full 为 Python 510 发现项、442/442 非系统；系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 15.0381/17.6511/19.2154/17.6434/19.2673 秒、总计 88.8155 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（45.1 秒）、repository/refactor contract/diff 均通过，普通 full 零真实模型/外网。QA-010 仍未完成且远程 Live 暂缓；下一项为 `REF-019`。

2026-09-06 `REF-019` 完成个人知识处理流程拆分：`extractors/` 按文本、Office、PDF、图片分工并通过 dispatcher 统一入口；`jobs.py` 接管 Job 查询、快照、进度、失败、重试、删除和待处理扫描；`ingestion.py` 接管上传、原子存储、OCR 质量门、分段和 FTS 入库。Facade 在每次调用创建依赖对象，保留可 patch 的数据库、配置、OCR 限制、OCR 函数和审计 hook。标准环境 full 为 Python 515 发现项、447/447 非系统；系统数据、HTTP、知识、模型、会话均通过，墙钟 14.9755/23.3130/20.4623/18.6199/25.3240 秒、总计 102.6949 秒且全部预算通过；coverage 89%，Node 20/20、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17、repository/refactor contract/diff 均通过，普通 full 零真实模型/外网。`refactor_contracts.py` 无参数检查模式通过。QA-010 仍由用户暂缓；下一项为 `REF-020`。

2026-09-07 `REF-020` 完成个人知识查询边界拆分：新增 `personal_knowledge_runtime/documents.py` 和 `search.py`，分别接管 Cursor/文档查询更新/文件定位与 Tag/FTS/LIKE/Chunk 检索；删除和 pending job 继续复用 `jobs.py`。Facade 508→294 行且保留原导出、异常身份和按调用解析的数据库、时间、Cursor、文档回读、查询词及 metadata/job/storage patch。主代理审查发现并修复了 Cursor、更新后详情回读和 JSON 列表转换三个隐藏 patch 兼容缺口，新增 2 项边界测试；标准环境定向及冻结契约 30/30 通过。沙箱首轮 full 因三项 loopback fixture 无 socket 权限停止，宿主权限重跑通过：Python 517 发现项、449/449 非系统；系统 13/15/13/17/10，墙钟 22.4605/37.5268/34.3948/19.7824/18.1820 秒、总计 132.3467 秒且全部预算通过；coverage 89%，Node 20/20、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（47.1 秒）、repository/refactor contract/diff 均通过，普通 full 零真实模型/外网。QA-010 远程 Live 继续由用户暂缓；下一项为只读审计 `REF-021`。

2026-09-07 `REF-021` 完成第二梯队只读审计：对 `database.py`、`answer_synthesizer.py`、`seed.py`、`planner.py`、`domain_playbooks.py` 和 `intent_router.py` 核对职责、调用方、Git 变化历史、可执行语句、完整门覆盖率与回归风险。审计没有修改产品代码；Router、Planner、Answer Synthesizer 和 SQLite 数据库层因职责/依赖边界分别形成 `REF-023` 至 `REF-026` 四项 `OPTIONAL` 候选，均不排期；`seed.py` 的确定性随机消费顺序和 `domain_playbooks.py` 的集中声明视图当前更值得保留，不建立拆分任务。主任务统计更新为 204 项、完成 160 项、待做 44 项；现有 `RAG-024`、`AGENT-039`、`REF-022` 加四项新候选后共有 7 项 `OPTIONAL`，仍不计入主统计。最近完整质量基线保持 `REF-020` full；当前除用户暂缓的 `QA-010` 外，没有可自动继续的非暂缓任务。

2026-09-07 `REF-022` 完成 Coordinator 阶段边界收口：保留 `coordinate_agent_run()` 唯一总入口，prepare/availability/model/ready/loop 五阶段迁入 `agent_runtime/stages/`，旧 `coordinator_*` 模块改为薄兼容导出。新增 `dependencies.py` 以 Preparation、Availability、Model、Ready、Loop 分组每次运行从 `app.agent` 捕获的依赖，同时经旧属性访问保持实时 patch 与既有调用兼容；`CoordinatorRunState` 继续是唯一可变事实源，新增的分组视图仅代理原字段，不复制状态。新增阶段目录、旧导入、依赖分组、状态隔离与动态 facade patch 边界测试。Agent runtime/execution/preparation/tool/ready/synthesis 定向 39/39、冻结契约、仓库和 diff 检查通过；宿主完整离线质量门通过，普通门未调用真实模型或外网。用户同时激活 `REF-023`、`REF-024`，二者转为普通待办按顺序执行；`REF-025`、`REF-026` 保持 OPTIONAL。

2026-09-07 `REF-023` 完成 Intent Router 边界拆分：新增 `intent_runtime/{contracts,rules,scope,time,routing}.py`，`app.intent_router` 保持薄兼容门面、现有导出和内部 helper 入口。未改变规则词表、排序、范围、日期、风险、语义 hint、prompt 或 dataclass 身份；新增 3 项边界快照。定向 Router/Turn/Context/Playbook/Planner/Validator/Agent preparation 130/130、冻结契约、仓库与 diff 检查通过；完整离线质量门通过，普通门真实模型和外网为 0。下一项为 `REF-024`。

2026-09-07 `REF-024` 完成 Planner 边界拆分：新增 `planning_runtime/{contracts,scope,queries,steps,service}.py`，`app.planner` 保持薄兼容门面与公开/私有入口；实现直接依赖 `intent_runtime.contracts`。Plan schema/版本/ID/JSON、SQL、参数来源、Ready 步骤顺序/依赖/预算与证据范围不变。新增边界测试；Planner/Validator/Guard/Ready/Playbook/Agent 62/62、冻结契约、仓库/diff 检查和完整离线质量门通过，普通门真实模型和外网为 0。当前没有可自动继续的非暂缓任务。

2026-09-10 `REF-027` 完成归属与兼容基线：新增版本化清单，登记 36 个 `app/*.py` 根模块及 package anchor 的目标归属、生产/脚本/测试/patch 消费者、兼容理由和退出条件；领域边界守卫检查绝对、相对、函数内及已知字面量动态导入。当前 26 条跨领域遗留边均为精确源/目标例外，清单输入、缺失领域策略、通配/格式错误与过期例外均会失败，负向 fixture 继续拒绝新增反向边和纯模块 storage/entry 依赖。主代理定向 16/16（4.671 秒）、`refactor_contracts.py` 与 repository baseline 通过；首次受限沙箱完整门仅因三项 loopback fixture 的 socket PermissionError 停止，宿主授权重跑 exit 0：536 个 Python 发现项、468/468 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 16.8838/18.9283/21.2746/16.8507/19.3026 秒、总计 93.2402 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17 通过。普通门未调用真实模型或外网；未移动业务模块或刷新行为基线，下一项为 `REF-028`。

2026-09-10 `REF-028` 完成制造领域归档：五个制造实现机械迁入 `app/manufacturing/`，39 个消费者只改为 canonical 导入，旧入口为薄兼容门面。`app.seed` 与 canonical seed 都按调用转发 live patch 的数据库/生成依赖；公开类型、函数及工具 Handler 对象身份保持。五个业务文件与 HEAD 原文件在忽略顶层 import 和 seed CLI adapter 后 AST 等价，26 条精确跨领域例外改为 canonical 源且未扩大。主代理定向 22/22（12.163 秒）与 worker 定向 87/87 通过；宿主完整离线质量门 exit 0：541 个 Python 发现项、473/473 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 16.5426/20.6775/20.2546/18.5248/20.9142 秒、总计 96.9139 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（52.2 秒）、repository/boundary/frozen contract 均通过，普通门真实模型和外网调用为 0。下一项为 `REF-029`。

2026-09-11 `REF-029` 完成存储基础归档：`database`、`department_schemas`、`execution_store` 的唯一实现机械迁入 `app/persistence/`，根路径保留薄兼容门面；19 个消费者只更新为 canonical 导入，`model_health` 与 `personal_knowledge` 继续持有本地可 patch 的 `db_session` 名称。公开/私有导出对象身份、显式提交与未提交 rollback、成功/异常连接关闭、Schema 初始化幂等和 canonical 纯模块边界均有定向测试；数据库路径、Schema、Journal、ATTACH/TEMP VIEW、FTS、迁移和中断恢复行为未变，未迁移真实数据、未激活 `REF-026`。主代理定向 24/24（7.686 秒）及 AST 审计通过；宿主完整离线质量门 exit 0：545 个 Python 发现项、477/477 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 13.9949/16.0328/18.0166/20.5391/15.7600 秒、总计 84.3435 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（41.0 秒）、repository/boundary/frozen contract 均通过，普通门真实模型和外网调用为 0。`QA-010` 远程 Live 验收仍由用户暂缓；下一项为 `REF-030`。

2026-09-11 `REF-030` 完成遥测领域归档：`audit`、`observability`、`runtime_status` 的唯一实现机械迁入 `app/telemetry/{audit,http,runtime_status}.py`，根路径保留薄兼容门面；10 个消费者只更新为 canonical 导入。ContextVar、logger/handler、锁和运行状态为跨旧/新路径共享的唯一状态；日志路径、脱敏、完整日志到期回退、事件/Trace 字段、请求关联、异常/取消与 finally 行为不变。边界测试覆盖 import 顺序单 handler、ContextVar 嵌套恢复、运行状态共享及 HTTP 成功/异常/取消生命周期；主代理定向 39/39（5.433 秒）与 AST 审计通过。宿主完整离线质量门 exit 0：550 个 Python 发现项、482/482 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 22.5104/18.3244/21.1528/33.3641/78.3291 秒、总计 173.6810 秒；会话组墙钟触发 50 秒 warning（unittest 测试体 10 项、2.983 秒），未推断原因，其余预算和总计通过。coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（58.4 秒）、repository/boundary/frozen contract 均通过，普通门真实模型和外网调用为 0。`QA-010` 远程 Live 验收仍由用户暂缓；下一项为 `REF-031`。
