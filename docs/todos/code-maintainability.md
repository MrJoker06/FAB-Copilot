# 代码可维护性 TODO

状态基线：`experiment/parallel-platform`，2026-08-27。

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
- [ ] `REF-006` 拆分确定性 Ready Plan、兼容 Agent Loop 与失败传播：迁移 `_ready_step_order`、`_execute_ready_plan`、工具轮次状态机和模型/依赖失败路径；服务端继续确定性执行 Ready 计划，模型不恢复业务工具选择权。
- [ ] `REF-007` 拆分通用知识检索阶段：迁移 `_prefetch_general_knowledge`、查询重写、可用结果过滤、知识降级与披露判断；保持检索次数、来源过滤、模型知识边界和引用语义不变。
- [ ] `REF-008` 拆分 Ready 综合、离线降级和结果组装：迁移 Ready synthesis、`_offline_answer`、Answer Contract 与最终 result builder；保持回答正文、来源、Thinking Policy、模型健康和所有返回字段不变。
- [ ] `REF-009` 收口 Agent coordinator 和兼容门面：将 `_run_agent_impl` 改为按阶段调用的协调器，`run_agent` 继续负责运行生命周期；删除已经迁移且不再使用的内部重复实现，目标使 `app/agent.py` 约 100～250 行、coordinator 约 350 行以内。

### FastAPI

- [ ] `REF-010` 建立 API application、errors、schemas 与 dependencies：提取 lifespan、异常协议、Pydantic 请求模型、个人用户和 Admin 依赖；`app.main.app` 与现有兼容导出继续可用。
- [ ] `REF-011` 按 system、enterprise、reports、models、admin、knowledge、sessions 和 monitor 拆分领域 Router；保持全部 URL、HTTP 方法、认证、状态码、响应结构和 OpenAPI 等价。
- [ ] `REF-012` 拆分聊天请求与流式服务：迁移 `_prepare_chat`、模型能力检查、`chat`、`chat_stream`、NDJSON 编码、取消/异常处理和消息持久化；保持事件顺序、首答行为、Session 关联和遥测不变。
- [ ] `REF-013` 收口 `app/main.py`：只保留应用创建、Router 注册和必要兼容导出，删除已迁移实现；目标约 150～250 行，所有 TestClient 和 OpenAPI 契约通过。

### 桌面前端

- [ ] `REF-014` 提取前端核心层：将共享 state、API、身份请求头、DOM helpers、Toast 和版本检查迁入 `app/static/app/core/`；保持普通 `defer` 加载、全局状态含义和错误显示不变。
- [ ] `REF-015` 拆分知识、报表、能力和模型设置控制器：迁移个人知识上传/文档/Job SSE、Dashboard/Capability/图表及 Thinking/模型配置；保持 DOM 标识、API 请求、上传队列和选择状态不变。
- [ ] `REF-016` 拆分 Session、聊天流和 Live Answer：迁移 Session Library、对话状态、流式请求、增量 Markdown、复制、重试、归档和流诊断；保持回答呈现、引用位置、取消语义和浏览器遥测不变。
- [ ] `REF-017` 拆分视图布局、Agent 面板和启动流程：迁移视图切换、面板开合/宽度、事件绑定与 `init()`，以 `bootstrap.js` 统一启动；`app.js` 最终只保留兼容入口并控制在约 150 行以内，不改变桌面视觉基线。

### 个人知识后端

- [ ] `REF-018` 拆分个人知识 contracts、metadata 与 storage：迁移错误类型、Metadata/Patch/Section、Tag、文件名校验和存储路径；`app.personal_knowledge` 保留兼容导出，数据模型和 ACL 不变。
- [ ] `REF-019` 拆分上传 Job、抽取器和入库流程：按文本、Office、PDF、图片划分抽取职责，迁移上传、进度、失败、OCR、分段、入库、重试和删除 Job；保持事务、状态机、幂等和清理语义不变。
- [ ] `REF-020` 拆分文档查询、搜索和兼容门面：迁移文档列表/更新/删除、Cursor、FTS 查询、Chunk 与 pending job；保持分页、召回、权限、引用和既有调用路径不变。

### 第二梯队审计

- [ ] `REF-021` 只读审计其余大模块：评估 `database.py`、`answer_synthesizer.py`、`seed.py`、`planner.py`、`domain_playbooks.py` 和 `intent_router.py` 的变化原因、依赖方向和真实维护成本。只生成后续候选计划；未经用户确认，不因行数机械拆分，也不实施代码改动。

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
