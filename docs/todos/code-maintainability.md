# 代码可维护性 TODO

状态基线：`experiment/parallel-platform`，2026-09-07。

本清单只处理结构、模块边界和可读性，不改变业务逻辑、API 契约、SSE/NDJSON 事件、工具调用顺序、Trace、数据库结构或前端交互。每项重构都保留必要的兼容门面，并以现有回归测试作为行为基线。

## 设计原则

1. 采用“一个职责或运行阶段一个模块”，不采用机械的“一个函数一个文件”。强相关辅助函数保留在同一模块；只有能够独立复用、独立测试或拥有复杂状态的函数才单独成文件。
2. Python 内部实现使用 `app/agent_runtime/`，不创建与 `app/agent.py` 冲突的 `app/agent/` 包。`app/agent.py`、`app/main.py` 和 `app/personal_knowledge.py` 始终保留为兼容门面。
3. 前端继续使用普通 `defer` 脚本和显式加载顺序，不引入打包器或 ES Module；`app/static/app.js` 最终只保留兼容启动入口。
4. 工具目录、注册、执行和领域实现分层：运行时只负责 Schema、Handler 映射、权限/预算与结果归一化；`reports.py`、`enterprise_data.py`、`rag.py` 和 `answer_synthesizer.py` 继续拥有真实业务实现。
5. 一次只完成一个 `REF` 编号并独立提交。行为变化、数据库迁移或 API 调整必须另建任务，不能混入结构重构。

## 目标目录

```text
app/
├── agent.py                         # Agent 兼容门面
├── agent_tools.py                   # 工具兼容门面
├── model_streaming.py               # 模型流兼容门面
├── agent_runtime/
│   ├── contracts.py                 # 阶段输入、输出和运行状态
│   ├── coordinator.py               # 全链路协调器
│   ├── telemetry.py                 # 进度、审计和 Trace 汇总
│   ├── preparation/{context,routing,planning}.py
│   ├── tools/{catalog,registry,executor}.py
│   ├── execution/{ready_plan,agent_loop,failure}.py
│   ├── retrieval/general_knowledge.py
│   ├── synthesis/{ready,fallback,result}.py
│   └── model/{stream,retry,audit}.py
├── api/
│   ├── application.py
│   ├── errors.py
│   ├── schemas.py
│   ├── dependencies.py
│   ├── routers/{system,enterprise,reports,models,admin,knowledge,sessions,chat,monitor}.py
│   └── services/{chat,chat_stream,personal_job_events}.py
├── personal_knowledge_runtime/
│   ├── {contracts,metadata,storage,jobs,ingestion,documents,search}.py
│   └── extractors/{text,office,pdf,image}.py
└── static/app/
    ├── core/
    ├── knowledge/
    ├── dashboard/
    ├── model/
    ├── sessions/
    ├── chat/
    ├── layout/
    └── bootstrap.js
```

目录树是职责边界而不是强制文件清单；实施时若某个候选文件不足以形成独立职责，应与同阶段模块合并，避免碎片化。

## 已完成

- [x] `REF-001` 提取 Agent 叶子运行时模块：将静态工具目录与处理器注册表迁入 `app/agent_tools.py`，将模型 SSE 解析、隐藏推理审计和重试策略迁入 `app/model_streaming.py`；`app.agent` 保留原有 `TOOLS`、`TOOL_HANDLERS`、`search_agent_knowledge`、`_stream_completion` 与模型策略函数入口，使既有调用方和测试 patch 点不变。Agent 主编排控制流不调整。

## 当前产品待办

### 契约基线

- [x] `REF-002` 冻结结构重构兼容基线：`evaluations/refactor_contract_v1.json` 固定工具名称与完整 Schema 哈希、三条脱敏 Agent 链路的最终结果键/工具轨迹键/Trace-SSE 事件顺序、完整 OpenAPI 哈希、51 条方法/路径/成功码/operation 名，以及用户端和管理端全部 DOM ID 与脚本加载顺序。`scripts/refactor_contracts.py` 只允许检查或打印当前规范化契约，不提供自动覆写基线；测试强制 `synthetic_redacted`、真实模型 0、网络 0，并在差异时输出统一 diff。

### Agent 运行时

- [x] `REF-003` 建立 `agent_runtime` 基础边界：增加阶段输入/输出与运行状态 contracts、进度/审计 telemetry 和协调器接口；`app.agent` 保留现有公开入口及高频测试 patch 点，不移动业务控制流。`AgentRunRequest` 保留原始对象引用，`AgentRunResult` 是不包装、不复制的旧结果类型别名，协调器只按旧签名转发，生命周期继续只以首个 `answer_delta` 计算首答耗时；定向边界、Agent/Ready/Context 与冻结契约回归通过。
- [x] `REF-004` 拆分 Context、Router、DecisionArbiter、Playbook 与 Planner 准备阶段：Context Protocol helpers、`_resolve_conversation_turn`、路由/Playbook/计划进度和阶段初始化迁入 `agent_runtime/preparation`；`app.agent` 保留同名 facade 并在每次运行实时注入依赖，保持 resolved question、TurnDecision、计划内容、事件顺序与模型调用次数不变。新增 6 项准备阶段边界测试，116 项定向回归、冻结契约及 2026-08-26 宿主 full（430/362 Python、87% 覆盖率）均通过；`app.agent` 由 2860 行降至 2476 行（减少 384 行）。
- [x] `REF-005` 将工具运行时整理为文件夹：唯一的 Schema、Handler 注册表和单次执行器已迁入 `agent_runtime/tools/`；`app/agent_tools.py` 兼容导出与 `app.agent` 保持同一 catalog/registry 对象，单次参数解析保留 `{}` 默认、非对象/非法 JSON 的原始参数截断和异常语义，Ready、知识预取及兼容工具循环继续在调用时读取实时 patch 的注册表。新增 5 项边界测试、108 项定向回归、冻结契约及 2026-08-27 宿主 full（435/367 Python、87% 覆盖率）均通过；catalog/registry 对象身份和实时 registry patch 保持兼容。
- [x] `REF-006` 拆分确定性 Ready Plan、兼容 Agent Loop 与失败传播：`agent_runtime/execution` 接管稳定 Ready 依赖排序、确定性执行、兼容模型/工具循环和无副作用失败决策；`app.agent` 继续以实时依赖注入 facade 保留 patch 点。Ready 计划仍由服务端执行、模型业务工具选择数为 0，依赖阻塞、审计/进度顺序、重试及首个正文前降级语义不变。新增 3 项执行边界测试、105 项定向回归、冻结契约及 2026-08-28 宿主 full（438/370 Python、87% 覆盖率）通过；`app.agent` 由 2478 行降至 1801 行（减少 677 行）。
- [x] `REF-007` 拆分通用知识检索阶段：`agent_runtime/retrieval/general_knowledge.py` 接管 `_prefetch_general_knowledge`、查询重写、可用结果过滤、知识降级与披露判断；`app.agent` 保留实时依赖注入 facade，检索次数、来源过滤、模型知识边界、引用及工具/进度/审计顺序不变。新增 4 项离线检索边界测试、94 项定向回归、冻结契约及 2026-08-28 宿主 full（442/374 Python、87% 覆盖率）均通过；`app.agent` 由 1801 行降至 1613 行（减少 188 行）。
- [x] `REF-008` 拆分 Ready 综合、离线降级和结果组装：`agent_runtime/synthesis/` 接管 Ready synthesis、`_offline_answer` 与最终 result builder；Ready assistant 的结构化提交解析、离线降级和 Ready 无模型完整结果均在该边界内，`app.agent` 保留实时依赖注入 facade，回答正文、来源、Thinking Policy、模型健康和返回字段不变。新增 10 项合成边界测试、141 项定向回归、冻结契约、仓库检查及 2026-08-28 宿主 full（452/384 Python、88% 覆盖率）均通过；原始正文空白与实时 fallback facade patch 保持兼容，`app.agent` 由 1613 行降至 1256 行（减少 357 行）。
- [x] `REF-009` 收口 Agent coordinator 和兼容门面：每次调用由 `AgentCompatibilityFacade` 快照 `app.agent` namespace，保持 async/sync wrapper 语义与实时 patch；`CoordinatorRunState` 依次协调 prepare、availability、model、ready、loop 五阶段，`run_agent` 继续负责运行生命周期。已删除迁移后的重复内部实现，`app/agent.py` 由 1256 行降至 164 行、coordinator 降至 108 行；174 项定向回归、冻结契约、仓库检查和 2026-08-30 宿主 full 均通过。

### FastAPI

- [x] `REF-010` 建立 API application、errors、schemas 与 dependencies：application 提取 lifespan、errors 提取异常协议、schemas 提取 Pydantic 请求模型、dependencies 提取个人用户和 Admin 鉴权；`app.main.app`、lifespan、异常 handler、schema 与鉴权兼容导出继续可用，并在调用时保持实时 patch。URL、OpenAPI、认证、状态码和响应不变。新增 5 项 API 边界测试、78 项必要回归、冻结契约、仓库检查及 2026-08-31 宿主 full 均通过；`app/main.py` 由 1267 行降至 1125 行。
- [x] `REF-011` 按 system、enterprise、reports、models、admin、knowledge、sessions 和 monitor 拆分领域 Router；保持全部 URL、HTTP 方法、认证、状态码、响应结构和 OpenAPI 等价。已完成：8 个 `APIRouter` 经 `app.main` 运行时 namespace 保持实时 patch，同名兼容导出不变；Personal Job SSE 迁至 `app/api/services/personal_job_events.py`，`app/main.py` 1125→697（减少 428 行），新增 3 项 Router 边界测试；Chat/stream 留待 `REF-012`。
- [x] `REF-012` 拆分聊天请求与流式服务：新增 `app/api/routers/chat.py`、`services/chat.py` 与 `services/chat_stream.py`；迁移 `_prepare_chat`、模型能力检查/状态分类、非流式生命周期与持久化、NDJSON、队列/delivery metrics、成功/取消/HTTP/network/unexpected 错误和 finally。`app.main` 同名兼容导出及每调用 namespace patch 保持，`run_agent`、`emit` 与 helper patch 实时；URL/方法/认证/状态/响应/OpenAPI、事件顺序、首答、Session 关联和遥测不变，`main.py` 697→352（减少 345 行），新增 9 项 Chat 边界测试。
- [x] `REF-013` 收口 `app/main.py`：新增 `app/api/runtime_dependencies.py` 显式发布 103 个 runtime dependencies 到 `app.main`，对象身份和 live `app.main.*` patch 保持；统一 bundle 注册/导出，9 个 Router bundle 与路由顺序不变。app/lifespan、错误、鉴权、schemas、Chat aliases、URL/OpenAPI/响应兼容不变；`main.py` 352→227（减少 125 行）达到 150～250 行目标，新增 2 项边界测试冻结 103 项依赖身份、Router export 身份、无 `_routes` 临时泄漏和无迁回领域实现。

### 桌面前端

- [x] `REF-014` 提取前端核心层：新增 `app/static/app/core/{state,dom,api,toast,version}.js` 五个 UMD/CommonJS+globalThis 模块，完成 state 全字段/容器、DOM/格式、身份 headers、FabApiError/API、Toast 和版本检查等价迁移。index 保持普通 defer，core 按 state→dom→api→toast→version 在原 8 个辅助脚本前加载，原相对顺序不变、app.js 最后；冻结契约仅更新 index script_sources。错误文案、状态含义、API、Toast、版本 Banner/focus/visibility、DOM IDs 和视觉行为不变；`app.js` 1959→1879（减少 80 行），新增 8 项 `app_core` 边界测试。
- [x] `REF-015` 拆分知识、报表、能力和模型设置控制器：新增 `app/static/app/{knowledge,model,dashboard}/controller.js` 三个 UMD/CommonJS+globalThis 模块，个人知识上传/文档/Job SSE、工厂知识/历史案例、Dashboard/Capability/图表及 Thinking/模型配置均以显式依赖注入迁移；`app.js` 保留同名 facade、共享 state 与 `personalUploadQueue` 对象身份/事件绑定。DOM 标识、API 请求、上传队列、选择状态、Thinking、SSE 和请求取消不变；index 保持普通 defer、leaf helper 后加载 controller、app.js 最后，冻结契约仅更新 script_sources。`app.js` 1879→1153（减少 726 行），新增 6 项 Node 边界测试，Node 50→56。
- [x] `REF-016` 拆分 Session、聊天流和 Live Answer：新增 `app/static/app/chat/{presenter,controller}.js` 与 `app/static/app/sessions/controller.js` 三个 UMD/CommonJS+globalThis 模块，以显式依赖注入迁移 Markdown/来源/复制呈现、Session Library/对话状态，以及 NDJSON 流式请求、Live Answer、重试和遥测；`app.js` 保留同名 facade 与 REF-017 的布局/启动职责。API、Session localStorage、请求保护、回答/引用位置、增量 Markdown、复制、重试消息 ID、归档/恢复/删除、取消/drain 和浏览器遥测不变；index 普通 defer 顺序和冻结 `script_sources` 已同步。`app.js` 1153→426（减少 727 行），新增 2 项 Node 边界测试，Node 56→58；定向 Python 24/24、系统五组 13/15/13/17/10 和确定性 Playwright 17/17 均通过。完整门因 WSL 进程退出墙钟异常在知识组 91.6 秒超过 75 秒预算而停止，测试体本身 13/13 通过；未将该次运行宣称为 full 通过。
- [x] `REF-017` 拆分视图布局、Agent 面板和启动流程：新增 `app/static/app/layout/controller.js` 与 `app/static/app/bootstrap.js`，迁移视图切换、面板开合/宽度、全部事件绑定与 `init()`；`app.js` 成为 89 行 composition/兼容入口。通过 late-bound layout wrapper 保持循环依赖下的单一 state；DOM、API、CSS、脚本 defer 顺序和桌面视觉不变。首次 Playwright 15/17 暴露 layout 在 sessions 前创建并捕获 no-op `loadSessionLibrary`，两个会话旅程列表停在“正在加载”；未放宽测试，改为先创建 sessions 后注入 layout，并新增 Node 防回归契约。完整验收通过：Python 505 发现项、非系统 437/437、系统 13/15/13/17/10（98.1517 秒）、coverage 89%、Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（46.3 秒）；递归 JS syntax、冻结 script_sources/契约、仓库检查和 diff 均通过，普通门真实模型/外网为 0。

### 个人知识后端

- [x] `REF-018` 拆分个人知识 contracts、metadata 与 storage：新增 `personal_knowledge_runtime/{contracts,metadata,storage}.py`，迁移错误类型、Metadata/Patch/Section、Tag、文件名校验和存储路径；`app.personal_knowledge` 保留对象身份兼容导出，并以薄 wrapper 实时传递 facade 的 OCR 安全限制和 `get_settings` patch。自动标签顺序/上限、ACL 脱敏、错误文本、数据模型和 API 不变。新增 5 项模块边界测试；2026-09-06 标准环境 full 为 Python 510 发现项、442/442 非系统，系统 13/15/13/17/10（88.8155 秒）及全部预算通过，coverage 89%、Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（45.1 秒）、repository/refactor contract/diff 均通过，普通 full 的真实模型和外网调用均为 0。
- [x] `REF-019` 拆分上传 Job、抽取器和入库流程：新增 `personal_knowledge_runtime/extractors/`、`jobs.py` 和 `ingestion.py`；Facade 按调用构造依赖，确保 `db_session`、配置、OCR 限制、OCR 函数和审计 patch 实时生效。上传幂等、原子文件写入、OCR 质量门、FTS rowid、Job 状态机、重试、删除与清理语义不变。2026-09-06 标准环境 full 为 Python 515 发现项、447/447 非系统，系统数据/HTTP/知识/模型/会话均通过（102.6949 秒）且预算通过；coverage 89%、Node 20/20、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17、repository/refactor contract/diff 均通过，普通 full 零真实模型/外网；`refactor_contracts.py` 无参数检查模式通过。
- [x] `REF-020` 拆分文档查询、搜索和兼容门面：新增 `personal_knowledge_runtime/documents.py` 接管 Cursor、文档列表/详情/更新和文件读取，新增 `personal_knowledge_runtime/search.py` 接管 FTS 查询构造、Tag 优先召回、FTS/LIKE 降级、结果整形和 Chunk 查询；删除、pending job 继续由既有 `jobs.py` 负责，不重复实现。`app.personal_knowledge` 保留原函数、签名、异常身份和动态依赖 facade，`db_session`、时间、Cursor、文档回读、查询词及 metadata/job/storage helper 的实时 patch 继续生效。SQLite FTS5、附加 schema、分页、ACL、ready 状态、Tag 精确匹配优先、排序、limit、引用和错误语义均不变；facade 508→294 行，新增 2 项边界测试。2026-09-07 标准环境 full 为 Python 517 发现项、449/449 非系统，系统 13/15/13/17/10（132.3467 秒）及全部预算通过，覆盖率 89%、Node 20/20、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17，repository/refactor contract/diff 均通过，普通 full 零真实模型/外网。

### 第二梯队审计

- [x] `REF-021` 只读审计其余大模块：按行数/可执行语句、职责、调用方、Git 变化历史、当前覆盖率和回归风险审计 `database.py`、`answer_synthesizer.py`、`seed.py`、`planner.py`、`domain_playbooks.py` 与 `intent_router.py`。结论是 Router、Planner、Answer Synthesizer 和 SQLite 数据库层存在真实职责边界，生成 `REF-023` 至 `REF-026` 四项 `OPTIONAL` 候选；`seed.py` 是低频修改的确定性生成算法，`domain_playbooks.py` 主要是六个集中治理的不可变声明，当前均不拆分。任务只修改计划文档，没有修改产品代码；最近完整质量基线继续使用 2026-09-07 `REF-020` full。

审计快照：

| 模块 | 当前形态 | 变化与依赖判断 | 审计结论 |
|---|---|---|---|
| `database.py` | 1016 行、288 条语句、覆盖率 79% | 同时承担 400 余行 legacy Schema、增量迁移、连接/Journal、五部门库附加/校验、legacy 搬迁和缺陷目录；被大部分持久化模块直接依赖，且历次数据、Session、模型和知识功能持续追加 | 有真实边界，但与未来多数据库治理相邻；列为 `REF-026 OPTIONAL`，不得借结构重构实现 `DATA-017`/`DATA-019` |
| `answer_synthesizer.py` | 762 行、325 条语句、覆盖率 86% | 同时包含 `submit_analysis` Schema、答案契约、解析、证据/范围/因果守卫、降级、Markdown 渲染和 legacy 路径；历史修复多集中在安全与证据保持 | 安全敏感且有真实阶段边界，列为 `REF-025 OPTIONAL` |
| `seed.py` | 727 行、370 条语句、覆盖率 81% | 主要是固定市场锚点、制造模拟常量和一个强确定性生成流程；变化低频，拆分容易使随机数消费顺序和固定夹具漂移 | 当前不拆分；仅在模拟模型再次扩展时重审 |
| `planner.py` | 695 行、332 条语句、覆盖率 98% | 数据契约、范围、查询参数、步骤装配和预算已由函数分层，但 Validator/Guard 仍从实现模块导入公开类型，制造范围修复会跨多个 helper | 存在依赖方向和契约边界，列为 `REF-024 OPTIONAL` |
| `domain_playbooks.py` | 599 行、70 条语句、覆盖率 97% | 绝大多数行是六个不可变 Playbook 声明；选择和 prompt 逻辑很薄，集中展示有利于证据/安全规则统一评审 | 当前不拆分，不转成 YAML，也不为每个 Playbook 建文件 |
| `intent_router.py` | 597 行、255 条语句、覆盖率 96% | 混合声明式规则、文本模式、范围识别、时间解析、风险、确定性路由、语义提示和 prompt；历史上多次因通用问答、上下文与制造范围边界修复 | 变化压力最高且有真实阶段边界，列为 `REF-023 OPTIONAL` |

### 第二梯队可选候选

- `REF-023` `OPTIONAL`：建立 `intent_runtime/{contracts,rules,scope,time,routing}.py`，保留 `app/intent_router.py` 兼容门面。冻结 `IntentRoute.to_dict()`、日期边界、规则优先级、通用/对话/制造分类、范围澄清、风险等级、`apply_semantic_intent_hint()` 覆盖限制及 system prompt；不得趁重构扩充词表或改变语义 Router 策略。验收覆盖 Router/Context/Arbiter/Planner/Playbook/Trace 黄金集和完整离线质量门。
- `REF-024` `OPTIONAL`：建立 `planning_runtime/{contracts,scope,queries,steps,service}.py`，保留 `app/planner.py` 的公开 dataclass 身份与函数入口。拆分纯 contracts、范围/参数来源、制造查询、工具调用和 Ready 计划装配；plan ID、JSON、SQL 文本、步骤 ID/顺序/依赖、required、结果上限、预算及证据语义不得变化。依赖 `REF-023` 或证明可独立保持 `IntentRoute` 身份；验收覆盖 Planner、Validator、Guard、Ready execution、Playbook 和 Trace 回放。
- `REF-025` `OPTIONAL`：建立 `answer_synthesis_runtime/{contracts,tool_schema,parsing,claim_guard,rendering,service}.py`，保留 `app/answer_synthesizer.py` 兼容门面。冻结 `SUBMIT_ANALYSIS_TOOL` 完整 Schema 哈希、`AnswerContract`/报告/结果身份、source ref 规范化、结构化语义验证、范围/因果过度声明降级、模型知识披露、章节顺序、中文措辞和 legacy answer。验收覆盖 Answer Synthesizer、Evidence Validator/Semantics、Agent synthesis、Ready 与 Trace 回放；任何安全降级差异均回退。
- `REF-026` `OPTIONAL`：建立 `database_runtime/{schema,migrations,connections,departments,defect_catalog}.py`，保留 `app/database.py` 所有兼容导出。只重排现有 SQLite 实现，保持 `SCHEMA`/部门 Schema 执行结果、迁移顺序和幂等性、Row factory、Journal、busy timeout、ATTACH/TEMP VIEW、事务、legacy 搬迁、FTS rebuild、校验和缺陷别名完全不变。该任务不创建通用数据库抽象、不接入 MySQL/Oracle、不改 Schema，必须与 `DATA-019` 的 Provider 边界协调；验收至少覆盖 Database Manager、系统隔离快照、Schema/迁移等价、RAG/Session/模型持久化和宿主 full。

四项候选均不排期、不计入主任务统计；只有用户明确激活后才转为普通 `[ ]`，且仍遵守一次一个编号、一个提交。`REF-022` Coordinator 候选保持独立，不因本次审计自动激活。

### Coordinator 后续候选

- `REF-022` `OPTIONAL` 收口 Agent Coordinator 阶段拓扑与依赖边界：该任务依赖 `REF-021` 审计，不进入当前 `REF-016` 至 `REF-021` 串行队列。目标结构保留 `agent_runtime/coordinator.py` 作为唯一总协调器、`coordinator_state.py` 作为单次运行唯一主状态，新增 `dependencies.py` 与 `stages/{prepare,availability,model,ready,loop}.py`。
  1. 首先冻结五阶段顺序、提前返回、Ready/离线/Loop 三条路径、Progress/Audit/Trace 事件、最终返回结构及 `app.agent.*` 实时 patch 契约。
  2. 再将现有 `coordinator_{prepare,availability,model,ready,loop}.py` 迁入 `agent_runtime/stages/`，旧模块保留兼容导出，不为减少文件数重新合并阶段。
  3. 将过宽的 `CoordinatorDependencies` 拆为 Preparation、Availability、Model、Ready Execution、Agent Loop 和 Result 阶段依赖；`app.agent` 每次运行仍只快照一次实时依赖，阶段不得重新读取全局 namespace。
  4. 在不创建第二个可变事实源的前提下，按 Preparation、Model、Execution 和 Synthesis 分组 `CoordinatorRunState` 字段；兼容 `AgentLoopContext` 结束后必须同步回主状态。
  5. 最后仅收口已被契约测试覆盖的证据验证通知、Answer Synthesis 审计、模型健康记录和结果组装重复逻辑，不建立新的通用万能 helper。
- 验收要求：`app.agent.run_agent()` 签名、`coordinate_agent_run()` 唯一入口、依赖快照/对象身份、Ready 的零模型工具选择、离线降级、Agent Loop 停止/取消、事件顺序和响应字段全部不变；定向运行 Agent runtime/execution/module/preparation/tool-runtime、Ready Plan、冻结契约与仓库检查，再运行一次完整离线 `python scripts/run_quality_gate.py full`。`QA-010` 完整 7-run Live 不属于该任务验收。
- 风险与回退：最高风险为实时 patch 失效、阶段事件重排、Ready/Loop 状态分叉和兼容导入破坏；实施时应分为“阶段目录与兼容导出”、“分阶段依赖”、“状态/重复逻辑收口”三个独立提交，任一阶段出现行为差异时只回退对应提交。只有用户明确激活后，`REF-022` 才转为普通 `[ ]` 并纳入主统计和排期。

## 主要职责迁移映射

| 当前职责 | 目标模块 |
|---|---|
| `_resolve_conversation_turn` 与 Context Protocol helpers | `agent_runtime/preparation/context.py` |
| 路由、仲裁与路由阶段进度 | `agent_runtime/preparation/routing.py` |
| Playbook、Planner 和执行计划初始化 | `agent_runtime/preparation/planning.py` |
| 工具 Schema、注册和单次调用 | `agent_runtime/tools/` |
| `_ready_step_order`、`_execute_ready_plan` | `agent_runtime/execution/ready_plan.py` |
| 非 Ready 模型/工具循环 | `agent_runtime/execution/agent_loop.py` |
| `_prefetch_general_knowledge` 与知识降级 | `agent_runtime/retrieval/general_knowledge.py` |
| Ready 综合、`_offline_answer`、最终结果 | `agent_runtime/synthesis/` |
| `_run_agent_impl` | `agent_runtime/coordinator.py` |
| Personal Job SSE | `api/services/personal_job_events.py` |
| `_prepare_chat`、模型检查、`chat_stream` | `api/services/chat.py`、`chat_stream.py` |
| 知识、Session、聊天、报表、模型和布局前端 | `static/app/` 对应职责目录 |

## 可读性控制目标

以下是软约束，不作为机械拆分理由：

- 兼容门面约 100～250 行，coordinator 尽量不超过约 350 行。
- 普通职责模块约 100～400 行；普通函数尽量低于约 80 行。
- 流式协议或显式状态机可放宽至约 150 行，但必须只有一个变化原因。
- 依赖只允许从协调层指向阶段、阶段指向领域服务；工具和领域服务不得反向导入 coordinator。

## 每项验证门槛

1. 运行 `git diff --check`、仓库静态检查和对应模块针对性测试。
2. Agent/API/前端边界任务必须执行宿主 `full` 质量门；沙箱 TestClient 挂起不能替代宿主结果。
3. 比较工具名称、Schema、调用次数、Trace、最终结果字段、SSE/NDJSON 事件类型和顺序。
4. 比较 OpenAPI 路径、方法、认证、状态码和响应结构。
5. 比较 DOM 标识、脚本顺序、关键交互、无障碍和 Playwright 视觉基线。
6. 正常 quick/full 质量门真实模型和网络调用必须保持为 0。

## 风险与回滚

- 每个 `REF` 提交必须是可独立撤销的纯结构提交。
- 任一契约差异出现时保持任务未完成，回退该任务的结构移动；不得以新增兼容分支掩盖行为变化。
- 不在同一个任务中同时修改数据库 Schema、API、前端协议和模块边界。
- 现有高频 `app.agent.*`、`app.main.*` patch 点在迁移前建立清单；保留兼容入口或在同一任务中迁移为显式依赖注入，并证明断言等价。
