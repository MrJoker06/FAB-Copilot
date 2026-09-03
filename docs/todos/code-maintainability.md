# 代码可维护性 TODO

状态基线：`experiment/parallel-platform`，2026-08-28。

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
- [ ] `REF-016` 拆分 Session、聊天流和 Live Answer：迁移 Session Library、对话状态、流式请求、增量 Markdown、复制、重试、归档和流诊断；保持回答呈现、引用位置、取消语义和浏览器遥测不变。
- [ ] `REF-017` 拆分视图布局、Agent 面板和启动流程：迁移视图切换、面板开合/宽度、事件绑定与 `init()`，以 `bootstrap.js` 统一启动；`app.js` 最终只保留兼容入口并控制在约 150 行以内，不改变桌面视觉基线。

### 个人知识后端

- [ ] `REF-018` 拆分个人知识 contracts、metadata 与 storage：迁移错误类型、Metadata/Patch/Section、Tag、文件名校验和存储路径；`app.personal_knowledge` 保留兼容导出，数据模型和 ACL 不变。
- [ ] `REF-019` 拆分上传 Job、抽取器和入库流程：按文本、Office、PDF、图片划分抽取职责，迁移上传、进度、失败、OCR、分段、入库、重试和删除 Job；保持事务、状态机、幂等和清理语义不变。
- [ ] `REF-020` 拆分文档查询、搜索和兼容门面：迁移文档列表/更新/删除、Cursor、FTS 查询、Chunk 与 pending job；保持分页、召回、权限、引用和既有调用路径不变。

### 第二梯队审计

- [ ] `REF-021` 只读审计其余大模块：评估 `database.py`、`answer_synthesizer.py`、`seed.py`、`planner.py`、`domain_playbooks.py` 和 `intent_router.py` 的变化原因、依赖方向和真实维护成本。只生成后续候选计划；未经用户确认，不因行数机械拆分，也不实施代码改动。

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
