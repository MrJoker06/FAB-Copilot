# TODO 执行历史

状态基线：`experiment/parallel-platform`，归档于 2026-08-28。

本文件只保留已完成任务的历史执行顺序和阶段检查点，不是任务状态来源，不使用复选框，不参与任务统计。未完成定义以各分类 TODO 为准；已完成定义与验收见[完成索引](completed.md)及对应归档。

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

2026-09-12 `REF-031` 完成模型访问归档：`model_registry`、`model_compatibility`、`model_health`、`model_streaming` 的唯一实现迁入 `app/model_gateway/{registry,compatibility,health,streaming}.py`，根路径保留兼容门面；10 个消费者只更新为 canonical 导入。管理员显式配置与主动探针、Thinking 策略、流式解析、重试、熔断和恢复租约不变；非 health 的公开类型、异常和函数对象身份保持。health 的旧/新公共 wrapper 为刻意独立函数以保留 `app.model_health.db_session` 的 live patch，但签名和单一 SQL 实现保持一致；导入顺序测试确认不触发 Provider 网络访问。主代理定向 37/37（0.951 秒）及 AST 审计通过；宿主完整离线质量门 exit 0：555 个 Python 发现项、487/487 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 15.080060437/17.058814557/19.944656240/16.225540532/19.084223758 秒、总计 87.393515570 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（43.7 秒）、repository/boundary/frozen contract 均通过，普通门真实模型和外网调用为 0。`QA-010` 远程 Live 验收仍由用户暂缓；下一项为 `REF-032`。

2026-09-12 `REF-032` 完成会话与运行时归档：`context_resolver`、`turn_decision`、`decision_arbiter`、`sessions` 的唯一实现机械迁入 `app/conversation/`；`assistant_capabilities` 迁入 `app/agent_runtime/`，`loop_guard` 迁入 `app/agent_runtime/execution/`，六个模块均保留根路径薄兼容门面。旧/新入口的公开和私有导出对象身份保持，`MODULE:app.context_resolver` 冻结字面量未变；15 个消费者仅更新 canonical 导入。原问题与补全问题来源、意图决策、消息 ID、幂等、历史回忆、Session 归档/恢复/删除、Agent 预算及停止条件不变。六个实现体忽略 import 后 AST 等价；主代理定向 99/99（15.629 秒）、最终新增边界测试 5/5（4.929 秒）、冻结契约、仓库、边界和 diff 检查均通过。宿主完整离线质量门在恢复后重跑 exit 0：560 个 Python 发现项、492/492 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 13.681662739/17.997523946/18.400096835/16.220875455/18.302686829 秒、总计 84.6030422 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（44.5 秒）、repository/boundary/frozen contract/diff 均通过。此前完整门会话在恢复时丢失最终输出，故以持久化的 `runtime/quality/ref032-full-resumed.log` 重跑结果为唯一验收依据；普通门未调用真实模型或外网，未变更数据库、Schema 或产品行为。`QA-010` 远程 Live 验收仍由用户暂缓；下一项为 `REF-033`。

2026-09-12 `REF-033` 完成知识与证据归档：`rag`、`knowledge_decision`、`ocr`、`ocr_quality` 的唯一实现机械迁入 `app/knowledge/`，`evidence_semantics`、`evidence_validator`、`answer_synthesizer` 迁入 `app/evidence/`；七个根入口均保留薄兼容门面。FTS 查询、ACL、Tag/排序/limit、引用、声明守卫、降级和最终渲染不变；OCR 单例和推理锁跨旧/新入口共享，并继续从 `rapidocr.__file__` 定位本地 wheel 资源。个人知识 facade 的既有 patch 命名空间保留，`semantics` canonical 仍受纯模块网络负例保护，未激活 REF-025 或重复个人知识运行时。七个实现体忽略 import 后 AST 等价，消费者只更新 canonical 导入及两个测试文件中的 OCR/RAG 内部 patch 字面量；冻结 capability `MODULE:app.evidence_validator`/`MODULE:app.answer_synthesizer` 未变。主代理定向 52/52（6.882 秒）、边界/冻结契约/仓库/diff 检查通过。宿主完整离线质量门 exit 0：565 个 Python 发现项、497/497 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 19.057910855/17.129691909/20.299146184/16.508507279/21.130809872 秒、总计 94.126279141 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（42.7 秒）均通过。结果保存于被 Git 忽略的 `runtime/quality/ref033-full-parent.log`；普通门未调用真实模型或外网，`QA-010` 远程 Live 验收仍由用户暂缓；下一项为 `REF-034`。

2026-09-13 `REF-034` 完成兼容入口退役与收口：17 个内部消费者只更新 import 至 canonical 运行时，未改业务行为；29 个已无内部 Python 生产/脚本消费者的过渡 facade 由 AST 清单精确比对并禁止回流，覆盖相对、多名称、函数内和字面量动态导入，fixture 字符串不误判。没有外部消费者迁移证据，因此未删除公开 facade；36 个根入口继续保留，`main`、`agent`、`personal_knowledge`、`config`、`identity` 为长期锚点，`seed` CLI 与 `model_health.db_session` patch 维持明确兼容合同。`allowed_domain_dependencies` 未扩大；旧的 `app.agent_runtime.compatibility -> app.intent_router` 单一例外由 `intent_runtime.contracts`、`routing`、`rules` 三条精确 canonical 边替代，例外总数 28。主代理定向 47/47（11.320 秒）、冻结契约、仓库、边界和 diff 检查通过；宿主完整离线质量门 exit 0：569 个 Python 发现项、501/501 非系统测试，系统数据/HTTP/知识/模型/会话 13/15/13/17/10，墙钟 15.599845838/16.172799632/17.754458358/15.565569326/16.426263403 秒、总计 81.519137426 秒且全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（45.7 秒）均通过。结果保存于被 Git 忽略的 `runtime/quality/ref034-full-parent.log`；普通门未调用真实模型或外部服务。`REF-027` 至 `REF-034` 系列已收口，当前没有可自动继续的非暂缓任务。

2026-09-13 `REF-035` 完成用户新增的实际目录精简要求：`app/` 根目录由 37 个 Python 文件收敛为 `__init__.py` 与 `main.py`；配置、身份、Agent 与个人知识入口分别迁至 `core/settings.py`、`core/identity.py`、`agent_runtime/service.py`、`personal_knowledge_runtime/service.py`，删除 31 个旧兼容文件，35 个旧 Python 模块路径明确退役。`app.main:app`、HTTP API、页面、数据位置与业务行为不变，seed CLI 改用 `python -m app.manufacturing.seed`；不通过别名或重复实现保留旧路径。四个搬迁实现 AST 等价（除导入和配置路径层级），19 个已有应用文件仅改变导入/文档路径；原领域许可不扩大，28 条精确例外同步至新路径。主代理定向 63/63 核心与启动测试（6.926 秒）、29/29 领域边界测试（12.024 秒）、冻结契约与仓库检查通过。首次 full 的能力目录旧标识导入测试失败已修复；2026-09-13 `REF-035` 宿主完整离线质量门重跑 exit 0：发现 576 个 Python 测试，508/508 非系统测试（67.545 秒），系统数据/HTTP/知识/模型/会话 13/15/13/17/10 全通过，墙钟 20.381070265/17.895252597/21.359629731/17.605863887/24.480409194 秒、总计 101.722489564 秒，全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（43.4 秒）均通过。结果保存于被 Git 忽略的 `runtime/quality/ref035-full-parent-rerun.log`；普通门未调用真实模型或外部服务。 任务总计 216 项，完成 172 项，剩余 44 项均属暂缓，4 项 OPTIONAL 未激活。

2026-09-26 `MEM-001` 至 `MEM-004` 完成 Memory System 结构抽离：`app/memory_system/` 统一拥有上下文契约、协议、历史选择、解析与分阶段消息片段；API 通过 HistoryReader 复用 Session 单次读取及原有归属校验，Agent 适配器保留模型、事件、健康与实时 patch，ready 不新增历史。生产消费者迁至 canonical 导入，旧 `conversation.context_resolver` 仅保留兼容转发；长期记忆 B3 仍为 OPTIONAL。主代理逐阶段独立复验 A1 107、A2 116、A3 135、A4 59、A5 21 项定向测试及边界、仓库、冻结契约。最终宿主完整离线质量门 exit 0：发现 605 项 Python 测试，536/536 非系统和系统 13/15/13/17/11 全通过、系统墙钟 102.588 秒，覆盖率 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（45.4 秒）均通过。首次浏览器用例因 `ERR_NETWORK_CHANGED` 瞬断失败，单项与完整门重跑通过；普通门未调用真实模型。用户已有 `tests/test_context_resolver.py` 改动保留，阶段验证完成；按用户后续要求以一个汇总提交交付，排除该用户测试，原逐阶段提交计划未落实。下一项为 `AGENT-040`。

2026-10-15 `AGENT-040` 完成证据契约与答案展示分离：`AnswerContract.presentation` 基于当前请求优先、恢复任务回退的确定性规则选择简答、表格、完整报告或默认简洁摘要；Ready、Loop 及可用性回退均透传格式上下文。所有展示继续使用验证后的声明、有效引用与强制限制，空章节不再输出占位，通用知识降级保留来源披露，`not_applicable` 直接回答不变。冻结 `refactor_contract_v1.json` 仅因默认简洁输出在两条离线 Agent 案例减少一个 `answer_delta` 分片而更新，事件语义和字段未变。主代理定向复验 58/58、仓库边界检查通过；最终 WSL 完整离线质量门 exit 0：发现 613 项 Python 测试，544/544 非系统、系统 13/15/13/17/11 全通过且墙钟 111.455 秒低于预算，覆盖率 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（48.5 秒）均通过。首次完整门有一条旧标题断言失败，按预期格式变化更新；另一次浏览器全套中会话旅程时序失败，单项与最终完整门复跑通过。普通门真实模型和外网调用为 0；下一项为 `AGENT-041`。

2026-10-16 `AGENT-041` 完成逐声明证据支持评估：Validator 为实际观测的调用引用记录证据项覆盖、风险与冲突，Synthesizer 将事实、推断和结论分别审计为 `supported`、`limited` 或 `unsupported` 并记录原因；全局覆盖和限制仍作为任务级信息。良率下降的直接观测可保留，缺失的根因证据只降级依赖该证据的声明；错误引用、结构化范围/时间/粒度不匹配及真实共享冲突继续 fail-closed。EvidenceValidation schema 1.2、AnswerSynthesisReport schema 1.1 为兼容扩展，旧字段保留，冻结行为快照未重录。主代理定向复验 51/51；最终在 WSL 原生文件系统的临时 Git 副本（四个源码/测试补丁逐字一致，并复制五个模拟部门数据库、链接既有 Node 依赖）执行完整离线质量门 exit 0：发现 620 项 Python 测试，551/551 非系统，系统 13/15/13/17/11 全通过、墙钟 19.742 秒且低于预算；覆盖率 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（49.2 秒）均通过。原 `/mnt/d` 工作树首次 full 因知识组测试体全通过但墙钟 81.6 秒超过 75 秒预算停止；第二次 full 的 16/17 浏览器用例通过，跨视图用例因导航取消请求 `ERR_ABORTED` 偶发失败，单项复跑 1/1 通过；未放宽门槛或修改该用例。普通质量门未调用真实模型或外网；下一项为 `AGENT-042`。

2026-10-16 `AGENT-042` 完成多证据综合推断协议：`submit_analysis` 可选版本 `2.0`，调用级直接事实由服务端补全已知 kind/grain，模型仍声明语义、范围、时间和角色；综合推断以已验证事实索引关联多个来源，要求面向用户的依据与不确定性，结论再关联已验证推断。范围、时间、背景角色、非法引用和不支持协议均保守拒绝；旧协议及历史报告仍可读取，模型通用知识回退继续使用旧协议，不保存隐藏思维链。AnswerContract/AnswerSynthesisReport schema 1.2 为兼容扩展。冻结 `refactor_contract_v1.json` 仅更新 `submit_analysis` 工具 Schema 哈希：新增版本及事实/推断索引字段，旧工具名、API、前端和离线 Agent 事件基线不变。主代理独立复验定向 52/52、冻结契约 5/5、仓库检查通过；WSL 使用 Conda Python 与 Node 22 的最终完整离线质量门 exit 0：发现 625 项 Python 测试，556/556 非系统、系统 13/15/13/17/11 全通过且墙钟 91.009 秒低于预算，覆盖率 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（46.5 秒）均通过。前两轮分别因默认 Node 18 不满足 Playwright 要求和临时 PATH 漏掉 Conda Python 停止；最终门未调整测试或阈值，未调用真实模型或外网。下一项为 `AGENT-043`。

2026-10-17 `AGENT-043` 完成因果与确定性措辞治理：答案综合器按子句判定肯定因果/根因断言、否定证明、疑问、假设和通用机理，关键词只作为候选信号；逗号、分号及转折后的独立断言不能被前句谨慎措辞掩盖。直接事实中的疑问、假设和诊断性根因表述降级；有趋势证据的“已经证实良率下降”仍保留，未证明的确定性根因继续拒绝。披露的模型通用知识可说明一般机理，但带当前生产或命名设备范围的因果结论不能借此取得豁免。规则是固定离线判定，不宣称通用自然语言理解。旧/v2 引用与范围协议、历史结果及冻结契约未变。主代理定向复验 57/57、冻结契约 5/5、仓库检查通过；WSL 完整离线质量门 exit 0：发现 627 项 Python 测试，558/558 非系统、系统 13/15/13/17/11 全通过且墙钟 94.749 秒低于预算，覆盖率 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（46.7 秒）均通过；未调用真实模型或外网。下一项为 `AGENT-044`。


## 2026-11-12 从执行计划迁出的历史记录

以下内容按原文保留，当时的队列、目录、分工和测试数量不是当前状态。

历史检查点（2026-11-10，MOD-024）：首批三个 Profile 的组合交付与两端独立安装通过，原值见 [报告](../reports/mod-024-module-delivery.md)。当前成员口径与验证见 [MOD-031 报告](../reports/mod-031-validator.md)，不以该历史结果替代本次验收。

历史检查点（2026-11-11，MOD-031）：a～e 已实现并按基线对照验收，见 [报告](../reports/mod-031-validator.md)。Windows 全量 1467 项保留同名 12 失败/10 错误，full 未通过；两平台仓库外交付、定向及 Linux 浏览器通过。本版纳入 MOD-031 提交；模块化待做 9 项（020～023、025～029），产品 228/183/45 不变，029 保持暂缓。MOD-030 的历史验收见 [030e](../reports/mod-030e-acceptance.md)。

以下为历史检查点，不能据此覆盖上述最新状态。


最新检查点（2026-11-07，MOD-015e）：MOD-015 全部五批已验证。015e 新增 `tests/test_runtime_convergence_acceptance.py`（11 项），对类型化应用（Skill 关闭、Skill 文件根、Skill 发布库）× Ready/Loop 和旧 `service.run_agent` 的 Loop/Ready/上下文解析，分别跑成功、模型调用中取消（类型化 Ready 为计划执行中取消）、模型异常、工具异常和 Skill 重新校验失败（组装后禁用发布或改动 manifest，`new_run` 在预算工厂之前拒绝）。每次失败后无残留任务，脚本模型和网关会话全部退出/关闭，每 Run 新建预算与 Dispatcher，发布库状态和 Skill 快照、`runtime_status`、身份 ContextVar、存储/身份绑定、`service.TOOLS`/`TOOL_HANDLERS` 身份与内容不变，后续运行与首次干净运行逐项相等；三种注入泄漏的变异自检均被发现。未发现运行时泄漏（测试中的 SQLite `ResourceWarning` 经 tracemalloc 追溯全部来自测试夹具）。`decision_arbiter` 改用只读 `DecisionContext`，`evidence.validator` 改用五个只读计划/Playbook 视图，债务 14→11；其余 MOD-015 台账项（6 条债务、3 个过渡文件、7 个兼容入口、19 条 DB 来源、`legacy_sql_tool`、2 条边界例外）保留并改挂 MOD-027，台账中不再有 exit_task 为 MOD-015 的条目。WSL 全部 169 个模块 1301 项与 HEAD 逐模块对照无新增失败，Windows 定向 37 模块 412 项只剩与 HEAD 一致的既有环境失败（反斜杠断言 19、WinError 32 ×8、WinError 1314 ×1）；新测试两端各连续 3 次通过；282 文件/零边界错误，7 入口、消费记录 92→94、26 DB 候选；ruff check 无新增，新文件 format 0 偏差。未运行性能门。保留的 `run_agent` facade 与配置锚点归 MOD-027，见 [报告](../reports/mod-015-runtime-convergence.md)。以下保留历史检查点。

最新检查点（2026-11-07，MOD-015d）：存储/身份依赖注入 Port 已验证，零行为变化。新增只含标准库的 `app/core/storage_identity_ports.py`（`PrincipalView`、冻结的 `StorageIdentityBindings` 七项绑定、`install_storage_identity`/`storage_identity_bindings`，未安装时抛出写明安装函数的 `StorageIdentityNotConfiguredError`）、`app/bootstrap/storage_identity_assembly.py`（默认绑定在调用时读取 database/identity/audit/execution_store/sqlite_backend 的模块属性，具体模块 patch 照样生效；`install_default_storage_identity()` 可重复调用、不覆盖自定义绑定）和 `app/core/model_capabilities.py`；`sqlite_fts_query` 移到 `search_query.py`。sessions、rag、search_registry、模型 health/registry、个人知识 service、runtime_status 改为同名委托函数，SQL、签名和既有 patch 点不变；`app.main`（经 `runtime_dependencies`）和 `agent_runtime.service`（经 `default_coordinator_assembly`）的装配路径安装默认绑定，两个脚本和两个不经 `app.main` 的测试显式安装。债务 29→14，5 条延后到 MOD-008 ×2 / MOD-025 ×2 / MOD-021 ×1；282 文件/零边界错误，7 入口/92 消费记录/26 DB 候选不变，边界例外 37→32。新增 10 项专项；WSL 全部 168 个模块 1290 项与 HEAD 逐模块对照无新增失败，Windows 定向 43 模块 440 项只剩与 HEAD 一致的既有环境失败（反斜杠断言 19、WAL 断言 1、WinError 1314 ×2、WinError 32 ×5、数据库路径 1、便携切片解码 1）；ruff check 无新增，新文件 format 0 偏差。未运行性能门。下一批 015e Skill 链路与取消/异常验收，见 [报告](../reports/mod-015-runtime-convergence.md)。以下保留历史检查点。

最新检查点（2026-11-07，MOD-015c）：Loop 职责拆分已验证，纯重构。`run_agent_loop` 由约 700 行单函数拆为 6 个模块：`loop_state.py`（`LoopRunState` slots dataclass 持有 evidence_validation/answer_contract/knowledge_fallback/fallback_announced/applied_synthesis_reason/health/thinking_answer_effective，运行开始快照一次，`sync_to_context` 是唯一回写点，只在注入路径、原调用点执行）、`loop_request.py`、`loop_model_call.py`（重试/健康/回退，返回 `ModelTurn` 或回退结果，裸 `raise` 仍在 except 内）、`loop_answer.py`（文本/提交修复/salvage/降级/轮次上限）、`loop_tool_round.py`（Dispatcher 轮与旧工具轮）、`loop_round_validation.py`；`agent_loop.py` 812→196 行，公开名称与签名不变。等价证据：37 个场景的完整有序记录（事件与字段、进度、模型请求、sleep、消息、结果、context 同步快照）与改动前录制、并经 HEAD 导出副本重录字节一致的黄金样本逐项相等；变异自检和真实 `task.cancel()` 取消测试通过。新增 9 项专项；WSL 定向 34 模块 339 项通过，Windows 同 31 模块 320 项只剩与 HEAD 逐项一致的既有环境失败。279 文件/零边界错误，29 债务/7 入口/92 消费记录/26 DB 候选不变；ruff check 全过，新文件 format 0 偏差。未运行性能门。下一批 015d 存储/身份依赖注入 Port，见 [报告](../reports/mod-015-runtime-convergence.md)。以下保留历史检查点。

最新检查点（2026-11-07，MOD-015b）：依赖组/状态类型化与 EventSink 已验证。新增 `app/agent_runtime/ports.py` 结构化端口模块：`runtime_checkable` 的 `RuntimeSettings`/`RuntimeModelConnection` 配置视图（边界规则禁止 agent_runtime 导入 `app.core.settings`，含 TYPE_CHECKING）、22 个可调用 Protocol、`ToolRunBindings` 与 `Callable` 别名，领域类型仅 TYPE_CHECKING 导入、运行时只加载标准库；`dependencies.py` 58 个字段、`CoordinatorRunState`、`AgentLoopContext` 从 `Any` 全部类型化，字段名/顺序/默认值/live patch 快照不变；`telemetry.py` 新增 `RUNTIME_STAGE_AUDIT_EVENT`（`runtime_stage_completed`）、`runtime_event_audit_fields` 与 `AuditEventSink`，只供显式装配、默认路径审计流不变；`build_portable_unit.py` 的导入扫描跳过 TYPE_CHECKING 分支，便携清单不变。新增 17 项专项（含 58 字段真实快照绑定、Any 守卫、审计映射端到端、新进程导入面）；WSL 定向 433 项通过，Windows 同集只剩与 HEAD 逐项一致的既有环境失败（反斜杠断言 19、WinError 1314 ×5、WinError 32 ×11、bundle 子进程解码 ×3、便携切片 ×6）。273 文件/零边界错误，29 债务/7 入口/26 DB 候选不变，消费记录 91→92；ruff check 全过，format 计数与 HEAD 一致或更好。未运行性能门。下一批 015c Loop 职责拆分，见 [报告](../reports/mod-015-runtime-convergence.md)。以下保留历史检查点。

最新检查点（2026-11-07，MOD-015a）：MOD-015 拆为 a～e 五批，015a 兼容台账收敛已验证。删除 5 个 coordinator 转发模块、`conversation/context_resolver.py`、旧 `(client, endpoint, headers)` synthesis facade、`ClientModelSession` 与 `state.endpoint`，测试消费者迁到 canonical 模块；兼容性探针的 URL/凭据头改由 `ModelEndpoint` 提供；配置优先级修为“进程环境 > 项目 `.env` > 工作区 `.env`”，新增 4 项子进程测试。WSL 定向 251 项、扩展 183 项通过；Windows 同集只有既有的反斜杠路径、WinError 1314/32 失败，且与 HEAD 副本一致。272 文件/零边界错误，29 债务（5 条 exit_task 更正为 MOD-015）、兼容入口 13→7、消费记录 99→91。未运行性能门。下一批 015b，见 [报告](../reports/mod-015-runtime-convergence.md)。以下保留历史检查点。

最新检查点（2026-11-07，MOD-012）：ModelGatewayPort 与默认 HTTP Adapter 已验证。Loop、Ready 综合和上下文解析通过同一网关打开会话，客户端在成功、错误和取消时关闭；URL、凭据头和 `FAB_CHAT_TEMPLATE_COMPAT` 整形收进 gateway，重试/健康/回退仍由调用方负责。旧 service live patch 与 `(client, endpoint, headers)` facade 保持兼容。新增 20 项专项；WSL 定向 313 项与治理 17 项通过，Windows 同集只剩既有反斜杠路径、WinError 32/1314 失败。278 文件/零边界错误，29 债务/13 入口不变，消费者 97→99。未运行性能门。下一项 MOD-015，见 [验收报告](../reports/mod-012-model-gateway.md)。以下保留历史检查点。

最新检查点（2026-11-06，MOD-009）：批量来源替换和新增查询入口已验证。显式七类 Port 组合 21 项 canonical 工具，Fake 与 17 SQLite / 3 Provider / 1 Backend 的 Ready/Loop 通过；可选设备健康汇总复用原 Handler，不改默认清单或执行内核。主审两端各 9 项专项（ResourceWarning 按错误）、各 6 组 CLI 和 101 文件/44 路隔离通过，完整离线阶段门通过。275 文件（247 Python/28 静态），29 债务/25 DB 候选/13 入口/97 消费者不扩张；遗留报表、身份和演示 seed/启动退出交给 MOD-015，不冒充已移除。下一项 MOD-012，见 [验收报告](../reports/mod-009-tool-sources.md)。按用户要求通过后单任务提交并同步，Git 以实际记录为准。以下保留历史检查点。

最新检查点（2026-11-04，MOD-019）：进程内不可变发布、全部声明资源固定、显式激活/禁用/回退与真实 Run 内容固定已验证。主审 WSL 新增13项、Windows新旧Skill64项（跳过1）、两端各5组CLI与96文件隔离通过；按阶段收尾规则完成完整离线质量门，实际计数见 [验收报告](../reports/mod-019-skill-releases.md)。272文件（244 Python/28静态），29债务/25 DB候选/13入口/97消费者不变；默认HTTP与旧工具patch语义不变，下一项 MOD-009。按用户要求验收后单任务提交并同步，Git以实际记录为准。以下保留历史检查点。

最新检查点（2026-11-04，MOD-018）：已验证真实非空 skill_refs 的显式受控装配、光刻 Cpk 包及原命名 Playbook/Planner 的 Ready/Fake Loop。新证据策略显式为 1.3.0，默认 1.2.0 对照保持；权限/预算仍由原 Dispatcher 检查。主审 WSL 139 项（跳过 2）与另 27 项 Dispatcher/旧安装回归通过，Windows 51 项（跳过 1）通过，两端各 5 组 CLI 及 95 文件+4资产隔离通过；扩大旧 Windows 检查的 5 个既有失败由 Git 基线复现并单列。271 文件（243 Python/28 静态）、29 债务/25 DB 候选/13 入口/97 消费者；下一项 MOD-019。本轮按用户要求完成后提交并同步，以实际 Git 记录为准。见 [验收报告](../reports/mod-018-litho-cpk-skill.md)。以下保留历史检查点。

最新检查点（2026-11-03，MOD-017）：显式不可变 Catalog、确定性发现和渐进 Loader 已验证。仅声明读取 → 精确版本选择后说明 → 显式资源扩展，缺失/禁用/版本冲突和查询不匹配分开报告，不自动选择 latest，不新增模型调用。主审 WSL/原生 Windows 各 31 项专项分别跳过 2/1 个另一平台专用项；两端 10 文件隔离真链路及各 5 组演示/读取观测通过，既有 84 项基线（含 16 项 MOD-016，不重复计数）、必要仓库/边界/默认 v2/历史契约通过。267 文件（239 Python/28 静态），29 债务、25 DB 候选、13 入口/97 消费者不变。下一项 MOD-018 实际装配与光刻 Cpk 试点；本轮按用户要求验收后提交并同步，Git 状态以实际记录为准。见 [报告](../reports/mod-017-skill-catalog.md)。以下保留当时的历史检查点。

最新检查点（2026-11-02，MOD-016）：独立 Skill Manifest、工具/Workflow/Evidence 依赖校验与显式安全文本读取已验证。WSL / 原生 Windows 各运行 16 项专项，分别跳过 2 / 1 个另一平台专用项，其余通过；两端各 22 项额外非法输入检查、65 项既有回归、3 项旧隔离回归、仓库/边界/默认 v2/历史契约通过。264 文件（236 Python/28 静态），29 债务、25 DB 候选、13 入口/97 消费者保留。未接默认 Runtime 或实际 Workflow，不新增模型调用或数据库访问；下一项 MOD-017。见 [验收报告](../reports/mod-016-skill-manifest.md)。本轮未提交/推送，下述优先级调整为此前检查点。

最新优先级调整（2026-11-02，用户要求）：**Skill 加载机制及关联能力提升为最高开发优先级，下一项 MOD-016。** 当前基线为已同步的 6d6e6fa；本次仅改计划，工作包均未冒充完成。原 015 全部收口前置改为已验证的 008/011/014；018 纳入实际 skill_refs/装配接缝，019 完成版本发布/禁用/回退后，015 再统一状态/事件与生命周期收口。既有 182 项产品统计、企业接入暂缓和历史失败证据保留。

| 当前优先顺序 | 工作包 | 交付重点 | 前置 |
| --- | --- | --- | --- |
| 已验证 | MOD-016 | Manifest、依赖版本、安全资源加载 | 008、011、014 已验证 |
| 已验证 | MOD-017 | Catalog、确定性发现、渐进 Loader | 016 已验证 |
| 已验证 | MOD-018 | 光刻 Cpk Skill、复用 Playbook、实际装配与 Ready/Loop 演示 | 017、008、014 已验证 |
| 已验证 | MOD-019 | Run 版本固定、发布、禁用和回退 | 018 |
| 已验证 | MOD-009 | 批量工具来源替换与扩展能力验收 | 008；安排在 Skill 四项后 |
| 已验证 | MOD-012 | 模型客户端生命周期 | 014；安排在 009 后 |
| 已验证 | MOD-015 | Runtime 与先行 Skill 接缝、状态/事件、兼容收口（015a～015e 已验证；保留的兼容 facade 归 MOD-027） | 009、012、014；本轮安排在 019 后 |

执行与验收仍逐项串行；Skill 通过后回到余下 Runtime 工作，Skill 保持可选，启用/未启用路径均须兼容。后续公司接入、Checkpoint
与整体交付的完成门槛不变。总方案 v1.4 和 [模块化追踪](modularization.md) 已同步调整。
下方均为当时的历史检查点，其中“下一项 MOD-009”已由本次优先级取代。

用户插入维护（2026-11-02）：Windows / Linux 原生启动已完成并验证。统一 run.py、两端原生入口、独立 venv 与平台锁，保留受控快照和数据隔离；原生 Windows 与 WSL 各 48 项必要回归及真实 HTTP 启动/停止/重启通过。WSL 挂载盘快照发布错误已修复，历史失败保留。见 [验收报告](../reports/cross-platform-startup.md)。此项不计作 MOD-009，不更改 182 项产品统计；模块化主线下一项仍为 MOD-009。本次未提交/推送。

最新检查点（2026-11-02，第六批 F2b 收口）：MOD-008 已验证。依赖字段元数据、默认清单延迟物化与证据序列化三个有界优化后，205 项必要回归（7.820 秒）、仓库/边界/默认 v2/显式 legacy-v1 检查通过。r3/r4 失败保留；新源码的 r5 正式 1000×2 全部通过，12,000 个原始墙钟样本独立复算一致，阈值与夹具未改。Ready / Loop / 知识两批 p95 增幅分别为 2.27%/3.82%、13.20%/14.71%、12.67%/13.90%。258 文件、29 债务、25 DB 候选、13 入口/97 消费者不变。此前阶段完整质量门的分段证据保留，本次仅重跑必要范围；未暂存/提交/推送。下一项 MOD-009，见 [报告](../reports/mod-008-tools-rollout.md)。下方保留历史检查点，描述当时状态。

最新检查点（2026-11-01，第六批 F2b，验收中）：默认 v2 规划、业务 21 项原生绑定及通识仅知识检索的装配已落地，独立 submit_analysis 协议保留，默认模型 SQL 清单/提示/执行绑定退出。Ready、Loop、预取及受控降级共享 Dispatcher 与同一 Guard；旧独立阶段调用保留可选 hook 兼容。实扫 258 文件、29 债务、25 DB 候选、13 入口/97 消费者。两轮正式 1000×2 迁移性能均未通过：Ready 两批通过，Loop / 知识检索中位数仍超限，Loop 一批 p95 超限；原阈值及失败证据保留。F2b / MOD-008 继续性能收口，不进入 MOD-009。功能/质量复核已分段完成：1051 项全量非系统及修复后 105 项必要补测、70 系统、88% 覆盖率、Node 61 和浏览器 17 通过；系统 208.72 秒触发预警但未超过失败线，详见 [报告](../reports/mod-008-tools-rollout.md)。前批 68 源码/测试中仅知识 Adapter 增加已审查的可选个人来源类型，其余逐字节保留；工作簿保留，未暂存/提交/推送。下方为历史检查点，描述当时状态。

最新检查点（2026-10-31，第六批 F2a）：`MOD-008` 显式版本化 Planner/Playbook/Evidence 消费链已验证，整体仍进行中。六类 v2 Playbook 和真实规划器使用八项具名工具，保留证据 ID、依赖、预算、产品/设备过滤和批次全历史；新具名结果严格匹配实际参数。72 模块 476 项必要回归（75.754 秒）、12 路独立功能核验、旧安装/七单元/冻结行为/契约和边界门通过。首轮 Ruff 对照发现一条新增 SIM102，等价修正后主审复跑 52 项（1.844 秒）、12 路功能和冻结行为通过，不重复累计。当前 254 文件（226 Python/28 静态）、28 债务、24 DB 候选、13 入口/85 消费者；前批 58 源码/测试逐字节不变。默认旧 Planner/catalog/bindings/服务装配未切换，SQL 仍可见且可执行；下一步 F2b 统一默认原生装配、清单与 SQL 执行绑定退出。没有真实公司/模型调用，未重跑正式性能/全浏览器/覆盖率；未暂存、提交或推送，工作簿及 UTF-8/LF 保留。见 [MOD-008 报告](../reports/mod-008-tools-rollout.md)，下方保留历史检查点。

最新检查点（2026-10-31，第六批 F1）：`MOD-008` 八条 Planner 固定 SQL 的具名替代能力已验证，整体仍进行中。新 Native Query/Port/八绑定、精确 Fake、单库只读 SQLite 与 Ready/Loop 保留产品加权良率、设备联合过滤、批次全历史和原列集/排序/上限；technology 为整数、yield_rate 为比率、yield_pct 为百分数。65 模块 431 项必要回归（64.487 秒）、32 主路径、60 文件仓库外 16 条 Fake 路径、旧 37 文件安装/七单元/冻结行为/兼容门、11 文件 Ruff/格式通过。当前 252 文件（224 Python/28 静态）、28 债务、24 DB 候选、13 入口/85 消费者；新增 DB 候选仅为经审查的只读具名 Adapter。前批 47 源码/测试逐字节不变，实际 Planner/Playbook/Evidence 与默认绑定未改；下一步 F2 落地消费映射、SQL 能力版本与默认清单/执行绑定退出。没有公司/外部模型调用，未重复正式性能/完整浏览器/覆盖率；未暂存/提交/推送，工作簿和 UTF-8/LF 保留，见 [MOD-008 报告](../reports/mod-008-tools-rollout.md)。下方保留历史检查点。

最新检查点（2026-10-30，第五批）：`MOD-008` 联合知识检索已验证，整体仍进行中。消费方 KnowledgeSearchPort 与个人搜索 Port、显式工厂/个人 Backend Adapter 和精确 Fake 保留三类来源、owner 映射、排序/多样性及引用；设备等焦点不冒充 ACL。旧 RAG 仅抽取相同纯规则，10 个保留函数 AST 与排序模块不变。最终 61 模块 413 项必要回归（118.380 秒，含新增 29 项）、70 组完整旧新对照、临时合成库 RAG 15/15、66 真实文件仓库外四条路径、旧 37 文件安装/七单元/冻结行为/兼容门通过。首轮 412 项后仓库门拒绝公共工具契约导入，失败记录保留；只补五条精确许可，九类禁止导入仍拒绝。新 13 文件 Ruff/格式通过，旧 rag 保留原两项诊断、无新增。当前 245 文件（217 Python/28 静态）、28 债务、23 DB 候选、13 入口/85 消费者；前批 33 源码/测试逐字节不变。默认 14 个业务工具仍为 legacy 绑定，SQL 全局尚未退出，未接公司来源；未暂存/提交/推送，工作簿和 UTF-8/LF 保留。下一批继续具名查询、SQL 能力版本和默认装配迁移，见 [MOD-008 报告](../reports/mod-008-tools-rollout.md)。下方保留历史检查点。

最新检查点（2026-10-29，第四批）：`MOD-008` 企业目录、汇总和样本工具已验证，整体仍进行中。新增消费方 EnterpriseDataPort、固定时间窗口、三项原生绑定及精确 Fake/显式 Provider Protocol Adapter；默认省略参数、90/730 天窗口、模拟统计/血缘和样本分页口径保留。主审 52 模块 354 项必要回归（182.717 秒，含本批 19 项）、82 真实文件仓库外执行、旧 37 文件安装、原七单元重建、冻结行为/旧契约/仓库/新旧边界和 11 文件 Ruff/格式通过；另有 47 个异常来源检查。当前 236 文件（208 Python/28 静态）、28 债务、23 DB 候选、13 入口/85 消费者，逐路径结构已核对，前两批 22 源码/测试逐字节不变。未接真实公司来源，未改默认旧热路径，未退出 SQL，未重复正式性能/完整浏览器/覆盖率；没有暂存/提交/推送，工作簿保留。下一批继续知识工具，再做具名查询及能力版本/默认路径迁移，见 [MOD-008 报告](../reports/mod-008-tools-rollout.md)。下方保留历史检查点。

最新检查点（2026-10-28，第三批）：`MOD-008` 生产率、缺陷 Pareto、最近异常已验证，整体仍进行中。OperationalReportsPort 与三项原生绑定采用 Fake 或每次仅访问设备/质量/制造一个相关库的只读 SQLite；保留设备优先/异常联合筛选、Pareto 截断前分母和原舍入/NULL 语义。最终 46 模块 328 项必要回归（47.389 秒）、74 真实文件仓库外六条 Fake 路径、原 37 文件安装、七单元重建、冻结行为/旧契约/仓库/新旧边界通过；11 文件 Ruff/格式通过。当前 229 文件、28 债务、23 DB 候选、13 入口/85 消费者；逐文件结构已核对，第二批 11 源码/测试保留不变。九个固定制造报表均有显式原生路径，旧默认绑定和 SQL 能力仍在；下一批继续企业数据/知识工具，再做具名查询/能力版本与默认路径迁移，见 [MOD-008 报告](../reports/mod-008-tools-rollout.md)。未重复正式性能、浏览器完整门或覆盖率，本批未暂存/提交/推送；下方保留历史检查点。

最新检查点（2026-10-28）：`MOD-008` 第二批生产总览、周良率趋势、制程运行通过率已验证，整体仍进行中。三项工具形成原生输入/Definition/Binding、消费方 Query/Snapshot/Port、Fake 和显式制造单库只读 SQLite，实际复用 Ready/Loop。主审修复并验证空总览 held_lots=None、AVG(pass_flag) 的 NULL 语义、加权良率/周分组/结束日边界与来源范围；拒绝路径零 Port、来源故障无回退。最终 42 模块 305 项必要回归（45.695 秒）、67 真实文件仓库外六条 Fake 路径、原 37 文件安装、七单元重建、冻结行为/旧契约/仓库和模块守卫通过；11 文件 Ruff/格式通过。当前 222 文件、28 债务、22 DB 候选、13 入口/85 消费者；[精细结构](../current-project-structure.md) 已逐路径核对。基线为已同步的 db4cee6，本批未暂存/提交/推送；未改默认 catalog/执行热路径或退出 SQL，未重复正式性能、浏览器完整门或覆盖率。下一批继续其余报告/企业数据/知识工具及具名查询和 SQL 能力版本迁移，见 [MOD-008 报告](../reports/mod-008-tools-rollout.md)。下方保留历史检查点。

最新检查点（2026-10-27）：`MOD-008` 首批已验证，整体仍进行中。get_process_capability / get_sensor_summary 已形成原生输入/Definition/Binding、消费方 Query/Snapshot/Port、Fake 与相关单库只读 SQLite；两工具实际复用 Ready/Loop，未激活全局旧入口或退役 SQL。修复共享结果桥接丢弃真实联合过程/设备过滤的问题，保留设备健康原设备优先 Scope。主审 38 模块 281 项必要回归、60 文件仓库外 Fake、原 37 文件安装/七单元重建、冻结行为/旧契约/新旧守卫通过；13 小文件 Ruff/格式通过。未重复正式性能、完整浏览器或覆盖率。当前 215 文件、28 债务、21 DB 调用候选文件、13 入口/85 消费者；[215 文件精细结构](../current-project-structure.md) 已逐路径核对。下一批继续其余工具及具名查询/SQL 能力版本迁移，见 [MOD-008 首批报告](../reports/mod-008-tools-rollout.md)。本批无暂存/提交/推送，下方保留历史检查点。

最新检查点（2026-10-26）：`MOD-014` 已验收。现有 Loop 显式注入同一 Dispatcher，单轮预算/响应分类、公共证据/综合/事件归约与 Ready 对照成立。主审最终 217 项必要定向、3 项默认旧回退系统回归、53 文件仓库外源码链路、原 37 文件安装/七单元/冻结行为/旧契约/守卫通过；6 小文件 Ruff/格式通过，旧 agent_loop.py 5→5 无新增诊断。r1 正式性能通过后，主审发现模型故障可能隐式调用旧离线业务回退，修复并预声明 r2；最终 1000×2 与原始墙钟独立审计通过，两报告保留，阈值未改。当前 208 文件、28 债务、13 入口/85 消费者；默认全局 SQL 与旧路径尚未切换，完整客户端生命周期留 MOD-012。下一项按主线为 `MOD-008` 分批工具推广和模型 SQL 能力退出，见 [MOD-014 报告](../reports/mod-014-loop-dispatcher.md)；精细文件责任地图见 [项目结构](../current-project-structure.md)。未提交/推送，下方为历史检查点。

最新检查点（2026-10-26）：`MOD-013` 已验收。现有 Ready 与 service facade 可显式注入同一 Dispatcher，保留单一拓扑与预算；知识过滤/截断在最终记账前完成，失败依赖阻断、取消/超时状态与迟到结果均有实测。主审最终 204 项必要定向、49 文件仓库外源码链路、原 37 文件安装回归、七单元重建、冻结行为/旧契约/守卫通过；11 个小文件 Ruff/格式通过，旧文件无新增问题。唯一一次 1000×2 正式配对及 12,000 个墙钟样本独立审计通过，阈值未改。当前 204 文件、28 精确债务、13 入口/85 消费者；仅显式注入路径完成，旧默认 Ready/Loop 和旧 SQL 尚未切换，Runtime/Memory/Skill 尚未整体解耦。下一项 `MOD-014` 为 Loop 接入同一 Dispatcher 与一工具双路径对照，见 [MOD-013 验收报告](../reports/mod-013-ready-dispatcher.md)。未提交或推送；下方保留历史检查点。

最新检查点（2026-10-25）：`MOD-011` 已验收。最小 AgentDefinition/AgentRun 与显式装配已形成实际 Fake/只读 SQLite 演示，声明能力与服务端能力取交集、版本/依赖在执行前校验，各 Run 使用独立本地 Registry/Dispatcher 和预算 factory。旧 coordinator 依赖快照组装已迁 bootstrap，保留真实 service 的 live patch/构造器/共享容器兼容。主审 185 项必要定向、44 文件仓库外源码链路、原 37 文件安装回归、冻结行为/旧契约/守卫通过；唯一一次 1000×2 正式配对性能与原始墙钟独立审计通过，阈值未改。199 文件、28 精确兼容债务、13 入口/83 消费者；尚未退出的制造/会话/身份/目录/配置和兼容 seam 按台账留至 MOD-008/015，不假称整个 Runtime/Memory 已完成解耦。新增 8 文件 Ruff/格式通过，旧 compatibility.py 保留原 9 项 Ruff 历史问题、无新增。未切换旧 Ready/Loop、未退出旧 SQL、未启动 Skill 或真实来源。下一项 `MOD-013` 为 Ready 接入同一 Dispatcher，见 [MOD-011 验收报告](../reports/mod-011-agent-assembly.md)。下方保留历史检查点。

最新检查点（2026-10-24）：`MOD-010` 已验收。新增最小 ModelResponsePort / ToolDispatcherPort / EventSink、可信 RuntimeContext、模型响应/Usage 和阶段结果，以及三个无循环/重试的单步消费者；服务端执行 ID 与模型关联 ID 分离，事件保留工具 execution_state，sink 失败不重执行工具。主审 171 项必要定向、40 文件仓库外源码切片真实链路及原 MOD-007 新 venv 安装回归通过；Ruff、冻结行为/旧契约与守卫通过（194 文件、27 条债务）。未改旧 CoordinatorDependencies/AgentLoopContext/Ready/Loop，未宣称完成完整 ModelGateway、整个 Runtime 类型化或旧 SQL 退出；未重跑全量/浏览器/性能。下一项 `MOD-011` 为显式装配与最小 AgentDefinition。见 [MOD-010 验收报告](../reports/mod-010-runtime-ports.md)。下方保留历史检查点。

最新检查点（2026-10-24）：`MOD-007` 已验收。最小公共 Dispatcher 固定输入/有效 Scope、服务端能力清单及演示授权，复用同实例 LoopGuard，形成结果/来源/事件 payload 桥接；204 项必要定向测试、37 文件仓库外新 venv 真实安装及 Fake/双临时 SQLite、取消/超时/迟到隔离/安装包拒绝通过。Ruff、冻结行为 v2、旧契约和守卫通过（191 文件、27 条精确债务），原七源码单元重建验证通过。本项未切换旧 Ready/Loop、未移除旧 SQL 工具，未重跑配对性能、全量浏览器或覆盖率。下一项依总方案为 `MOD-010` 最小 Runtime Ports/类型化上下文，再经 `011→013→014` 完成一工具双路径，不直接跳到批量 `008`。见 [MOD-007 验收报告](../reports/mod-007-tool-dispatcher.md)。下方 MOD-006/005/004 段落保留为历史检查点。

最新检查点（2026-10-24）：`MOD-006` 已验收。统一 Registry 持有原生 Schema/handler 兼容容器，旧工具经 LegacyBindingAdapter 读取实时映射，具体装配迁入 bootstrap；全局工具集合和 Schema 不变，未激活 typed 设备路径。主审 163 项定向测试、27 文件仓库外实运行、冻结行为/旧契约/守卫通过（185 文件、27 条精确依赖债务）；唯一一次预声明 1000×2 正式配对性能及原始墙钟独立重算通过，未修改容差。未重跑浏览器全量、完整质量门或覆盖率。下一项 `MOD-007` 为公共 Dispatcher、Fake/演示 Policy、能力限制与结果桥接；旧 SQL 工具仍待 MOD-008 退出。见 [MOD-006 Registry 报告](../reports/mod-006-tool-registry.md)。下方 MOD-005/004 段落是此前同日检查点，不再代表当前下一项。

最新实施进度（2026-10-24）：`MOD-005` 已验收。设备健康查询的输入/Definition/Binding/消费方 Data Port 与 Fake、双库只读 SQLite 已形成未注册切片；26 文件仓库外真实运行、旧新行为矩阵、错误脱敏及连接生命周期通过。主审最终 130 项定向测试、冻结行为 v2、旧重构契约和仓库检查通过；真实边界清单为 181 文件/0 错误。本轮未重跑完整门、覆盖率、浏览器或性能，不改变 P0 历史证据。旧工具和 Ready/Loop 尚未切换，旧 SQL 工具仍保留，下一项 `MOD-006` 是单一 Registry、兼容视图和 LegacyBindingAdapter。详见 [MOD-005 试点报告](../reports/mod-005-equipment-health.md) 与 [模块化追踪](modularization.md)。下段保留 MOD-004 验收时的历史检查点，其中“下一项 MOD-005”已由本段更新。

当前实施进度（2026-10-24）：P0 已收口。`MOD-002` 的 observe/reference 审批、完整门、CLI 导入修正后 76 项定向回归及两次预声明 1000×2 正式比较 A/B 均通过，主审独立重算墙钟样本通过，旧静态失败保留。`MOD-003` 已完成 171 文件归属、30 条依赖债务、兼容与数据库台账并接入新旧双守卫；55 项定向和 r2 完整门通过（786 Python、coverage 89%、61 Node、17/17 浏览器，系统预算通过）。r1 浏览器会话异步竞态失败与测试同步修正记录均保留。`MOD-004` 现已完成 1.0.0 执行上下文、结果/错误/来源纯契约，以及旧工具导出的必要惰性加载；主审 109 定向项、真实包隔离导入/仓库外 Fake、冻结行为 v2 与旧重构契约/守卫通过，当前归属清单 172 文件。本项未接新执行路径或改变公开 Schema；性能明确跳过，未重跑浏览器完整门，不改写 P0 历史证据。下一项 `MOD-005` 是设备查询工具及 Data Port 的 Fake/SQLite 试点；不提前接入公司数据库。详见 [MOD-002 基线报告](../reports/mod-002-behavior-baseline.md)、[MOD-003 边界报告](../reports/mod-003-module-boundaries.md) 与 [MOD-004 契约报告](../reports/mod-004-tool-contracts.md)。下方早期未完成描述保留为对应日期的历史状态。

2026-10-24 文档补充：总方案现为 v1.3，按用户确认保留只读数据库和报表/API 两种公司侧接入可能。先固定业务契约并用 Fake/SQLite 验收，再按能力显式绑定实际来源；不要求两套同时实现、不自动回退来源。业务读取与应用自有存储分开，现有 `database.py` 按消费者逐步收缩全库挂载及初始化职责，保留未迁路径与数据；不立即换库或重写全部持久化。公司业务库不由本项目建表/迁移/seed，接入资料和权限具备后另行验收。补充要求归入既有 `MOD-003/005～009/011/015/025～028`，不改变依赖、完成状态、历史失败或企业授权范围，见 [数据库渐进处理](../architecture-modularization-master-plan.md#510-应用存储与现有-databasepy-的渐进处理) 和 [接入确认](../architecture-modularization-master-plan.md#94-公司侧接入确认与绑定记录)。

2026-10-22 文档补充：总方案 v1.2 已明确量化小模型不生成/提交可执行 SQL，模型只调用具名工具及结构化参数；受控查询留在 Repository/Adapter。现有 `query_manufacturing_data(sql)` 尚未移除，按 `MOD-003` 登记退出、`MOD-004～007` 限制契约/执行能力、`MOD-008` 替代并退出、`MOD-009/015` 验收；能力/Schema 变化单独记录，不自动刷新旧基线。Data Access 职责和 D0～D3 接入成熟度已细化，仍保留单工具双路径优先顺序，不启动企业连接平台。本次只修订文档，不将这些要求标为已实现，详见 [总方案](../architecture-modularization-master-plan.md#59-数据访问职责与无-sql-模型边界) 与 [模块化追踪](modularization.md)。

2026-10-22 用户已批准模块化与内网迁移重构。既有产品队列仍为 0；模块化 P0 另设工作包队列，`MOD-001` 已验证。`MOD-002` 的 r1–r5 历史静态失败、v4 validation 和完整门证据均保留；用户现已批准同轮 reference/current 配对 wall-clock 方法，固定原相对容差，wall median/p95 为硬门，CPU/cleanup 仅观察。candidate reference、protocol 与 runner 尚未完成 observe、reference behavior 审批或 formal，故 `MOD-003` 仍未开始。验证顺序为 observe 隔离/完整 behavior v2、审批 metadata、完整离线门与两次预先声明 formal；仅两次均通过才完成 MOD-002 并自动继续 MOD-003，任次失败保留。状态、边界和证据见 [模块化工作包追踪](modularization.md)，不与分类 TODO 的历史完成数混计。

2026-09-23 用户批准优先实施 Memory 结构抽离；2026-09-26 `MEM-001` → `MEM-004` 已逐阶段验收，定义与结果见 [Memory System TODO](memory-system.md)。当前回到下方答案综合队列；两者涉及 ready 输入的变更不并行。B1/B2 未纳入本次结构抽离，长期记忆 B3 保持 OPTIONAL。用户随后要求提交并同步；本次以一个汇总提交交付，不包含其已有未提交测试，原计划的逐阶段独立提交未落实。

2026-09-17 新增的产品任务定义与完成状态见 [Agent 执行架构 TODO](archive/agent-architecture.md#答案综合灵活性改善2026-09-17-新增已完成)。`AGENT-040` 已于 2026-10-15 完成，`AGENT-041`、`AGENT-042` 已于 2026-10-16 完成，`AGENT-043`、`AGENT-044` 已于 2026-10-17 完成；本队列收口。`AGENT-039` 与 `REF-025` 保持 `OPTIONAL`，未自动激活。

| 顺序 | 任务 | 依赖 | 本次交付 | 完成门槛 |
|---:|---|---|---|---|
| 1 | `AGENT-044` | `AGENT-040` 至 `AGENT-043`（已完成） | 已完成：局部修复与跨路径回归，P1 | 有界修复不重复工具/正文，保留有效格式，完整离线门通过 |

### 前序已完成与暂缓记录（保留）

| 顺序 | 任务 | 依赖 | 本次交付 | 完成门槛 |
|---:|---|---|---|---|
| 1 | `AGENT-037` | 无 | 范围安全指标与综合 | 已完成：通用范围契约、调用级来源、fail-closed 结构化声明验证及全制程数据驱动覆盖 |
| 2 | `AGENT-038` | `AGENT-037` | 确定性 ready 计划执行 | 已完成：服务端依赖执行、失败传播、仅 `submit_analysis` 综合、验证前禁止正文、无模型降级及三类固定合成性能门 |
| 3 | `OBS-017` | `AGENT-036`、`AGENT-038` | Trace 语义 | 已完成：schema 分离、三类引用计数、安全仲裁候选、六阶段耗时聚合和旧日志读取兼容 |
| 4 | `QA-004` | `AGENT-036`、`AGENT-037`、`AGENT-038`、`OBS-017` | 脱敏离线回放矩阵 | 已完成：三条真实链路、三种 Router 失败扩写和 SOP/范围反例跨层断言通过；普通质量门真实 LLM/网络调用为 0 |
| 5 | `DEPLOY-012` | `QA-004` 及全部当前队列测试 | CI 质量门 | 已完成：固定 Hosted Runner 环境执行完整门，分支保护严格要求 GitHub Actions 的 `Full quality gate` |
| 6 | `REF-001` | `DEPLOY-012` | Agent 叶子运行时模块 | 已完成：工具目录与模型流协议提取，保留旧导出和 patch 点，主编排不变 |
| 7 | `REF-002` | `REF-001` | 重构契约基线 | 已完成：版本化快照固定工具、Agent/Trace/SSE、OpenAPI/HTTP、DOM 与脚本顺序，离线差异检查通过 |
| 8 | `REF-003` | `REF-002` | Agent contracts 与 telemetry | 已完成：建立运行输入/生命周期 contracts、进度/审计 telemetry 和纯转发协调入口；旧入口、高频 patch 点与主业务控制流保持兼容 |
| 9 | `REF-004` | `REF-003` | Agent 准备阶段 | 已完成：Context、Router、Arbiter、Playbook、Planner 等价迁移；`app.agent` facade 实时注入兼容 patch 点 |
| 10 | `REF-005` | `REF-004` | 工具运行时目录化 | 已完成：Schema、Registry、Executor 分离；`agent_tools`/`agent` 继续导出唯一 catalog/registry 对象，实时 patch registry 与工具调用语义不变 |
| 11 | `REF-006` | `REF-005` | Agent 执行阶段 | 已完成：Ready Plan、兼容 Loop 与失败传播等价迁移；服务端依赖执行与模型业务工具选择数 0 保持不变 |
| 12 | `REF-007` | `REF-006` | 通用知识检索阶段 | 已完成：查询、过滤、降级披露与引用等价迁移；94 项定向回归、冻结契约及宿主 full 通过 |
| 13 | `REF-008` | `REF-007` | Agent 综合与结果阶段 | 已完成：Ready assistant 解析、离线降级、Contract 和结果字段等价迁移；10 项合成边界测试、141 项定向回归、契约、仓库检查及宿主 full 通过，`app.agent` 1613→1256 行 |
| 14 | `QA-005` | `QA-004`、`DEPLOY-012`、`UX-012` 至 `UX-015` | E2E 基础契约 | 已完成：自动错误 fixture、10 条稳定关键 ID 清单、快照/端口/真实 loopback 健康诊断、三次独立 Chromium 及宿主 full 通过 |
| 15 | `QA-006` | `QA-005` | 真实模型与故障协议双通道 | 已完成：`deepseekv4-pro` 在 2026-08-29T05:52:38.410+00:00 兼容性通过（12556.2ms；connectivity_streaming、tool_calls、context_load、structured_context、thinking_answer、thinking_tool_roundtrip、limits；context_chars=32768）；授权五轮 Chromium `LIVE_PROVIDER` 矩阵 5/5，通过报告 calls=9、input/output=66859/22083、313235.3ms、fallback/degraded=0，普通 full 仍为零外部调用 |
| 16 | `QA-007` | `QA-006`、`UX-025` 至 `UX-028` | 个人知识 E2E 闭环 | 已完成：确定性个人知识闭环与 six-run Live 召回/来源/复制/删除验证通过，普通 full 零外部调用 |
| 17 | `QA-008` | `QA-006`、`AUTH-004`、`MODEL-001` 至 `MODEL-007` | 管理端真实治理闭环 | 已完成：令牌表单、严格四能力模型发布/失效/探针/状态、用户端 Thinking 同步、协议失败分类及三场景授权 Live 通过；凭据不进入前端或 artifact |
| 18 | `QA-009` | `QA-005`、`QA-006`、`QA-007` | 桌面关键旅程收口 | 已完成：Session 生命周期、来源分组/复制/Trace、固定日期 dashboard、ETCH capability、knowledge/case 真实 API、17 条确定性 E2E 通过；必要 Live Provider 五轮矩阵通过，完整 7-run 门未重跑 |
| 19 | `QA-010` | `QA-005` 至 `QA-009`、`DEPLOY-012` | 双通道 CI 治理 | 本地完整 Live 已通过；2026-09-05 用户暂缓远程 `live-e2e` Environment、Secret 与首次完整实测验收，私有仓库 required reviewer API 返回 422 |
| 20 | `REF-009` | `REF-008`、`QA-010` | Agent coordinator 收口 | 已完成：每调用 namespace snapshot 的 `AgentCompatibilityFacade` 保持 async/sync wrapper 和实时 patch；`CoordinatorRunState` 协调 prepare、availability、model、ready、loop 五阶段，`run_agent` 生命周期不变，`agent.py` 1256→164、coordinator→108，174 项定向回归、契约、仓库检查和宿主 full 通过 |
| 21 | `REF-010` | `REF-009` | API 基础边界 | 已完成：application、errors、schemas、dependencies 等价迁移；main app/lifespan/handler/schema/auth 兼容导出与实时 patch 保持，URL/OpenAPI/认证/状态码/响应不变 |
| 22 | `REF-011` | `REF-010` | 领域 Router | 已完成：8 个领域 `APIRouter`、main runtime namespace 实时 patch、同名兼容导出与 Personal Job SSE service 收口；URL、认证、状态码、响应和 OpenAPI 等价，`main.py` 1125→697（减少 428 行） |
| 23 | `REF-012` | `REF-011` | Chat 与流式服务 | 已完成：Chat Router、非流式与 NDJSON 流式服务、兼容导出与实时 patch 收口；契约、事件顺序、Session 和遥测不变 |
| 24 | `REF-013` | `REF-012` | `main.py` 收口 | 已完成：runtime dependencies 显式发布、9 个 Router bundle 统一注册/兼容导出，main 达到 227 行且 live patch 不变 |
| 25 | `REF-014` | `REF-013` | 前端核心层 | 已完成：五个 Core UMD 模块、defer 依赖顺序、app.js facade 及契约等价迁移 |
| 26 | `REF-015` | `REF-014` | 前端业务控制器 | 已完成：知识/案例、上传/Job SSE、Dashboard/Capability/图表和 Thinking/模型配置迁入三个 controller；同名 facade、共享状态、脚本顺序和产品交互不变 |
| 27 | `REF-016` | `REF-015` | Session 与聊天流 | 已完成：Presenter、Session 与 Chat/Live controller 显式分层；增量 Markdown、复制、重试消息 ID、归档、取消与遥测不变，`app.js` 1153→426 行 |
| 28 | `REF-017` | `REF-016` | 布局与启动收口 | 已完成：layout/bootstrap 模块化，`app.js` 426→89 行，视觉基线不变 |
| 29 | `REF-018` | `REF-017` | 个人知识基础边界 | 已完成：contracts、metadata、storage 与 ACL 等价迁移；标准环境 full 510 Python、442/442 非系统及全部预算通过 |
| 30 | `REF-019` | `REF-018` | 个人知识处理流程 | 已完成；Job、抽取器、OCR、入库、重试和删除语义保持不变，标准环境 full 515 Python、447/447 非系统及全部预算通过 |
| 31 | `REF-020` | `REF-019` | 个人知识查询收口 | 已完成：文档/Cursor 与 FTS/Chunk 分入独立 runtime 模块；SQLite、ACL、排序、引用和 facade 实时 patch 不变，标准环境 full 517 Python、449/449 非系统及全部预算通过 |
| 32 | `REF-021` | `REF-020` | 第二梯队只读审计 | 已完成：按职责、依赖、变化压力、覆盖率和维护风险审计六个模块；仅生成四项 `OPTIONAL` 候选，未修改产品代码 |
| 33 | `REF-022` | `REF-021` | Coordinator 阶段边界 | 已完成：五阶段迁入 `stages/`、兼容导出、依赖分组和单一状态实时视图；不改变运行路径 |
| 34 | `REF-023` | `REF-022` | Intent Router 边界 | 已完成：contracts/rules/scope/time/routing 与薄 facade，规则和类型兼容不变 |
| 35 | `REF-024` | `REF-023` | Planner 边界 | 已完成：planning runtime 与薄 facade，契约/SQL/步骤语义保持 |
| 36 | `REF-027` | `REF-024` | 归属与兼容基线 | 已完成：36 个根模块与 package anchor 清单、26 条精确例外、兼容/patch 审计和 AST 边界守卫已通过完整质量门 |
| 37 | `REF-028` | `REF-027` | 制造领域归档 | 已完成：实现迁入 manufacturing，旧入口兼容、精确边界例外与冻结行为均通过验证 |
| 38 | `REF-029` | `REF-028` | 存储基础归档 | 已完成：SQLite、部门 Schema、执行记录迁入 persistence；不拆内部实现、不改数据库 |
| 39 | `REF-030` | `REF-029` | 遥测领域归档 | 已完成：审计、HTTP 遥测和运行状态迁入 telemetry；脱敏、关联与生命周期不变 |
| 40 | `REF-031` | `REF-030` | 模型访问归档 | 已完成：唯一实现迁入 model_gateway，旧入口兼容；能力/Thinking/重试/熔断不变 |
| 41 | `REF-032` | `REF-031` | 会话与运行时归档 | 已完成：会话唯一实现迁入 conversation，能力与 Loop Guard 迁入 agent_runtime；旧入口兼容、来源/决策/会话与停止条件均通过验证 |
| 42 | `REF-033` | `REF-032` | 知识与证据归档 | 已完成：RAG/OCR/知识决策、证据语义/验证/答案综合迁入领域目录；ACL/引用/安全校验不变 |
| 43 | `REF-034` | `REF-033` | 兼容入口退役与收口 | 已完成：内部消费者使用 canonical 路径，29 个过渡 facade 受 AST 清单守卫；缺少外部迁移证据的公开入口继续保留 |
| 44 | `REF-035` | `REF-034` | 根目录精简与旧入口退役 | 已完成：根目录仅保留包与 HTTP 入口；35 个旧路径退役，完整离线质量门通过 |

用户在 REF-034 后新增实际精简目录要求，REF-035 不属于此前八项任务的已完成结论。2026-09-23 登记 4 项 Memory 抽离任务，2026-09-26 全部通过完整离线验收后，总计 225 项，176 项完成、49 项未完成（当前队列 5、用户暂缓 2、企业级暂缓 42）；4 项 `OPTIONAL` 不计入主任务统计，暂缓状态不变。

已完成的 `UX-015` 只覆盖桌面端；移动视口、触摸交互和移动端回归统一由用户暂缓的 `UX-029` 后续处理。

## 当前阶段检查点

### 检查点 E：结构可维护性

`REF-001` 至 `REF-024`、`REF-027` 至 `REF-034` 及 `QA-005` 至 `QA-009` 已完成；Coordinator、Router、Planner、制造、存储、遥测、模型访问、会话运行时、知识与证据领域的职责边界已经冻结。2026-09-08 用户批准的 `REF-027` 至 `REF-034` 领域目录重构已在 2026-09-13 完成；具体映射、兼容与验收见 [代码可维护性 TODO](archive/code-maintainability.md#领域目录重构已完成)。`REF-025`、`REF-026` 仍为 `OPTIONAL`，未激活内部拆分。`QA-010` 本地完整 7-run 已于 2026-09-04 通过，但远程 Environment/Secret/full 验收于 2026-09-05 由用户暂缓，故仍保持未完成且不阻塞本轮离线结构重构。普通 push/PR 不访问真实模型；必要 Live `provider-matrix` 不替代完整 7-run Live 门，未来发布或打标签前仍必须完成受保护的完整 Live 门；任一任务若产生未批准的产品行为差异，不得作为测试或重构完成。

### 检查点 D：上一阶段收口

`DEPLOY-012` 已完成：全部当前任务已标记 `[x]`，GitHub Actions 完整门与分支 required check 已收口。`AGENT-037`、`AGENT-038`、`OBS-017`、`QA-004` 与 `DEPLOY-012` 均是本期已完成的非企业级产品任务。

已完成的检查点 A、B 和 C 及其实测记录保留在 [TODO 执行历史](execution-history.md)。



2026-11-11 执行更新：c1～c7、030d 和 030e 均已交付，阶段报告逐项保留通过、基线失败及环境未验证范围；本轮只创建本地提交，不推送，不修改他人 MOD-031 文档。
