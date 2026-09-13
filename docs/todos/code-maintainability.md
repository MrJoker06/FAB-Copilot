# 代码可维护性 TODO

状态基线：`experiment/parallel-platform`，2026-09-08。

本清单只处理结构、模块边界和可读性，不改变业务逻辑、API 契约、SSE/NDJSON 事件、工具调用顺序、Trace、数据库结构或前端交互。每项重构都保留必要的兼容门面，并以现有回归测试作为行为基线。

## 设计原则

1. 采用“一个职责或运行阶段一个模块”，不采用机械的“一个函数一个文件”。强相关辅助函数保留在同一模块；只有能够独立复用、独立测试或拥有复杂状态的函数才单独成文件。
2. Python 内部实现按领域归类。REF-034 及之前保留根目录兼容门面；用户随后要求实际精简目录，新增 REF-035，将根目录收敛为 `__init__.py` 与 `main.py`，Agent 与个人知识入口迁入各自运行时目录。
3. 前端继续使用普通 `defer` 脚本和显式加载顺序，不引入打包器或 ES Module；`app/static/app.js` 最终只保留兼容启动入口。
4. 工具目录、注册、执行和领域实现分层：运行时只负责 Schema、Handler 映射、权限/预算与结果归一化；`reports.py`、`enterprise_data.py`、`rag.py` 和 `answer_synthesizer.py` 继续拥有真实业务实现。
5. 一次只完成一个 `REF` 编号并独立提交。行为变化、数据库迁移或 API 调整必须另建任务，不能混入结构重构。

## 第一轮目标目录（历史设计）

以下保留第一轮阶段拆分设计；新一轮根目录归档以“领域目录重构”中的映射为准。既有运行时边界不因命名统一再次搬迁。

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

- [x] `REF-021` 只读审计其余大模块：按行数/可执行语句、职责、调用方、Git 变化历史、当前覆盖率和回归风险审计 `database.py`、`answer_synthesizer.py`、`seed.py`、`planner.py`、`domain_playbooks.py` 与 `intent_router.py`。结论是 Router、Planner、Answer Synthesizer 和 SQLite 数据库层存在真实职责边界，形成 `REF-023` 至 `REF-026` 候选；随后用户已激活 `REF-022` 至 `REF-024`，`REF-025`、`REF-026` 仍不排期。`seed.py` 是低频修改的确定性生成算法，`domain_playbooks.py` 主要是六个集中治理的不可变声明，当前均不拆分。任务只修改计划文档，没有修改产品代码。

审计快照：

| 模块 | 当前形态 | 变化与依赖判断 | 审计结论 |
|---|---|---|---|
| `database.py` | 1016 行、288 条语句、覆盖率 79% | 同时承担 400 余行 legacy Schema、增量迁移、连接/Journal、五部门库附加/校验、legacy 搬迁和缺陷目录；被大部分持久化模块直接依赖，且历次数据、Session、模型和知识功能持续追加 | 有真实边界，但与未来多数据库治理相邻；列为 `REF-026 OPTIONAL`，不得借结构重构实现 `DATA-017`/`DATA-019` |
| `answer_synthesizer.py` | 762 行、325 条语句、覆盖率 86% | 同时包含 `submit_analysis` Schema、答案契约、解析、证据/范围/因果守卫、降级、Markdown 渲染和 legacy 路径；历史修复多集中在安全与证据保持 | 安全敏感且有真实阶段边界，列为 `REF-025 OPTIONAL` |
| `seed.py` | 727 行、370 条语句、覆盖率 81% | 主要是固定市场锚点、制造模拟常量和一个强确定性生成流程；变化低频，拆分容易使随机数消费顺序和固定夹具漂移 | 当前不拆分；仅在模拟模型再次扩展时重审 |
| `planner.py` | 695 行、332 条语句、覆盖率 98% | 数据契约、范围、查询参数、步骤装配和预算已由函数分层，但 Validator/Guard 仍从实现模块导入公开类型，制造范围修复会跨多个 helper | 存在依赖方向和契约边界，`REF-024` 已完成 |
| `domain_playbooks.py` | 599 行、70 条语句、覆盖率 97% | 绝大多数行是六个不可变 Playbook 声明；选择和 prompt 逻辑很薄，集中展示有利于证据/安全规则统一评审 | 当前不拆分，不转成 YAML，也不为每个 Playbook 建文件 |
| `intent_router.py` | 597 行、255 条语句、覆盖率 96% | 混合声明式规则、文本模式、范围识别、时间解析、风险、确定性路由、语义提示和 prompt；历史上多次因通用问答、上下文与制造范围边界修复 | 变化压力最高且有真实阶段边界，`REF-023` 已完成 |

### 第二梯队候选与排期

- [x] `REF-023` 建立 `intent_runtime/{contracts,rules,scope,time,routing}.py`，`app/intent_router.py` 成为兼容门面并保留类型、常量、公开函数和内部 helper 身份/入口。规则、范围、日期和路由逻辑机械迁移，词表、优先级、日期、风险、语义 hint 与 system message 不变；新增门面、运行时反向依赖、对象身份和日期/规则快照测试，完整离线质量门通过。
- [x] `REF-024` 建立 `planning_runtime/{contracts,scope,queries,steps,service}.py`，`app/planner.py` 为薄兼容门面并保持公开 dataclass/函数与私有 helper 入口。运行时直接依赖 `intent_runtime.contracts`，计划 schema、plan ID、JSON、SQL、步骤、范围和预算语义机械保持；Planner、Validator、Guard、Ready、Playbook、Agent 回归与完整离线质量门通过。
- `REF-025` `OPTIONAL`：建立 `answer_synthesis_runtime/{contracts,tool_schema,parsing,claim_guard,rendering,service}.py`，保留 `app/answer_synthesizer.py` 兼容门面。冻结 `SUBMIT_ANALYSIS_TOOL` 完整 Schema 哈希、`AnswerContract`/报告/结果身份、source ref 规范化、结构化语义验证、范围/因果过度声明降级、模型知识披露、章节顺序、中文措辞和 legacy answer。验收覆盖 Answer Synthesizer、Evidence Validator/Semantics、Agent synthesis、Ready 与 Trace 回放；任何安全降级差异均回退。
- `REF-026` `OPTIONAL`：建立 `database_runtime/{schema,migrations,connections,departments,defect_catalog}.py`，保留 `app/database.py` 所有兼容导出。只重排现有 SQLite 实现，保持 `SCHEMA`/部门 Schema 执行结果、迁移顺序和幂等性、Row factory、Journal、busy timeout、ATTACH/TEMP VIEW、事务、legacy 搬迁、FTS rebuild、校验和缺陷别名完全不变。该任务不创建通用数据库抽象、不接入 MySQL/Oracle、不改 Schema，必须与 `DATA-019` 的 Provider 边界协调；验收至少覆盖 Database Manager、系统隔离快照、Schema/迁移等价、RAG/Session/模型持久化和宿主 full。

`REF-022`、`REF-023`、`REF-024` 已完成；`REF-025`、`REF-026` 仍不排期、不计入主任务统计。

### Coordinator 后续候选

- [x] `REF-022` 收口 Agent Coordinator 阶段拓扑与依赖边界：保留 `agent_runtime/coordinator.py` 作为唯一总协调器、`coordinator_state.py` 作为单次运行唯一主状态，新增 `dependencies.py` 与 `stages/{prepare,availability,model,ready,loop}.py`。旧 `coordinator_*` 均为薄兼容导出；依赖按 Preparation/Availability/Model/Ready/Loop 分组且保留旧属性访问，状态以实时分组视图收口但不复制事实。
  1. 首先冻结五阶段顺序、提前返回、Ready/离线/Loop 三条路径、Progress/Audit/Trace 事件、最终返回结构及 `app.agent.*` 实时 patch 契约。
  2. 再将现有 `coordinator_{prepare,availability,model,ready,loop}.py` 迁入 `agent_runtime/stages/`，旧模块保留兼容导出，不为减少文件数重新合并阶段。
  3. 将过宽的 `CoordinatorDependencies` 拆为 Preparation、Availability、Model、Ready Execution、Agent Loop 和 Result 阶段依赖；`app.agent` 每次运行仍只快照一次实时依赖，阶段不得重新读取全局 namespace。
  4. 在不创建第二个可变事实源的前提下，按 Preparation、Model、Execution 和 Synthesis 分组 `CoordinatorRunState` 字段；兼容 `AgentLoopContext` 结束后必须同步回主状态。
  5. 最后仅收口已被契约测试覆盖的证据验证通知、Answer Synthesis 审计、模型健康记录和结果组装重复逻辑，不建立新的通用万能 helper。
- 验收要求：`app.agent.run_agent()` 签名、`coordinate_agent_run()` 唯一入口、依赖快照/对象身份、Ready 的零模型工具选择、离线降级、Agent Loop 停止/取消、事件顺序和响应字段全部不变；定向运行 Agent runtime/execution/module/preparation/tool-runtime、Ready Plan、冻结契约与仓库检查，再运行一次完整离线 `python scripts/run_quality_gate.py full`。`QA-010` 完整 7-run Live 不属于该任务验收。
- 风险与回退：最高风险为实时 patch 失效、阶段事件重排、Ready/Loop 状态分叉和兼容导入破坏；阶段目录、依赖分组和状态视图已在同一任务提交中通过定向与完整质量门验证，出现行为差异时整体回退该提交。

## 领域目录重构（已完成）

2026-09-08 用户确认方案并要求写入 TODO、提交；`REF-027` 至 `REF-034` 已完成文件归属、内部 canonical 导入与必要兼容装配，未改变业务设计。`REF-025`、`REF-026` 继续 OPTIONAL，未激活内部拆分；未来激活时应基于届时规范路径重新评审目录，不能恢复重复实现。

### 目标归属与迁移映射

| 当前 app 根目录文件 | 目标位置 | 责任边界 |
|---|---|---|
| `__init__.py`、`main.py`、`config.py`、`identity.py` | 保持原位置 | 包入口、应用装配、配置路径锚点及跨领域身份上下文 |
| `agent.py`、`personal_knowledge.py` | 保持原位置 | 必须保留的兼容入口，不迁回真实业务实现 |
| `context_resolver.py`、`turn_decision.py`、`decision_arbiter.py`、`sessions.py` | `conversation/` 下同名文件 | 上下文、会话动作与仲裁、会话生命周期 |
| `model_registry.py`、`model_compatibility.py`、`model_health.py`、`model_streaming.py` | `model_gateway/{registry,compatibility,health,streaming}.py` | 模型访问及治理，不是新增网关服务 |
| `evidence_semantics.py`、`evidence_validator.py`、`answer_synthesizer.py` | `evidence/{semantics,validator,answer_synthesizer}.py` | 证据范围、验证与答案契约/渲染；本轮不拆综合器内部实现 |
| `rag.py`、`knowledge_decision.py`、`ocr.py`、`ocr_quality.py` | `knowledge/{rag,decision,ocr,ocr_quality}.py` | 公共检索、知识决策与共享 OCR |
| `processes.py`、`domain_playbooks.py`、`reports.py`、`enterprise_data.py`、`seed.py` | `manufacturing/{processes,playbooks,reports,enterprise_data,seed}.py` | 制造定义、报表、现有模拟 Provider 与种子数据 |
| `database.py`、`department_schemas.py`、`execution_store.py` | `persistence/` 下同名文件 | SQLite 连接/Schema/迁移、执行记录；本轮不拆 database 内部实现 |
| `audit.py`、`observability.py`、`runtime_status.py` | `telemetry/{audit,http,runtime_status}.py` | 审计、HTTP 遥测和运行状态 |
| `assistant_capabilities.py`、`loop_guard.py` | `agent_runtime/assistant_capabilities.py`、`agent_runtime/execution/loop_guard.py` | 能力声明与运行循环守卫 |
| `agent_tools.py`、`intent_router.py`、`planner.py` | 真实实现继续由现有运行时持有 | 旧入口先审计消费者，再决定保留或退役 |

保留 `api/`、`agent_runtime/`、`intent_runtime/`、`planning_runtime/`、`personal_knowledge_runtime/` 既有职责；`static/` 本轮不动。`knowledge/` 不重复个人文档的上传、Job、存储、搜索实现。Session 业务归 conversation，制造查询归 manufacturing，不因使用数据库而统一塞入 persistence。

### 普通任务与验收

- [x] `REF-027` 归属与兼容基线：`evaluations/module_boundaries_v1.json` 已逐项登记 36 个根模块及 package anchor 的目标、消费者与保留/退出条件；[领域模块归属与兼容基线](../domain-module-boundaries.md) 审计生产、脚本、测试、patch 与资源路径。`scripts/check_module_boundaries.py` 已由仓库检查和质量门执行，覆盖相对/绝对/函数内及已知字面量动态导入，拒绝新增领域反向边和纯模块的 storage/entry 依赖；当前树的 26 条既有跨领域例外均以精确源/目标、理由和退出条件登记，并校验清单输入和过期例外。负向 fixture、冻结契约和仓库检查通过。2026-09-10 宿主完整离线质量门发现 536 个 Python 测试，468/468 非系统测试及五组系统测试 13/15/13/17/10 均通过，覆盖率 89%、Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17，普通门未调用真实模型或外网；未移动业务模块或刷新行为基线。
- [x] `REF-028` 制造领域归档：`processes`、`playbooks`、`reports`、`enterprise_data`、`seed` 已机械迁入 `app/manufacturing/`，39 个消费者只更新导入；旧入口保留薄兼容门面。`app.seed` 与 canonical seed 均按调用解析 live patch 依赖，公开类型、函数和工具 Handler 身份不变；26 条精确例外改为 canonical 源且未扩大。2026-09-10 宿主完整离线质量门发现 541 个 Python 测试，473/473 非系统测试及五组系统测试 13/15/13/17/10 均通过，覆盖率 89%、Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17，普通门未调用真实模型或外网；未新增 Oracle/MySQL Provider、迁移或行为基线变化。
- [x] `REF-029` 存储基础归档：`database`、`department_schemas`、`execution_store` 已机械迁入 `app/persistence/`，旧入口为薄兼容门面；保持 db_session、Schema、初始化、事务、连接关闭、Journal、ATTACH/TEMP VIEW、FTS、迁移幂等性和中断恢复行为。Database Manager、隔离系统快照、执行记录及 RAG/Session/模型持久化均经完整门验证；未迁移真实数据、未改变数据库文件位置或 Schema 行为，未激活 REF-026。
- [x] `REF-030` 遥测领域归档：`audit`、`observability`、`runtime_status` 已机械迁入 `app/telemetry/{audit,http,runtime_status}.py`，旧入口为薄兼容门面并共享 ContextVar、logger/handler、锁和运行状态；请求 ID、脱敏、完整日志策略及到期回退、日志路径、事件/Trace 字段、取消/finally 与运行状态不变。审计策略、HTTP 生命周期、Trace 回放、监控响应和 import 顺序均经验证，未改变日志结构。
- [x] `REF-031` 模型访问归档：registry、compatibility、health、streaming 的唯一实现已迁入 `app/model_gateway/`，生产、脚本和非 health 测试使用 canonical 导入；旧入口保留兼容门面。管理员显式配置与主动探针、Thinking 策略、解析、重试、熔断和恢复租约不变；类型、异常和非 health 函数对象身份保持，health 的旧/新公共 wrapper 为刻意独立函数但签名一致，`app.model_health.db_session` 的必需 live patch 继续按调用生效。导入顺序不探测 Provider；不自动联网判断能力，不更改 Provider 协议。
- [x] `REF-032` 会话与运行时归档：`context_resolver`、`turn_decision`、`decision_arbiter`、`sessions` 的唯一实现已机械迁入 `app/conversation/`；`assistant_capabilities` 迁入 `app/agent_runtime/`，`loop_guard` 迁入 `app/agent_runtime/execution/`，旧入口保留兼容门面。原问题与补全问题的来源、意图决策、消息 ID、幂等、历史回忆、归档/恢复/删除、预算和停止条件不变；旧/新入口的公开及私有导出身份保持，`MODULE:app.context_resolver` 冻结字面量保持。六个实现体忽略 import 后 AST 等价，15 个消费者仅更新导入；Context/Arbiter/Guard、Agent 准备、Session 流式系统测试和桌面会话旅程均已验证。
- [x] `REF-033` 知识与证据归档：RAG/OCR/知识决策迁入 `app/knowledge/`，证据语义/验证/答案综合迁入 `app/evidence/`，旧入口保留薄兼容门面。FTS 查询、ACL、Tag/排序/limit、引用、声明守卫、降级和最终渲染不变；OCR 继续通过 `rapidocr.__file__` 定位本地 wheel 模型，单例/锁与个人知识 facade patch 保持。语义模块仍为纯边界，未激活 REF-025 或重复个人知识运行时；RAG/OCR 黄金集、证据/综合、Ready/Trace 回放和完整知识桌面旅程均通过。
- [x] `REF-034` 兼容入口退役与收口：17 个消费者仅更新为 canonical 导入，29 个无内部 Python 生产/脚本消费者的过渡 facade 由 AST 清单守卫禁止回流；36 个根入口继续保留，其中 `main`、`agent`、`personal_knowledge`、`config`、`identity` 为长期锚点，`seed` CLI 与 `model_health.db_session` patch 为明确兼容合同。没有外部迁移证据，故没有删除公开 facade。`allowed_domain_dependencies` 未扩大；原 `app.agent_runtime.compatibility -> app.intent_router` 例外改为 `contracts`、`routing`、`rules` 三条精确 canonical 边，例外总数为 28。主代理定向 47/47（11.320 秒）、冻结契约、仓库、边界与 diff 检查通过；2026-09-13 宿主完整离线质量门发现 569 个 Python 测试，501/501 非系统测试及五组系统测试 13/15/13/17/10 全通过，墙钟 15.599845838/16.172799632/17.754458358/15.565569326/16.426263403 秒、总计 81.519137426 秒且全部预算通过，coverage 89%、Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（45.7 秒）均通过；普通门未调用真实模型或外部服务。`REF-027` 至 `REF-034` 系列收口，不自动激活暂缓或 `OPTIONAL` 任务。

### 兼容与依赖规则

1. REF-027 至 REF-034 按当时约定保留 `app.main`、`app.agent`、`app.personal_knowledge` 等兼容入口；下述 REF-035 根据用户新增的目录精简要求覆盖这一保留策略，仅保留 `app.main:app` 启动入口，旧 Python 导入路径明确退役。
2. 重新导出函数不等于保留旧模块实时 patch：必须保留的 patch 契约需验证实际执行；内部测试可以迁至真实实现或显式注入点，但断言强度不降低。类型/异常/注册表对象身份同样需验证。
3. 每项只保留一份真实实现；禁止通过复制实现或大规模 sys.modules 别名掩盖问题。过渡门面登记目标、消费者、保留原因及退出条件。
4. API/协调器负责装配，领域模块不得反向依赖 app.main 或协调器；contracts、规则和纯计算模块不得引入数据库/网络/应用入口依赖。对既有例外登记并防止扩大，需要设计变更的部分另行评审。
5. 每项同时更新生产代码、脚本、测试和文档中的消费者；迁移期间允许登记的过渡入口，但每个任务提交均须可独立运行及验收。

### REF-035：根目录精简与旧入口退役（已完成）

- [x] `REF-035` 精简 `app/` 根目录并按功能归类：根据用户“简洁目录，功能模块化并归类好”的新增要求，根目录仅保留 `__init__.py` 和 `main.py`；将配置、身份、Agent、个人知识入口分别迁至 `core/settings.py`、`core/identity.py`、`agent_runtime/service.py`、`personal_knowledge_runtime/service.py`，删除其余 31 个根目录兼容文件，并同步生产、脚本、测试与文档引用。

范围与兼容边界：`app.main:app`、HTTP API、页面功能、业务逻辑、数据库位置和 Schema 保持不变；`app.agent`、`app.config`、`app.rag` 等 35 个旧 Python 模块路径停止支持，不建立别名或转发层。种子数据入口改为 `python -m app.manufacturing.seed`；实时 patch 使用新的实现命名空间。冻结的 `MODULE:app.*` 展示标识保持不变，通过退役映射验证实际实现。

完成结果：代码迁移和目录精简已落地，独立审查与完整离线质量门通过。四个搬迁实现的 AST 等价检查（除导入及配置资源定位层级）通过；主代理定向 63 项核心/启动测试与 29 项领域边界测试通过，冻结契约和仓库检查通过。退役清单登记 35 个旧路径，并检查物理重建、绝对/相对/嵌套/字面量动态旧导入及目标有效性。

验收记录：首次完整离线质量门因能力目录测试仍直接导入冻结旧标识而失败 1 项，原始记录保留在 `runtime/quality/ref035-full-parent.log`。测试修复后通过退役映射验证真实模块，相关 17 项测试及冻结契约通过。2026-09-13 `REF-035` 宿主完整离线质量门重跑 exit 0：发现 576 个 Python 测试，508/508 非系统测试（67.545 秒），系统数据/HTTP/知识/模型/会话 13/15/13/17/10 全通过，墙钟 20.381070265/17.895252597/21.359629731/17.605863887/24.480409194 秒、总计 101.722489564 秒，全部预算通过；coverage 89%，Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（43.4 秒）均通过。结果保存于被 Git 忽略的 `runtime/quality/ref035-full-parent-rerun.log`；普通门未调用真实模型或外部服务。 `QA-010` 远程 Live、其他暂缓项和 `OPTIONAL` 项不在本任务范围内。

风险与回退：外部 Python 调用方须迁移到领域路径；已删除文件可从 Git 历史恢复。迁移和删除应作为同一任务提交整体回退，不恢复重复业务实现。

### 验证、风险与交付

每项运行对应领域定向测试，并执行：

```bash
conda run -n fab-insight-agent python scripts/refactor_contracts.py
conda run -n fab-insight-agent python scripts/check_repository.py
conda run -n fab-insight-agent python scripts/run_quality_gate.py full
git diff --check
```

额外检查导入顺序/循环依赖、实时 patch/对象身份、`__file__` 和相对资源路径、配置与脚本启动、工具 Schema/调用次数、API/事件顺序、数据库事务/FTS/租户隔离/引用及测试发现无遗漏。不得通过刷新行为基线消除不符合预期的差异。普通 full 零真实模型/外网；QA-010 远程 Live 继续暂缓，不作为本轮前置条件。本次计划登记只做文档检查，不宣称已运行上述实现验收。

一个任务一个提交，主代理先规划、按 AGENTS.md 委派代码实现，再独立审查和验证。实现后同步 TODO、执行计划、相关架构文档及 execution-history；计划登记不写成实现完成记录。遇到行为差异保持未完成，按依赖逆序撤销相关结构提交；不需要数据库数据回滚，不通过破坏性重置丢弃其他改动。

## 主要职责迁移映射（第一轮）

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
