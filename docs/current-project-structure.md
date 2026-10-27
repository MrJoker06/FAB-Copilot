# 当前项目精细结构快照

快照日期：2026-10-27。依据为 experiment/parallel-platform 分支的 WSL 源码（基线提交 `0c93cf6` 之后的模块化改造及 MOD-008 首批）。MOD-014 已验收，MOD-008 首批已验证，整个 MOD-008 仍进行中；验收证据以对应报告为准，当前提交与远程同步状态以 Git 记录为准。

本次实扫 `app/` 的受管源码为 **215 文件：187 个 Python、28 个静态文件**。数量与
`evaluations/mod_003_boundaries_v1.json` 一致；测试、日志、缓存和运行期生成物不计入。

## 1. 当前物理树与逻辑边界

```text
app/
├── main.py                         HTTP 启动与应用组合
├── api/                            HTTP 路由、请求模型、流式聊天服务
├── bootstrap/                      显式装配与旧绑定组合的过渡区
├── agent_runtime/                 协调器、执行、工具、综合与兼容入口
├── planning_runtime/              Router 输入后的 Plan/步骤生成
├── intent_runtime/                规则路由、时间与范围解析
├── manufacturing/                 Playbook、旧报告、设备健康及 Cpk/传感器纯工具
├── integrations/manufacturing/    设备健康、过程诊断的 Fake/只读 SQLite Adapter
├── knowledge/                     RAG、检索决策、搜索契约与 SQLite 后端
├── evidence/                      证据描述、校验、答案综合和序列化
├── memory_system/                 当前上下文记忆的规则、Port 与服务
├── conversation/                  会话决策、上下文兼容、会话存取
├── model_gateway/                 Provider 配置、健康与 SSE 流式协议
├── persistence/                   SQLite 初始化、schema、执行记录
├── personal_knowledge_runtime/    个人知识文件、抽取、索引、任务与服务
├── core/                          设置和身份
├── telemetry/                     审计、HTTP 与运行状态
└── static/                        浏览器界面与前端控制器
```

边界标签：**纯** 表示该文件不应读取配置、连库或创建客户端；**装配** 表示把具体实现连接到
契约；**兼容** 表示保留旧导出、动态 patch 或旧调用；**Adapter** 表示外部/SQLite/Fake 技术
实现；**存储** 表示应用自有持久化。

## 2. 实际调用链

### 旧应用链（仍是默认应用入口）

```text
HTTP app.main / api
  → agent_runtime.service.run_agent
  → compatibility 的 live namespace + CoordinatorDependencies
  → coordinator / stages.prepare / availability / ready / loop
  → Ready: ready_plan 的旧回调 或 Loop: agent_loop 的旧 Handler 回调
  → tools.catalog / tools.registry 的兼容对象
  → bootstrap.tool_bindings → manufacturing.reports / knowledge.rag / enterprise_data
  → persistence.database 或具体后端
  → evidence.validator / answer_synthesizer → 流式回答与审计
```

该链仍保留 `agent_loop.py` 内的 `httpx.AsyncClient` 生命周期、Provider 请求和重试；这正是
MOD-012 的目标，不能把当前 Loop 接缝称作完整 ModelGateway 解耦。

### 新的显式试点链（MOD-011～014 的受控分支）

```text
AgentDefinition + bootstrap.agent_assembly
  → AgentApplication.new_run → AgentRun
  → RuntimeContext + 本地 ToolRegistry + ToolDispatcher
  → Ready: bind_ready_run → execute_dispatched_ready_plan
       或 Loop: bind_loop_run → classify_loop_response → execute_dispatched_loop_round
  → ToolBinding → EquipmentHealthPort / ProcessDiagnosticsPort
  → 各自的 Fake Adapter 或显式只读 SQLite Adapter
  → ToolResult / Scope / Source → tool_result_bridge → EvidenceObservation
```

这一链只验证单个设备健康工具及显式 legacy 适配的共同 Dispatcher 语义。它并未把所有旧工具、
所有数据源、HTTP 生命周期、会话存储或 Skill 迁入新装配。

### 仓库根目录与交付资产

| 位置 | 作用 |
| --- | --- |
| `run.sh`、`run.bat` | 启动与实例管理入口；WSL 开发使用 run.sh。 |
| `requirements.txt`、`requirements-test.txt` | 应用及测试依赖范围；当前不是整套环境的精确锁文件。 |
| `package.json`、`package-lock.json` | Playwright/axe 浏览器验证依赖；页面本体是 static 中的 JavaScript/CSS。 |
| `.editorconfig`、`.gitattributes` | UTF-8、LF 和 Git 文本/二进制规则。 |
| `.env.example`、`.env` | 配置模板与本机配置；配置值不写入本结构说明。 |
| `PROJECT_INDEX.md`、`AGENTS.md`、`README.md`、`TODO.md` | 项目入口索引、协作规则、使用说明和任务索引。 |
| `docs/`、`evaluations/` | 方案/验收报告，以及边界清单、历史基线和固定评估数据。 |
| `scripts/` | 构建源码单元、安装试点、边界检查、离线验收和实例/样例库管理 CLI。 |
| `knowledge/`、`cases/` | 知识与历史案例内容资产，独立于检索算法实现。 |
| `data/`、`backups/` | 本地合成/应用自有数据库及备份；不是纯工具模块源码。 |
| `runtime/` | run.sh 的实例源码快照、实例数据，以及 quality/portable 验收产物；与 app/agent_runtime 的执行源码不同。 |
| `tests/`、`logs/`、缓存与 node_modules | 验证、日志和生成依赖；本说明不逐文件展开，不计入 215 源码文件。 |
| `fab_litho_agent_gantt_boss.xlsx` | 用户的规划参考资产，不是运行时依赖。 |

### 关键接口与状态归属

| 边界 | 当前接口与职责 |
| --- | --- |
| Runtime → 模型 | ModelResponsePort.complete(ModelRequest, RuntimeContext) → ModelResponse；旧默认 Loop 的 httpx 生命周期仍待 MOD-012。 |
| Runtime → 工具 | ToolDispatcherPort.dispatch(name, raw_arguments, ToolExecutionContext) → ToolResult；真实 Dispatcher 管输入、能力/Scope、期限/取消和唯一记账。 |
| 工具 → 业务数据 | EquipmentHealthPort.fetch / ProcessDiagnosticsPort.fetch(query, principal) → Snapshot；输入是固定业务查询，SQL 不进入新增原生模型参数。 |
| Adapter → 来源 | Fake 精确夹具或显式只读 SQLite。诊断的 capability 只用制造库，sensors 只用设备库；不附挂其余数据库。 |
| 结果采用 | ToolResultPolicy 在预算记账前过滤/截断；Source Scope 同时含过程与设备时，桥接保留两项真实过滤。 |
| 运行状态 | AgentDefinition 保存声明，RuntimeContext 保存可信上下文，Guard 是预算/进展权威；旧应用仍由 CoordinatorRunState 管阶段状态。 |
| Memory / 内部存储 | ContextService 消费 ContextModel/Rules/Events 等 Port；会话和执行记录尚有直接 SQLite 依赖，后续走 Store/Repository，不要求模型调用业务 Tool 来读写内部会话。 |

## 3. 源码清单与职责

### 包根、API 与 bootstrap

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/__init__.py` | 包 | 应用包锚点。 |
| `app/main.py` | 装配 | FastAPI 应用、lifespan、路由和静态资源启动入口。 |
| `app/api/__init__.py` | 包 | API 包锚点。 |
| `app/api/application.py` | 装配 | API 应用/路由安装与跨域等 HTTP 组合。 |
| `app/api/dependencies.py` | 装配 | 请求级依赖与身份/设置获取。 |
| `app/api/errors.py` | 业务 | HTTP 错误规范化。 |
| `app/api/runtime_dependencies.py` | 装配/存储 | API 对运行时、数据库和服务的具体依赖组合。 |
| `app/api/schemas.py` | 纯 | API Pydantic/数据传输结构。 |
| `app/api/routers/__init__.py` | 包 | 路由包锚点。 |
| `app/api/routers/admin.py` | API | 管理配置与运维端点。 |
| `app/api/routers/chat.py` | API | 聊天、流式回答和运行发起端点。 |
| `app/api/routers/enterprise.py` | API | 企业数据模拟/Provider 相关端点。 |
| `app/api/routers/knowledge.py` | API | 知识检索与个人知识入口。 |
| `app/api/routers/models.py` | API | 模型配置和健康端点。 |
| `app/api/routers/monitor.py` | API | 监控与审计读取端点。 |
| `app/api/routers/reports.py` | API | 制造报告端点。 |
| `app/api/routers/runtime.py` | API | Agent 运行状态端点。 |
| `app/api/routers/sessions.py` | API/存储 | 会话读取、删除和恢复端点。 |
| `app/api/routers/system.py` | API/存储 | 系统初始化和状态端点。 |
| `app/api/services/__init__.py` | 包 | API 服务包锚点。 |
| `app/api/services/chat.py` | API | 聊天请求编排。 |
| `app/api/services/chat_stream.py` | API | SSE/流式聊天响应。 |
| `app/api/services/history.py` | API/存储 | 会话历史 API 适配。 |
| `app/api/services/personal_job_events.py` | API | 个人知识后台任务事件转换。 |
| `app/bootstrap/__init__.py` | 包 | bootstrap 包锚点。 |
| `app/bootstrap/tool_catalog.py` | 装配 | 旧模型可见工具 Schema 的实际集合和 `SUBMIT_ANALYSIS_TOOL`。 |
| `app/bootstrap/tool_bindings.py` | 装配 | 旧 Handler 到默认 Registry 的实际绑定。 |
| `app/bootstrap/legacy_agent_assembly.py` | 装配/兼容 | 从一次 service globals 快照构建旧 CoordinatorDependencies。 |
| `app/bootstrap/agent_assembly.py` | 装配 | 校验 Definition/Binding/能力并建立 AgentApplication。 |
| `app/bootstrap/agent_demo.py` | 装配 | Fake 模型、Fake/SQLite 设备健康的新 AgentRun 演示。 |
| `app/bootstrap/dispatcher_demo.py` | 装配 | Dispatcher 试点 CLI 的 Fake/计划辅助。 |
| `app/bootstrap/ready_assembly.py` | 装配 | Ready 的 Guard/Dispatcher/结果策略同实例绑定。 |
| `app/bootstrap/ready_demo.py` | 装配 | 确定性 Ready 设备健康 CLI 演示。 |
| `app/bootstrap/loop_assembly.py` | 装配 | Loop 的能力过滤 Schema 与同实例绑定。 |
| `app/bootstrap/loop_demo.py` | 装配 | 两次 Fake 模型响应实际驱动 Loop round 的 CLI 演示。 |
| `app/bootstrap/diagnostics_demo.py` | 装配 | Cpk/传感器的 Ready/Loop、Fake/单库只读 SQLite 演示；实际装配两项原生绑定。 |

### Agent Runtime：协调、准备、综合与兼容

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/agent_runtime/__init__.py` | 包 | Runtime 包锚点。 |
| `app/agent_runtime/assistant_capabilities.py` | 纯 | 助手能力/元响应规则。 |
| `app/agent_runtime/compatibility.py` | 兼容 | 旧 facade、动态导出和 live patch 依赖快照入口。 |
| `app/agent_runtime/contracts.py` | 纯 | 旧 Runtime 的请求、进度与结果契约。 |
| `app/agent_runtime/coordinator.py` | 业务 | Coordinator 主流程与阶段切换。 |
| `app/agent_runtime/coordinator_availability.py` | 兼容 | availability stage 的保留转发入口。 |
| `app/agent_runtime/coordinator_loop.py` | 兼容 | loop stage 的保留转发入口。 |
| `app/agent_runtime/coordinator_model.py` | 兼容 | model stage 的保留转发入口。 |
| `app/agent_runtime/coordinator_prepare.py` | 兼容 | prepare stage 的保留转发入口。 |
| `app/agent_runtime/coordinator_ready.py` | 兼容 | ready stage 的保留转发入口。 |
| `app/agent_runtime/coordinator_state.py` | 业务 | `CoordinatorRunState` 和阶段受限状态视图。 |
| `app/agent_runtime/definition.py` | 纯 | 冻结 `AgentDefinition`、`ComponentReference`。 |
| `app/agent_runtime/application.py` | 纯 | `AgentRun` 对 Model/Tool/Event ports 的小门面。 |
| `app/agent_runtime/dependencies.py` | 装配契约 | 分阶段 CoordinatorDependencies 数据结构。 |
| `app/agent_runtime/service.py` | 兼容/装配 | 默认 `run_agent`、运行生命周期与全局兼容对象。 |
| `app/agent_runtime/telemetry.py` | 业务 | Runtime 事件和审计辅助。 |
| `app/agent_runtime/preparation/__init__.py` | 包 | 准备阶段包锚点。 |
| `app/agent_runtime/preparation/context.py` | 业务 | 问题/历史上下文解析阶段。 |
| `app/agent_runtime/preparation/pipeline.py` | 业务 | 准备阶段串联及依赖对象。 |
| `app/agent_runtime/preparation/planning.py` | 业务 | route/playbook/plan 准备。 |
| `app/agent_runtime/preparation/routing.py` | 业务 | 意图和运行路径准备。 |
| `app/agent_runtime/retrieval/__init__.py` | 包 | 检索阶段包锚点。 |
| `app/agent_runtime/retrieval/general_knowledge.py` | 业务 | 通用知识回退判定与披露。 |
| `app/agent_runtime/stages/__init__.py` | 包 | Coordinator stage 包锚点。 |
| `app/agent_runtime/stages/availability.py` | 业务 | 模型可用性和 Ready 前置阶段。 |
| `app/agent_runtime/stages/loop.py` | 业务/兼容 | 将 CoordinatorRunState 转成旧 AgentLoopContext。 |
| `app/agent_runtime/stages/model.py` | 业务 | Coordinator 结果生成/模型阶段辅助。 |
| `app/agent_runtime/stages/prepare.py` | 业务 | Coordinator 准备阶段。 |
| `app/agent_runtime/stages/ready.py` | 业务 | Ready 执行及 Ready 综合阶段。 |
| `app/agent_runtime/synthesis/__init__.py` | 包 | 综合包锚点。 |
| `app/agent_runtime/synthesis/fallback.py` | 业务 | 模型不可用的本地回答降级。 |
| `app/agent_runtime/synthesis/ready.py` | 业务 | Ready 综合、提交修复和安全降级。 |
| `app/agent_runtime/synthesis/result.py` | 业务 | 对外结果字典建立。 |

### Agent Runtime：执行内核

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/agent_runtime/execution/__init__.py` | 兼容 | 惰性导出旧 loop/ready 名称。 |
| `app/agent_runtime/execution/failure.py` | 纯 | 模型故障重试/回退分类。 |
| `app/agent_runtime/execution/loop_guard.py` | 纯 | `ToolLoopGuard`：预算、重复调用、进展和停止原因。 |
| `app/agent_runtime/execution/agent_loop.py` | 兼容/业务 | 旧模型循环、httpx 生命周期；可显式注入 Loop Dispatcher。 |
| `app/agent_runtime/execution/ready_plan.py` | 兼容/业务 | 原 Ready 回调路径；可显式委托新 Ready executor。 |
| `app/agent_runtime/execution/ready_graph.py` | 纯 | Ready 依赖拓扑排序与非法图拒绝。 |
| `app/agent_runtime/execution/ready_dispatch.py` | 纯 | Dispatcher-backed Ready 执行、归约和事件投影。 |
| `app/agent_runtime/execution/ready_result_policy.py` | 纯 | 知识过滤、截断与 raw 行数侧车。 |
| `app/agent_runtime/execution/loop_response.py` | 纯 | 提供方无关的模型工具/提交响应分类。 |
| `app/agent_runtime/execution/loop_dispatch.py` | 纯 | 单个模型工具轮次的 Dispatcher 执行与归约。 |
| `app/agent_runtime/execution/runtime_contracts.py` | 纯 | RuntimeContext、ModelRequest/Response、事件契约。 |
| `app/agent_runtime/execution/runtime_ports.py` | 纯 | ModelResponsePort、ToolDispatcherPort、EventSink。 |
| `app/agent_runtime/execution/pilot_stages.py` | 纯 | 单模型/工具/事件的最小 Port 消费者。 |
| `app/agent_runtime/execution/tool_budget.py` | 纯 | LoopGuard 到 Dispatcher ToolBudget 的适配器。 |
| `app/agent_runtime/execution/tool_result_bridge.py` | 纯 | ToolResult 到 Trace/EvidenceObservation/事件投影，以实际 Source Scope 保留联合过滤。 |

### Tool 系统

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/agent_runtime/tools/__init__.py` | 兼容 | 工具公共导出与延迟兼容入口。 |
| `app/agent_runtime/tools/contracts.py` | 纯 | ToolResult、错误、Scope、执行上下文和来源契约。 |
| `app/agent_runtime/tools/definition.py` | 纯 | ToolDefinition、ToolBinding、输入输出验证与准备结果。 |
| `app/agent_runtime/tools/tool_registry.py` | 纯 | 单一 Registry、原生/LegacyBindingAdapter 和默认容器。 |
| `app/agent_runtime/tools/dispatch_contracts.py` | 纯 | ToolPolicy、ToolBudget、ToolResultPolicy 契约。 |
| `app/agent_runtime/tools/dispatch_policy.py` | 纯 | Demo 授权 Policy。 |
| `app/agent_runtime/tools/dispatcher.py` | 纯 | JSON 解码、授权、预算、取消/期限、调用和最终采用的权威执行器。 |
| `app/agent_runtime/tools/catalog.py` | 兼容 | bootstrap 工具 Schema 的稳定对象身份视图。 |
| `app/agent_runtime/tools/registry.py` | 兼容 | bootstrap Handler 的 live patch 视图。 |
| `app/agent_runtime/tools/executor.py` | 兼容 | 旧参数解析和 Handler 调用叶节点。 |

### 领域、计划、检索与证据

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/intent_runtime/__init__.py` | 包 | 意图运行包锚点。 |
| `app/intent_runtime/contracts.py` | 纯 | IntentRoute、范围与时间契约。 |
| `app/intent_runtime/rules.py` | 纯 | 启发式意图/工具候选规则。 |
| `app/intent_runtime/routing.py` | 业务 | 规则路由入口。 |
| `app/intent_runtime/scope.py` | 业务 | 制程、设备、产品范围解析。 |
| `app/intent_runtime/time.py` | 业务 | 中文时间表达式和默认时间窗。 |
| `app/planning_runtime/__init__.py` | 包 | 计划运行包锚点。 |
| `app/planning_runtime/contracts.py` | 纯 | ExecutionPlan、PlanStep、PlanBudget。 |
| `app/planning_runtime/service.py` | 业务 | 从 route/playbook 建立 ExecutionPlan。 |
| `app/planning_runtime/steps.py` | 业务/过渡 | 计划步骤、预算、SQL 模板步骤与证据元数据。 |
| `app/planning_runtime/queries.py` | 业务/过渡 | 基于证据模板构造制造 SQL 字符串。 |
| `app/planning_runtime/scope.py` | 业务/过渡 | 从参数/SQL 推导计划范围与语义。 |
| `app/manufacturing/__init__.py` | 包 | 制造领域包锚点。 |
| `app/manufacturing/processes.py` | 纯 | 制程常量与分类。 |
| `app/manufacturing/playbooks.py` | 业务 | DomainPlaybook、证据需求与固定业务规则。 |
| `app/manufacturing/reports.py` | 业务/存储 | 旧 SQLite 制造报告；含 `safe_select(sql)`。 |
| `app/manufacturing/seed.py` | 存储 | 合成 FAB/部门库建模与种子数据。 |
| `app/manufacturing/data_contracts.py` | 纯 | EnterpriseDataProvider 和主体 Protocol。 |
| `app/manufacturing/enterprise_data.py` | 业务/装配 | 合成企业 Provider、注册/选择与报告函数。 |
| `app/manufacturing/equipment_health/__init__.py` | 包 | 设备健康包锚点。 |
| `app/manufacturing/equipment_health/contracts.py` | 纯 | 设备健康输入、聚合、Port 与错误契约。 |
| `app/manufacturing/equipment_health/handler.py` | 纯 | 设备健康用例/范围归一化。 |
| `app/manufacturing/equipment_health/binding.py` | 纯 | 从 Port 建立原生 ToolBinding。 |
| `app/manufacturing/process_diagnostics/__init__.py` | 包 | 过程诊断包锚点，不执行默认注册。 |
| `app/manufacturing/process_diagnostics/contracts.py` | 纯 | 两种输入、冻结 Query、Snapshot、消费方 Port 和完整结果字段/范围校验。 |
| `app/manufacturing/process_diagnostics/handler.py` | 纯 | Cpk/传感器处理器，核对查询、来源 Scope 与行级过滤，生成 ToolResult。 |
| `app/manufacturing/process_diagnostics/binding.py` | 纯 | 两个 ToolDefinition 及显式绑定工厂，注入 today 并冻结有效查询。 |
| `app/integrations/__init__.py` | 包 | 技术集成包锚点。 |
| `app/integrations/manufacturing/__init__.py` | 包 | 制造 Adapter 包锚点。 |
| `app/integrations/manufacturing/fake_equipment_health.py` | Adapter | 内存 FakeEquipmentHealthAdapter。 |
| `app/integrations/manufacturing/sqlite_equipment_health.py` | Adapter | 两个显式只读 SQLite 源的设备健康 Adapter。 |
| `app/integrations/manufacturing/fake_process_diagnostics.py` | Adapter | 精确 DiagnosticsQuery 夹具、租户隔离与快照复制。 |
| `app/integrations/manufacturing/sqlite_process_diagnostics.py` | Adapter | 两条固定参数化报表查询，按工具只开一个相关库，处理只读/期限/关闭及错误脱敏。 |
| `app/knowledge/__init__.py` | 包 | 知识包锚点。 |
| `app/knowledge/decision.py` | 业务 | 检索需求、质量和回退决策。 |
| `app/knowledge/rag.py` | 兼容/装配 | 旧 RAG facade、后端/身份选择和兼容搜索入口。 |
| `app/knowledge/ranking.py` | 纯 | 检索排序/去重规则。 |
| `app/knowledge/search_contracts.py` | 纯 | 工厂搜索、目录和主体 Backend 契约。 |
| `app/knowledge/search_query.py` | 纯 | 查询规范化与过滤。 |
| `app/knowledge/search_registry.py` | 装配/过渡 | 搜索/目录后端注册和选择。 |
| `app/knowledge/sqlite_backend.py` | Adapter | 工厂知识/目录 SQLite 后端。 |
| `app/knowledge/ocr.py` | 业务 | OCR 调用与文本处理。 |
| `app/knowledge/ocr_quality.py` | 纯 | OCR 质量评价规则。 |
| `app/evidence/__init__.py` | 包 | 证据包锚点。 |
| `app/evidence/semantics.py` | 纯/过渡 | 工具结果的证据语义与范围描述；仍识别旧 SQL 工具。 |
| `app/evidence/validator.py` | 业务 | 计划/Playbook 证据覆盖与结论限制。 |
| `app/evidence/answer_synthesizer.py` | 业务 | 证据约束答案结构和渲染。 |
| `app/evidence/serialization.py` | 纯 | 证据/报告的安全序列化。 |

### Memory、会话、模型、存储与可观测性

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/memory_system/__init__.py` | 包 | 当前上下文记忆包锚点。 |
| `app/memory_system/contracts.py` | 纯 | ContextResolution 等上下文契约。 |
| `app/memory_system/ports.py` | 纯 | HistoryReader、ContextModel、Rules、Events、时钟等 Port。 |
| `app/memory_system/service.py` | 业务 | 上下文解析、模型调用和规则回退编排。 |
| `app/memory_system/context/__init__.py` | 包 | Context 子包锚点。 |
| `app/memory_system/context/history.py` | 纯 | 历史消息截取/格式化。 |
| `app/memory_system/context/builder.py` | 纯 | 上下文系统消息和阶段消息构建。 |
| `app/memory_system/context/protocol.py` | 纯 | Context 模型 JSON 协议、错误和修复提示。 |
| `app/memory_system/context/resolver.py` | 业务 | 解析上下文、预算和模型回退。 |
| `app/conversation/__init__.py` | 包 | 会话包锚点。 |
| `app/conversation/decision_arbiter.py` | 业务/过渡 | 单次会话决策权和 active flow 恢复。 |
| `app/conversation/context_resolver.py` | 兼容 | 旧上下文解析导出。 |
| `app/conversation/sessions.py` | 业务/存储 | 会话 CRUD、历史、执行记录直接组合。 |
| `app/conversation/turn_decision.py` | 纯 | 单轮决定数据结构。 |
| `app/model_gateway/__init__.py` | 包 | 模型网关包锚点。 |
| `app/model_gateway/compatibility.py` | 兼容/过渡 | 旧模型协议/上下文兼容层。 |
| `app/model_gateway/registry.py` | 装配/存储 | 模型 Provider 配置、选择和持久化读取。 |
| `app/model_gateway/health.py` | 业务/存储 | 模型熔断健康记录。 |
| `app/model_gateway/streaming.py` | Adapter | SSE 请求、响应拼装、流式审计。 |
| `app/core/__init__.py` | 包 | 核心包锚点。 |
| `app/core/settings.py` | 装配 | 环境设置和默认运行配置。 |
| `app/core/identity.py` | Adapter/过渡 | 当前身份解析和 SQLite/请求绑定。 |
| `app/core/identity_contracts.py` | 纯 | Identity claims 与演示 Header 解析契约。 |
| `app/persistence/__init__.py` | 包 | 存储包锚点。 |
| `app/persistence/database.py` | 存储/过渡 | SQLite 连接、初始化、部门库挂载与建表。 |
| `app/persistence/department_schemas.py` | 纯 | 部门数据库 schema 定义。 |
| `app/persistence/execution_store.py` | 存储/过渡 | 计划、步骤、事件和中断状态记录；尚非安全恢复协议。 |
| `app/telemetry/__init__.py` | 包 | 可观测包锚点。 |
| `app/telemetry/audit.py` | 存储 | JSONL 审计、内容指纹和运行日志。 |
| `app/telemetry/http.py` | API | HTTP 请求/响应观测。 |
| `app/telemetry/runtime_status.py` | 业务/存储 | 运行状态与 SQLite/身份查询。 |

### 个人知识与前端静态文件

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/personal_knowledge_runtime/__init__.py` | 包 | 个人知识运行包锚点。 |
| `app/personal_knowledge_runtime/contracts.py` | 纯 | 文档、任务和检索 DTO。 |
| `app/personal_knowledge_runtime/documents.py` | 存储 | 文档元数据与内容读取。 |
| `app/personal_knowledge_runtime/metadata.py` | 存储 | 元数据校验与更新。 |
| `app/personal_knowledge_runtime/storage.py` | 存储 | 文件存储布局和安全路径处理。 |
| `app/personal_knowledge_runtime/ingestion.py` | 业务/存储 | 上传、抽取与入库流程。 |
| `app/personal_knowledge_runtime/jobs.py` | 业务/存储 | 异步任务状态和调度。 |
| `app/personal_knowledge_runtime/search.py` | 业务/存储 | 个人知识索引和检索。 |
| `app/personal_knowledge_runtime/service.py` | 业务/过渡 | 个人知识用例与审计/数据库组合。 |
| `app/personal_knowledge_runtime/extractors/__init__.py` | 包 | 抽取器包锚点。 |
| `app/personal_knowledge_runtime/extractors/text.py` | Adapter | 纯文本抽取。 |
| `app/personal_knowledge_runtime/extractors/pdf.py` | Adapter | PDF 抽取。 |
| `app/personal_knowledge_runtime/extractors/office.py` | Adapter | Office 文档抽取。 |
| `app/personal_knowledge_runtime/extractors/image.py` | Adapter | 图像/OCR 抽取。 |
| `app/static/index.html` | 前端 | 聊天主界面 DOM。 |
| `app/static/styles.css` | 前端 | 主界面样式。 |
| `app/static/app.js` | 前端/兼容 | 旧主界面启动与工具文案。 |
| `app/static/admin.html` | 前端 | 管理界面 DOM。 |
| `app/static/admin.css` | 前端 | 管理界面样式。 |
| `app/static/admin.js` | 前端 | 管理界面控制器。 |
| `app/static/app/bootstrap.js` | 前端 | 模块化前端启动和控制器装配。 |
| `app/static/app/core/api.js` | 前端 | HTTP/SSE API 客户端。 |
| `app/static/app/core/dom.js` | 前端 | DOM 查询/渲染辅助。 |
| `app/static/app/core/state.js` | 前端 | 页面状态容器。 |
| `app/static/app/core/toast.js` | 前端 | 通知组件。 |
| `app/static/app/core/version.js` | 前端 | 静态版本信息。 |
| `app/static/app/chat/controller.js` | 前端 | 聊天交互控制。 |
| `app/static/app/chat/presenter.js` | 前端 | 聊天消息呈现。 |
| `app/static/app/dashboard/controller.js` | 前端 | 仪表盘控制。 |
| `app/static/app/knowledge/controller.js` | 前端 | 知识上传/搜索控制。 |
| `app/static/app/layout/controller.js` | 前端 | 页面布局与导航控制。 |
| `app/static/app/model/controller.js` | 前端 | 模型设置控制。 |
| `app/static/app/sessions/controller.js` | 前端 | 会话列表控制。 |
| `app/static/model_capabilities.js` | 前端 | 模型能力显示。 |
| `app/static/personal_job_events.js` | 前端 | 个人知识任务事件消费。 |
| `app/static/personal_knowledge_metadata.js` | 前端 | 个人知识元数据 UI。 |
| `app/static/personal_upload_queue.js` | 前端 | 上传队列 UI。 |
| `app/static/source_presenter.js` | 前端 | 引用/来源展示。 |
| `app/static/stream_buffer.js` | 前端 | 流式文本缓冲。 |
| `app/static/stream_diagnostics.js` | 前端 | SSE 诊断显示。 |
| `app/static/stream_markdown.js` | 前端 | 流式 Markdown 渲染。 |
| `app/static/thinking_control.js` | 前端 | 推理模式开关。 |

## 4. Memory、Skill、Checkpoint 的实际状态

已实现的是**当前任务上下文记忆**：`memory_system` 包含上下文解析、历史截取、消息构建、
模型协议和可替换 Port；`conversation.sessions` 仍管理持久会话历史。知识库、案例和个人知识
检索是检索数据，不是自动沉淀的长期 Agent Memory。

尚未实现独立的 Skill Catalog/Discovery/Loader/版本发布；`manufacturing.playbooks` 是现有业务
规则与证据计划，不能等同 Skill。`persistence.execution_store` 已保存运行记录，但尚未提供
可安全重放的 Checkpoint/恢复协议。长期记忆仍是 OPTIONAL，未启用；因此不存在已完成的
语义/情景/程序三层长期记忆实现。

## 5. 当前耦合与迁移事实

边界清单记录 **28 条精确依赖债务、21 个 DB 调用候选文件、13 个兼容入口、85 个静态消费者**。
兼容消费者扫描只覆盖 app/scripts/tests 内的静态 import、字面动态 import 与常见 mock patch；
外部调用方和计算出的动态引用仍需人工审查。

28 条债务的实际来源可归纳为：

- `app/agent_runtime/compatibility.py` 仍直接装配 manufacturing 与 legacy bootstrap（3 条，MOD-015）。
- `app/agent_runtime/tools/catalog.py` 与 `registry.py` 仍反向看 bootstrap（2 条，分别至 MOD-015/MOD-008）。
- `app/conversation/decision_arbiter.py` 仍直接引用 `memory_system.contracts`（1 条，MOD-015）。
- `app/conversation/sessions.py`、`app/knowledge/rag.py`/`search_registry.py`、`enterprise_data.py`/`reports.py` 仍直接接身份或 SQLite（9 条，MOD-008/015）。
- `app/evidence/validator.py` 仍接 Playbook/Plan 实现（2 条，MOD-015）。
- `app/model_gateway` 与 `app/persistence` 仍互相涉及配置、身份、记忆或数据库（7 条，MOD-012/015）。
- 个人知识和 telemetry 仍直接接审计/身份/SQLite（4 条，MOD-015）。

21 个 DB 候选是 `api/application.py`、`api/routers/admin.py`、`api/routers/system.py`、
`api/runtime_dependencies.py`、`conversation/sessions.py`、SQLite 设备 Adapter、新过程诊断 SQLite Adapter、知识 SQLite 后端、
`main.py`、`manufacturing/reports.py`、`manufacturing/seed.py`、模型 health/registry、
`persistence/database.py`、`persistence/execution_store.py`、个人知识的 documents/ingestion/jobs/search/service，
以及 `telemetry/runtime_status.py`。它们并不都是公司业务数据库：其中很多是应用自有会话、
索引、审计或合成 FAB 数据。

最重要的未退出能力是旧 SQL：`planning_runtime/queries.py` 生成 SQL 模板，`steps.py` 把它写为
`query_manufacturing_data` 的计划参数，`scope.py`/`evidence.semantics.py` 仍解析其语义，
`bootstrap.tool_catalog.py` 全局暴露该工具，`bootstrap.tool_bindings.py` 把它绑定到
`manufacturing.reports.safe_select(sql)`。它当前仍是默认旧路径的一部分。MOD-008 首批只迁移
两个原生工具；默认模型 SQL 退出仍待后续批次，不能声称全局模型无 SQL 或工具层已全部解耦。

## 6. 可搬迁范围与尚不可独立搬迁部分

已经有七个较小源码单元：`memory_core`、`decision_core`、`model_transport`、
`enterprise_data_contract`、`retrieval_policy`、`factory_search_contract`、`identity_contract`；
它们的文件清单在 `evaluations/portable_units_v1.json`，用于契约/规则级仓库外验证。

另有旧 **37 文件** `dispatcher_pilot` 真 venv 安装清单，版本固定为 1.0.0；其用途是保持
MOD-007 的安装回归，并不自动包含后续源码。MOD-013 的 Ready 证明使用 49 文件源码切片；
MOD-014 的 Loop round 已验证 **53 文件**（37 + 3 runtime ports + 4 Agent 装配 + 5 Ready +
4 Loop）。MOD-008 首批在此基础上增加七个真实文件，形成 **60 文件**源码切片；以 -I -S、
空环境、无关 cwd 和持续网络/SQLite/配置/旧模块守卫实际执行 Fake Ready/Loop。
这些都是源码切片或试点制品，不是可与整个应用任意组合安装的正式 Wheel。

只读 SQLite 的两工具/两路径数值与 Scope 对照在显式临时库上另行验证。公司账号、公司
数据库方言或报表 API Adapter 尚未接入；迁入时复用工具与 Data Port，具体来源适配另验收。

在 WSL 仓库根目录、既有 Python 环境可查看首批效果（Fake，无真实模型或网络请求）：

```bash
python -m app.bootstrap.diagnostics_demo --mode ready --tool get_process_capability --arguments '{"process_step":"CMP"}'
python -m app.bootstrap.diagnostics_demo --mode loop --tool get_sensor_summary --arguments '{"process_step":"CMP","equipment_id":"CMP-01","signal_name":"pressure"}'
```

Loop 的模型响应由固定 Fake Port 提供；输出包含实际结果、Source Scope、TOOL 引用与同一
Guard 的计数。工具版本均为 1.0.0；首批没有改变默认全局 TOOLS/TOOL_HANDLERS。

当前不能独立搬迁的部分包括：默认 HTTP/API 应用、旧 service/coordinator 链、默认 Loop 的
httpx/Provider 生命周期、完整旧工具集合/SQL 入口、会话与个人知识的 SQLite 组合、模型健康
存储、RAG 后端选择，以及前端与 API 的整体装配。企业内网迁移应只把已验收切片与明确 Adapter
接口先行带入，不能把该工作树视为所有模块已独立部署。

## 7. 读取本快照的限制

本文件是实际目录与责任地图。MOD-014 的最终 217 项必要定向、3 项旧故障回退系统回归与
修订后预声明 r2 正式性能/独立审计通过，r1 证据保留。MOD-008 首批的 281 项必要回归、
60 文件隔离、旧安装/源码闭包/冻结行为/守卫通过；整个 MOD-008 仍进行中。此后变化须随
工作树重新核对。文档为 UTF-8/LF，源码表不展开测试、日志、runtime 产物或工作簿内容。
