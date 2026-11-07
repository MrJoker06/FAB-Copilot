# 当前项目精细结构快照

快照日期：2026-11-06。依据为 experiment/parallel-platform 的 `6dd6544` 基线及本轮 MOD-009 改造。MOD-008/009、跨平台启动和 MOD-016～019 已验收，历史失败保留；下一项 MOD-012，随后 015。Skill 加载与发布保持显式可选；新增来源装配和扩展工具复用原 Ready/Loop，默认 HTTP 与 21 项工具清单未改。验收证据以对应报告为准，提交与远程状态以 Git 记录为准。

本次实扫 `app/` 的受管源码为 **282 文件：254 个 Python、28 个静态文件**（2026-11-07 MOD-015d 后复扫；015a 删除 6 个转发模块，015b 新增 `agent_runtime/ports.py`，015c 新增 6 个 Loop 模块，015d 新增 2 个 core 模块和 1 个 bootstrap 模块）。数量与
`evaluations/mod_003_boundaries_v1.json` 一致；测试、日志、缓存和运行期生成物不计入。

## 平台启动入口

根目录 `run.py` 统一处理启动检查、源码快照、隔离实例与子进程生命周期；`run.bat`
直接运行原生 Windows Python，`run.sh` 用于 Linux / WSL，支持各自 venv 和既有 Conda。
`scripts/instance_lock.py` 提供平台锁，`scripts/manage_runtime.py` 维护安全的实例检查/
清理。以上均在 `app/` 之外。MOD-016 之前应用源码为 258 文件，016/017 累计新增九个 Skill 文件，018 另增三个 bootstrap 和一个 evidence 文件，019 再增一个 releases 模块；009 新增两个来源装配/演示文件和一个可选设备健康汇总。四个光刻 Skill 文本资产另计。启动入口不计入应用源码统计。
启动方式见 [README](../README.md#快速启动)，实际验证见 [跨平台启动报告](reports/cross-platform-startup.md)。

## 1. 当前物理树与逻辑边界

```text
app/
├── main.py                         HTTP 启动与应用组合
├── api/                            HTTP 路由、请求模型、流式聊天服务
├── bootstrap/                      显式装配与旧绑定组合的过渡区
├── agent_runtime/                 协调器、执行、工具、综合与兼容入口
├── planning_runtime/              Router 输入后的 Plan/步骤生成
├── intent_runtime/                规则路由、时间与范围解析
├── manufacturing/                 Playbook、旧报告及六组业务工具的纯契约与处理器
├── integrations/manufacturing/    Fake/只读 SQLite/显式企业 Provider Adapter
├── knowledge/                     RAG、纯知识工具、检索决策/规则/契约与旧 SQLite 后端
├── integrations/knowledge/        精确 Fake 与显式工厂/个人搜索后端 Adapter
├── evidence/                      证据描述、校验、答案综合和序列化
├── skills/                        清单/资源、Catalog/渐进加载、不可变发布与版本状态
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

### 当前默认应用链（F2b 已验证）

```text
HTTP app.main / api
  → agent_runtime.service.run_agent
  → compatibility 的 live namespace → bootstrap.default_coordinator_assembly
  → v2 Playbook / named_planner → schema 1.2 Plan
  → bootstrap.default_tool_assembly：业务运行 21 项；通识运行仅知识检索
  → coordinator / stages.prepare / availability / ready / loop
  → Ready / Loop / 知识预取 / 必要的无模型降级 → 同一 Dispatcher 与 Guard
  → ToolBinding → 消费方 Data Port → 按需构造的来源 Adapter
  → 相关只读 SQLite / 企业 Provider / 工厂和个人知识后端
  → evidence.validator / answer_synthesizer → 流式回答与审计
```

默认模型清单是 21 项业务工具加独立的 `submit_analysis` 协议。默认执行不接受
`query_manufacturing_data`，提示不再暴露数据库字段目录。13 项旧 kwargs 函数只保留
受信 Python 调用方的实时 patch 兼容桥，替换时以 `legacy-v1` 标记；未替换时解析为原生绑定。

模型访问经 `ModelGatewayPort`（`app/model_gateway/gateway.py`）：网关负责 HTTP 客户端开关、URL、
凭据头和聊天模板整形，`agent_loop.py` 只保留重试、健康记录和本地回退（MOD-012）。

### 新的显式试点链（MOD-011～014 的受控分支）

```text
AgentDefinition + bootstrap.agent_assembly
  → AgentApplication.new_run → AgentRun
  → RuntimeContext + 本地 ToolRegistry + ToolDispatcher
  → Ready: bind_ready_run → execute_dispatched_ready_plan
       或 Loop: bind_loop_run → classify_loop_response → execute_dispatched_loop_round
  → ToolBinding → EquipmentHealthPort / ProcessDiagnosticsPort
                    / ProductionReportsPort / OperationalReportsPort / EnterpriseDataPort
                    / KnowledgeSearchPort / NamedQueryPort
   → 各自的 Fake、只读 SQLite、企业 Provider 或工厂/个人搜索后端 Adapter
  → ToolResult / Scope / Source → tool_result_bridge → EvidenceObservation
```

这一链覆盖设备健康、Cpk、传感器，第二批总览/良率趋势/制程通过率，以及第三批生产率/
缺陷 Pareto/最近异常的显式绑定；第四批企业目录/汇总/样本绑定也已验证。另保留
经明确许可的 legacy 适配。各批验收状态分别记录；它并未把所有旧工具、所有数据源、
HTTP 生命周期或会话存储迁入新装配。MOD-018 通过显式 Skill 配置复用这条试点链，默认 HTTP 不自动启用。

第五批联合检索的显式绑定已验收。工厂/案例和个人知识通过数据 Port 组合，
旧 RAG facade 为历史直接调用保留设置、身份与后端选择；默认工具改由 bootstrap 注入。
这些工作不迁移知识上传、
目录管理、个人索引写入或检索失败后的整体回答策略。

第六批 F1 的八条旧 Planner 固定 SQL 具名替代工具已验收。产品/设备查询声明实际
日期与联合过滤，批次五工具保留全历史、日期 Scope 为空。F2a 新增显式版本化消费入口：
`select_named_playbook(route)` → `create_named_execution_plan(question, route, selection)`，
由六类 v2 Playbook 生成具名调用，再接现有原生绑定和 Ready/Loop；476 项必要回归和
12 路独立功能核验通过，包含完整批次计划与日期型证据子计划，详见 MOD-008 报告。
旧 `select_playbook` / `create_execution_plan` 保留 v1 显式历史入口。F2b 已将默认消费链
接到 v2，并从默认清单和执行绑定移除 SQL 能力；功能、拒绝路径、完整质量门与独立性能
比较的实际结果见报告。仍保留的历史 SQL 模板与内部 `safe_select` 不应注册到默认模型链。

### MOD-009：显式批量来源替换

`ToolSources → create_tool_bindings → AgentApplication → Ready/Loop → Dispatcher → 原 Handler → Data Port`。七类 Port 按显式配置选入；替换来源不改核心工具或 Runtime。完整 21 项工具已在 Fake 与 17 SQLite / 3 Provider / 1 Backend 两组来源通过双路径；企业与知识工具的外部接入仍使用内存夹具并标为 FAKE。可选 `get_equipment_health_summary` 只在显式注册时加入，复用原设备健康分类和 Scope；默认 21 项清单未变。见 [报告](reports/mod-009-tool-sources.md)。

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
| `tests/`、`logs/`、缓存与 node_modules | 验证、日志和生成依赖；本说明不逐文件展开，不计入 272 源码文件。 |
| `fab_litho_agent_gantt_boss.xlsx` | 用户的规划参考资产，不是运行时依赖。 |

### 关键接口与状态归属

| 边界 | 当前接口与职责 |
| --- | --- |
| Runtime → 模型 | ModelResponsePort.complete(ModelRequest, RuntimeContext) → ModelResponse；默认 Loop/Ready/Context 经 ModelGatewayPort.open(endpoint) → ModelSessionPort.stream(payload, progress, state)。 |
| Runtime → 工具 | ToolDispatcherPort.dispatch(name, raw_arguments, ToolExecutionContext) → ToolResult；真实 Dispatcher 管输入、能力/Scope、期限/取消和唯一记账。 |
| 工具 → 业务数据 | EquipmentHealthPort / ProcessDiagnosticsPort / ProductionReportsPort / OperationalReportsPort / EnterpriseDataPort / KnowledgeSearchPort / NamedQueryPort 的 fetch(query, principal) → Snapshot；输入是固定业务查询，SQL 不进入新增原生模型参数。 |
| Adapter → 来源 | Fake 精确夹具或显式只读 SQLite。生产报表、capability 和 excursions 只用制造库；sensors/productivity 只用设备库，defects 只用质量库；不附挂其余数据库。设备健康保留自身获验收的显式双库读取。 |
| 企业来源接缝 | EnterpriseDataPort 接入精确 Fake 或显式注入的 EnterpriseDataProvider Protocol Adapter；EnterpriseWindow 固定 as_of/保留期/汇总默认窗口。演示 Provider 是内存夹具，真实只读账号或报表 API 尚未接入。 |
| 知识来源接缝 | KnowledgeSearchPort 组合工厂搜索 Protocol 与个人搜索 Port；owner 由可信 tenant/user/default-tenant 配置决定。Scope 仅声明租户/检索粒度，设备等参数是重排焦点，不能当作 ACL。 |
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
| `app/bootstrap/tool_catalog.py` | 装配/兼容 | 默认 21 项原生 Schema 加 `SUBMIT_ANALYSIS_TOOL`，保持全局列表身份；另保存显式历史回放的 `LEGACY_TOOLS`。 |
| `app/bootstrap/tool_sources.py` | 装配 | 七类消费方 Port 的显式可选组合，复用原生绑定工厂；不发现配置、不读取来源，支持可选查询注册。 |
| `app/bootstrap/tool_sources_demo.py` | 装配 | 统一来源演示及实际 Ready/两阶段 Fake Loop，显式 Fake 或 SQLite/Provider/Backend 夹具，输出完整 Scope/错误/Guard。 |
| `app/bootstrap/tool_definitions.py` | 纯 | 默认能力版本与 21 项原生 ToolDefinition 的唯一清单；不创建来源或执行器。 |
| `app/bootstrap/tool_bindings.py` | 装配/兼容 | 13 项非 SQL kwargs Handler 的全局兼容绑定；保留 Python 导出，不注册旧 SQL 工具。 |
| `app/bootstrap/default_coordinator_assembly.py` | 装配 | 从 live namespace 构造默认协调器依赖，注入 v2 规划、每次运行的工具装配及受控原生离线降级；导入时安装默认存储/身份绑定，直接调用 `run_agent` 也可用。 |
| `app/bootstrap/default_tool_assembly.py` | 装配 | 业务运行组合 21 项原生绑定，通识仅授权知识检索；组合延迟来源、可信身份 Policy、同一 Guard 和结果策略。未暴露目录时使用不可变 Schema 快照；公开访问后的可变清单按运行独立物化，后续绑定反映实际修改。 |
| `app/bootstrap/legacy_agent_assembly.py` | 装配/兼容 | 从一次 service globals 快照构建旧 CoordinatorDependencies。 |
| `app/bootstrap/storage_identity_assembly.py` | 装配 | 存储/身份 Port 的默认绑定：调用时读取 database、identity、audit、execution_store 和 SQLite 检索后端的模块属性；`install_default_storage_identity()` 可重复调用，不覆盖自定义绑定。 |
| `app/bootstrap/agent_assembly.py` | 装配 | 校验 Definition/Binding/能力并建立 AgentApplication；非空 skill_refs 必须显式配置，未启用路径保持兼容。 |
| `app/bootstrap/skill_assembly.py` | 装配 | 根据实际绑定校验 Skill，连接文件目录或显式发布对象；新 Run 前检查声明或发布准入，将固定文本和基础元数据交给 Runtime。 |
| `app/bootstrap/litho_cpk_workflow.py` | 装配 | 固定光刻 Workflow 与证据策略引用，复用现有 v2 Playbook/Planner，不复制业务步骤。 |
| `app/bootstrap/litho_cpk_demo.py` | 装配 | 显式 Skill Ready/Fake Loop 演示，使用原生工具、同一 Dispatcher/Guard 与精确 Fake 来源。 |
| `app/bootstrap/agent_demo.py` | 装配 | Fake 模型、Fake/SQLite 设备健康的新 AgentRun 演示。 |
| `app/bootstrap/dispatcher_demo.py` | 装配 | Dispatcher 试点 CLI 的 Fake/计划辅助。 |
| `app/bootstrap/ready_assembly.py` | 装配 | Ready 的 Guard/Dispatcher/结果策略同实例绑定。 |
| `app/bootstrap/ready_demo.py` | 装配 | 确定性 Ready 设备健康 CLI 演示。 |
| `app/bootstrap/loop_assembly.py` | 装配 | Loop 能力过滤与同实例绑定；验证不可变 Schema 快照，兼容没有快照接口的 Registry。 |
| `app/bootstrap/loop_demo.py` | 装配 | 两次 Fake 模型响应实际驱动 Loop round 的 CLI 演示。 |
| `app/bootstrap/diagnostics_demo.py` | 装配 | Cpk/传感器的 Ready/Loop、Fake/单库只读 SQLite 演示；实际装配两项原生绑定。 |
| `app/bootstrap/production_reports_demo.py` | 装配 | 总览、周良率和制程通过率的 Ready/Loop 演示；本地绑定三项工具、Fake 模型与显式数据来源。 |
| `app/bootstrap/operational_reports_demo.py` | 装配 | 生产率、Pareto 与最近异常的 Ready/Loop 演示；按工具只绑定所需数据路径。 |
| `app/bootstrap/enterprise_tools_demo.py` | 装配 | 企业目录、汇总与样本的 Ready/Loop 演示；显式选择 Fake 或内存夹具 Provider，不接真实公司来源。 |
| `app/bootstrap/knowledge_search_demo.py` | 装配 | 联合个人/工厂/案例检索的 Ready/Loop 演示；显式 Fake 或内存搜索后端和当前用户策略。 |
| `app/bootstrap/named_queries_demo.py` | 装配 | 八项具名制造查询的 Ready/Loop 演示；显式 Fake 或单次读取相关一库的只读 SQLite。 |

### Agent Runtime：协调、准备、综合与兼容

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/agent_runtime/__init__.py` | 包 | Runtime 包锚点。 |
| `app/agent_runtime/assistant_capabilities.py` | 纯 | 助手能力/元响应规则。 |
| `app/agent_runtime/compatibility.py` | 兼容 | 旧 facade、动态导出和 live patch 依赖快照入口。 |
| `app/agent_runtime/contracts.py` | 纯 | 旧 Runtime 的请求、进度与结果契约。 |
| `app/agent_runtime/coordinator.py` | 业务 | Coordinator 主流程与阶段切换。 |
| `app/agent_runtime/coordinator_state.py` | 业务 | `CoordinatorRunState` 和阶段受限状态视图。 |
| `app/agent_runtime/definition.py` | 纯 | 冻结 `AgentDefinition`、`ComponentReference`。 |
| `app/agent_runtime/application.py` | 纯 | `AgentRun` 对 Model/Tool/Event ports 的小门面；可携带装配层传入的 Skill 文本消息与基础元数据，自身不依赖 Skill/业务模块。 |
| `app/agent_runtime/dependencies.py` | 装配契约 | 分阶段 CoordinatorDependencies 与类型字段名缓存；依赖值、回调仍按当前运行读取。 |
| `app/agent_runtime/ports.py` | 纯 | 依赖组、运行状态与事件通道的结构化 Protocol/Callable 端口（含 `RuntimeSettings`/`RuntimeModelConnection` 配置视图、`ToolRunBindings`）；领域类型仅类型检查时导入，运行时只加载标准库。 |
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
| `app/agent_runtime/execution/agent_loop.py` | 兼容/业务 | `AgentLoopContext` 与 `run_agent_loop` 短编排（MOD-015c）：校验 Loop Dispatcher 绑定，经注入的 ModelGatewayPort 打开会话，逐轮委托请求构建、模型调用、答案收尾、工具轮和轮末校验。 |
| `app/agent_runtime/execution/loop_state.py` | 纯 | `LoopRunState`：一次 Run 内可变事实的唯一持有者；`sync_to_context` 唯一回写点、结果构建、用量累计。 |
| `app/agent_runtime/execution/loop_request.py` | 业务 | 每轮仅综合门、阶段进度与模型请求 payload（tools/tool_choice/max_tokens）。 |
| `app/agent_runtime/execution/loop_model_call.py` | 业务 | 模型调用重试、健康失败/恢复记录、本地回退（native 或离线），返回 `ModelTurn`。 |
| `app/agent_runtime/execution/loop_answer.py` | 业务 | 文本答案、`submit_analysis` 纠正/salvage/降级与轮次上限终止。 |
| `app/agent_runtime/execution/loop_tool_round.py` | 业务 | Dispatcher 工具轮与旧注册工具轮（守卫、blocked/ok/error、知识过滤、证据观测）。 |
| `app/agent_runtime/execution/loop_round_validation.py` | 业务 | 轮末证据校验、答案契约刷新、知识回退公告与守卫轮次审计。 |
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
| `app/planning_runtime/named_planner.py` | 纯/版本化业务 | 默认 v2 规划入口；核对路由和声明 Playbook，生成 schema 1.2 / planner 2.0.0 计划，拒绝 SQL 步骤。 |
| `app/planning_runtime/steps.py` | 业务/过渡 | 新旧版本共享的步骤、预算及证据元数据；具名批次不附加日期，旧 SQL 模板步骤待退役。 |
| `app/planning_runtime/queries.py` | 业务/过渡 | 新工具结构化参数及来源构造；仍保留旧版本制造 SQL 模板。 |
| `app/planning_runtime/scope.py` | 业务/过渡 | 具名工具参数的范围/语义映射，以及旧参数/SQL 兼容推导。 |
| `app/manufacturing/__init__.py` | 包 | 制造领域包锚点。 |
| `app/manufacturing/processes.py` | 纯 | 制程常量与分类。 |
| `app/manufacturing/playbooks.py` | 业务 | DomainPlaybook、证据需求与固定业务规则。 |
| `app/manufacturing/named_playbooks.py` | 纯/版本化业务 | 六类 v2 Playbook 和选择器；保留证据要求，仅把固定 SQL 能力替换为八项具名工具。 |
| `app/manufacturing/reports.py` | 业务/存储 | 旧 SQLite 制造报告；含 `safe_select(sql)`。 |
| `app/manufacturing/seed.py` | 存储 | 合成 FAB/部门库建模与种子数据。 |
| `app/manufacturing/data_contracts.py` | 纯 | EnterpriseDataProvider 和主体 Protocol。 |
| `app/manufacturing/enterprise_data.py` | 业务/装配 | 合成企业 Provider、注册/选择与报告函数。 |
| `app/manufacturing/equipment_health/__init__.py` | 包 | 设备健康包锚点。 |
| `app/manufacturing/equipment_health/contracts.py` | 纯 | 设备健康输入、聚合、Port 与错误契约。 |
| `app/manufacturing/equipment_health/handler.py` | 纯 | 设备健康用例/范围归一化。 |
| `app/manufacturing/equipment_health/binding.py` | 纯 | 从 Port 建立原生 ToolBinding。 |
| `app/manufacturing/equipment_health/summary.py` | 纯 | 可选设备健康汇总 ToolDefinition/Handler/Binding，复用原等级计算与来源，不改执行器或默认清单。 |
| `app/manufacturing/process_diagnostics/__init__.py` | 包 | 过程诊断包锚点，不执行默认注册。 |
| `app/manufacturing/process_diagnostics/contracts.py` | 纯 | 两种输入、冻结 Query、Snapshot、消费方 Port 和完整结果字段/范围校验。 |
| `app/manufacturing/process_diagnostics/handler.py` | 纯 | Cpk/传感器处理器，核对查询、来源 Scope 与行级过滤，生成 ToolResult。 |
| `app/manufacturing/process_diagnostics/binding.py` | 纯 | 两个 ToolDefinition 及显式绑定工厂，注入 today 并冻结有效查询。 |
| `app/manufacturing/production_reports/__init__.py` | 包 | 生产报表包锚点，无默认注册副作用。 |
| `app/manufacturing/production_reports/contracts.py` | 纯 | 三种结构化输入、固定 Query/Snapshot、消费方 Port、错误与结果字段契约。 |
| `app/manufacturing/production_reports/handler.py` | 纯 | 调用 Port、核对查询和实际范围，生成对象或列表形式的 ToolResult；不执行 SQL。 |
| `app/manufacturing/production_reports/binding.py` | 纯 | 三个 1.0.0 Definition/Binding 工厂；冻结日期和有效过滤条件。 |
| `app/manufacturing/operational_reports/__init__.py` | 包 | 运行报表包锚点，无默认注册副作用。 |
| `app/manufacturing/operational_reports/contracts.py` | 纯 | 三项业务输入、固定 Query/Snapshot、消费方 Port、有效范围与输出契约；不接受自由 SQL。 |
| `app/manufacturing/operational_reports/handler.py` | 纯 | 核对来源与行级范围，区分生产率设备优先和异常联合筛选，产生 ToolResult。 |
| `app/manufacturing/operational_reports/binding.py` | 纯 | 三个 1.0.0 Definition/Binding，准备实际日期、过滤条件和 limit 后再授权执行。 |
| `app/manufacturing/enterprise_tools/__init__.py` | 包 | 企业工具包锚点，无默认注册副作用。 |
| `app/manufacturing/enterprise_tools/contracts.py` | 纯 | 三项输入、可信时间窗口、固定 Query/Snapshot、消费方 EnterpriseDataPort 与完整业务结果校验。 |
| `app/manufacturing/enterprise_tools/handler.py` | 纯 | 核对查询、租户、实际范围、模拟标记与记录，保留统计和样本口径，生成对象 ToolResult。 |
| `app/manufacturing/enterprise_tools/binding.py` | 纯 | 三个 1.0.0 Definition/Binding 工厂；注入固定时间窗口，按有效 Scope 准备授权。 |
| `app/manufacturing/named_queries/__init__.py` | 包 | 固定具名制造查询包锚点，无默认注册副作用。 |
| `app/manufacturing/named_queries/contracts.py` | 纯 | 四类封闭输入、八种内部 Query、Snapshot/消费方 Port、完整列集和数值/时间契约；模型不能指定 SQL 或 kind。 |
| `app/manufacturing/named_queries/handler.py` | 纯 | 核对查询、来源及实际行范围，保留批次全历史、列表结果和原投影，不在核心聚合或构造 SQL。 |
| `app/manufacturing/named_queries/binding.py` | 纯 | 八个未注册 1.0.0 定义及固定 kind 绑定工厂；冻结 as_of、准备日期或批次 Scope。 |
| `app/integrations/__init__.py` | 包 | 技术集成包锚点。 |
| `app/integrations/manufacturing/__init__.py` | 包 | 制造 Adapter 包锚点。 |
| `app/integrations/manufacturing/fake_equipment_health.py` | Adapter | 内存 FakeEquipmentHealthAdapter。 |
| `app/integrations/manufacturing/sqlite_equipment_health.py` | Adapter | 两个显式只读 SQLite 源的设备健康 Adapter。 |
| `app/integrations/manufacturing/fake_process_diagnostics.py` | Adapter | 精确 DiagnosticsQuery 夹具、租户隔离与快照复制。 |
| `app/integrations/manufacturing/sqlite_process_diagnostics.py` | Adapter | 两条固定参数化报表查询，按工具只开一个相关库，处理只读/期限/关闭及错误脱敏。 |
| `app/integrations/manufacturing/fake_production_reports.py` | Adapter | 精确生产查询夹具、租户核对与返回值复制，来源明确标记 FAKE。 |
| `app/integrations/manufacturing/sqlite_production_reports.py` | Adapter | 三类固定参数化生产报表，只访问显式制造库；只读、超时、连接释放和公开错误脱敏。 |
| `app/integrations/manufacturing/fake_operational_reports.py` | Adapter | 运行报表的精确 Query 夹具、租户核对和独立复制结果；无隐式来源回退。 |
| `app/integrations/manufacturing/sqlite_operational_reports.py` | Adapter | 固定生产率/Pareto/异常 SQL；每次只开一个相关设备/质量/制造库，保持窗口分母、舍入和过滤口径。 |
| `app/integrations/manufacturing/fake_enterprise_tools.py` | Adapter | 按完整企业 Query 返回深复制的精确夹具，核对租户并明确标记 FAKE。 |
| `app/integrations/manufacturing/provider_enterprise_tools.py` | Adapter | 固定调用注入的 EnterpriseDataProvider，核对来源头部、脱敏错误；不使用全局选择或故障回退。 |
| `app/integrations/manufacturing/fake_named_queries.py` | Adapter | 精确 Query 的具名查询夹具、深复制及租户核对，无查询或来源回退。 |
| `app/integrations/manufacturing/sqlite_named_queries.py` | Adapter | 八条固定参数化查询；按操作只打开制造/设备/质量一个相关只读库，保留列集/排序/上限和全历史语义。 |
| `app/knowledge/__init__.py` | 包 | 知识包锚点。 |
| `app/knowledge/decision.py` | 业务 | 检索需求、质量和回退决策。 |
| `app/knowledge/rag.py` | 兼容/装配 | 旧 RAG facade、后端选择和兼容搜索入口；身份与缺陷别名经存储/身份 Port 读取。 |
| `app/knowledge/ranking.py` | 纯 | 检索排序/去重规则。 |
| `app/knowledge/search_contracts.py` | 纯 | 工厂搜索、目录和主体 Backend 契约。 |
| `app/knowledge/search_query.py` | 纯 | 查询规范化与过滤，含 SQLite FTS 查询串 `sqlite_fts_query`。 |
| `app/knowledge/search_policy.py` | 纯 | 从旧 RAG 复用的过程/设备/缺陷推断与个人查询扩展规则；不读取设置或来源。 |
| `app/knowledge/search_tool/__init__.py` | 包 | 原生联合检索包锚点，无全局工具注册。 |
| `app/knowledge/search_tool/contracts.py` | 纯 | 输入、查询、候选快照、消费方/个人搜索 Port、owner 映射、检索准备与输出契约。 |
| `app/knowledge/search_tool/handler.py` | 纯 | 核对主体、owner、来源和候选，复用既有重排，保留引用及来源多样性，产生列表 ToolResult。 |
| `app/knowledge/search_tool/binding.py` | 纯 | 原生 search_knowledge 1.0.0；准备租户 Scope，空查询不咨询来源。 |
| `app/knowledge/search_registry.py` | 装配/过渡 | 搜索/目录后端注册和选择；`sqlite` 后端由 Port 绑定的工厂创建。 |
| `app/knowledge/sqlite_backend.py` | Adapter | 工厂知识/目录 SQLite 后端。 |
| `app/integrations/knowledge/__init__.py` | 包 | 知识来源集成包锚点。 |
| `app/integrations/knowledge/fake_search.py` | Adapter | 按完整查询/租户/用户读取深复制的精确候选夹具，来源明确为 FAKE。 |
| `app/integrations/knowledge/backend_search.py` | Adapter | 显式组合 FactorySearchBackend 与个人搜索 Port，核对 owner envelope、固定请求及错误/超时脱敏；无全局选择或故障回退。 |
| `app/integrations/knowledge/runtime_search.py` | Adapter/装配 | 默认知识工具的延迟来源组合；显式只读知识库会话及质量库别名查询，按可信身份读取个人知识，保留可替换工厂后端。 |
| `app/knowledge/ocr.py` | 业务 | OCR 调用与文本处理。 |
| `app/knowledge/ocr_quality.py` | 纯 | OCR 质量评价规则。 |
| `app/evidence/__init__.py` | 包 | 证据包锚点。 |
| `app/evidence/semantics.py` | 纯/过渡 | 原报告和八项具名工具的证据语义与范围描述；仍识别旧 SQL 工具。 |
| `app/evidence/validator.py` | 业务 | 计划/Playbook 证据覆盖与结论限制；新具名查询精确匹配产品、设备、制程、批次及日期参数。 |
| `app/evidence/skill_policy.py` | 纯 | 显式 1.3.0 证据策略：核对知识结果原生检索焦点，复用原覆盖/风险校验；默认 1.2.0 不变。 |
| `app/evidence/answer_synthesizer.py` | 业务 | 证据约束答案结构和渲染。 |
| `app/evidence/serialization.py` | 纯 | 证据/报告递归复制及 JSON 规范化；精确内置容器和字段名元数据优化，保留子类/deepcopy/错误语义。 |

### Skill（显式试点装配，默认 HTTP 未启用）

| 文件 | 标签 | 职责 / 关键入口 |
| --- | --- | --- |
| `app/skills/__init__.py` | 纯 | 导出校验与包读取 API，不进行能力发现或执行。 |
| `app/skills/contracts.py` | 纯 | 冻结的 Manifest/工具依赖/Workflow 与证据引用/资源声明，以及防御性复制的 DependencyInventory。 |
| `app/skills/versions.py` | 纯 | 严格 x.y.z 版本及有界逗号 AND 比较式，不自动选择 latest。 |
| `app/skills/manifest.py` | 纯 | 严格 JSON、结构/状态/依赖校验；声明可用不授予执行权限。 |
| `app/skills/resources.py` | 文件边界 | 跨平台路径检查、有界 UTF-8 文本读取、链接/硬链接/重解析点拒绝和打开句柄检查。 |
| `app/skills/package.py` | 显式加载 | 显式包根与可信依赖清单、按声明路径读取资源，返回冻结文本快照。 |
| `app/skills/catalog.py` | 声明/文件边界 | 由明确包根建立不可变目录，仅读 Manifest；稳定精确版本与可用性元信息，加载前拒绝声明漂移。 |
| `app/skills/discovery.py` | 纯 | 按可信 Workflow/制程/执行模式/输入名称确定性筛选，返回精确候选及拒绝原因，不自动取最新版。 |
| `app/skills/loader.py` | 渐进加载 | 精确选择后先读 SKILL.md，再按显式路径返回新内容快照；保持已读文本及累计预算，不授予执行权限。 |
| `app/skills/releases.py` | 发布/文件边界 | 冻结完整声明资源，管理精确版本启用/激活/禁用/回退；内存 Catalog/Loader 复用原渐进加载，已发布正文不再读作者目录。 |

该模块只依赖标准库和自身。`scripts/check_skill_package.py` 是独立验收入口；
`evaluations/skills/manifest_validation_v1/` 是 MOD-016 验证夹具。MOD-017 的
`scripts/demo_skill_loading.py` 和 `evaluations/skills/catalog_discovery_v1/` 展示三阶段加载；
两组夹具均不是光刻业务 Skill。演示和 API 用法见 [Catalog 报告](reports/mod-017-skill-catalog.md)。

`app/skills/lithography/cpk_diagnostic/` 为 MOD-018 的光刻包，含 `manifest.json`、
`SKILL.md`、`references/cpk_context.md`、`scenarios/acceptance.json` 四个文本资产。
它们不计入 Python/静态源码数，不执行代码、不授予权限；实际装配位于 bootstrap，
复用既有 Playbook/Planner。见 [试点报告](reports/mod-018-litho-cpk-skill.md)。

`scripts/demo_skill_releases.py` 以 `evaluations/skills/release_lifecycle_v1/` 的两版中性夹具展示发布、禁用与回退；实际 Run、权限和版本固定验收见 [发布报告](reports/mod-019-skill-releases.md)。

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
| `app/conversation/sessions.py` | 业务/存储 | 会话 CRUD、历史、执行记录组合；数据库会话、执行存储和身份经存储/身份 Port 读取。 |
| `app/conversation/turn_decision.py` | 纯 | 单轮决定数据结构。 |
| `app/model_gateway/__init__.py` | 包 | 模型网关包锚点。 |
| `app/model_gateway/compatibility.py` | 兼容/过渡 | 发布前模型兼容性探针；URL 与凭据头取自 `ModelEndpoint`，管理端探针仍自建客户端。 |
| `app/model_gateway/registry.py` | 装配/存储 | 模型 Provider 配置、选择和持久化读取；数据库会话与身份经存储/身份 Port 读取。 |
| `app/model_gateway/health.py` | 业务/存储 | 模型熔断健康记录；数据库会话经存储/身份 Port 读取。 |
| `app/model_gateway/gateway.py` | Port/Adapter | `ModelGatewayPort`/`ModelSessionPort`、`ModelEndpoint`，`HttpModelGateway` 持有客户端生命周期与聊天模板整形。 |
| `app/model_gateway/streaming.py` | Adapter | SSE 请求、响应拼装、流式审计。 |
| `app/core/__init__.py` | 包 | 核心包锚点。 |
| `app/core/settings.py` | 装配 | 环境设置和默认运行配置。 |
| `app/core/identity.py` | Adapter/过渡 | 当前身份解析和 SQLite/请求绑定。 |
| `app/core/identity_contracts.py` | 纯 | Identity claims 与演示 Header 解析契约。 |
| `app/core/storage_identity_ports.py` | 纯 | 存储/身份窄 Port：`PrincipalView`、`StorageIdentityBindings` 与安装/读取函数；只加载标准库，未安装时报错并写明安装函数。 |
| `app/core/model_capabilities.py` | 纯 | 模型能力默认值与 `normalize_capabilities`，供 registry 与数据库迁移共用。 |
| `app/persistence/__init__.py` | 包 | 存储包锚点。 |
| `app/persistence/database.py` | 存储/过渡 | SQLite 连接、初始化、部门库挂载与建表。 |
| `app/persistence/department_schemas.py` | 纯 | 部门数据库 schema 定义。 |
| `app/persistence/execution_store.py` | 存储/过渡 | 计划、步骤、事件和中断状态记录；尚非安全恢复协议。 |
| `app/telemetry/__init__.py` | 包 | 可观测包锚点。 |
| `app/telemetry/audit.py` | 存储 | JSONL 审计、内容指纹和运行日志。 |
| `app/telemetry/http.py` | API | HTTP 请求/响应观测。 |
| `app/telemetry/runtime_status.py` | 业务/存储 | 运行状态与 SQLite 查询；数据库会话经存储/身份 Port 读取，身份参数按 `PrincipalView` 标注。 |

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
| `app/personal_knowledge_runtime/service.py` | 业务/过渡 | 个人知识用例；审计与数据库会话经存储/身份 Port 读取。 |
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

MOD-016～018 已实现独立 Manifest、依赖校验、安全资源、显式 Catalog/Discovery/渐进 Loader，以及实际 skill_refs 的显式光刻业务试点；MOD-019 的进程内发布与完整声明资源固定已验收，跨进程交付不在本项范围；`manufacturing.playbooks` 是现有业务
规则与证据计划，不能等同 Skill。`persistence.execution_store` 已保存运行记录，但尚未提供
可安全重放的 Checkpoint/恢复协议。长期记忆仍是 OPTIONAL，未启用；因此不存在已完成的
语义/情景/程序三层长期记忆实现。

## 5. 当前耦合与迁移事实

边界清单记录 **14 条精确依赖债务、26 个 DB 调用候选文件、7 个兼容入口、92 个静态消费者**（MOD-015d 后；015a 退出 5 个 coordinator 转发模块与 `conversation/context_resolver.py`，015d 用存储/身份 Port 移除 15 条债务）。
兼容消费者扫描只覆盖 app/scripts/tests 内的静态 import、字面动态 import 与常见 mock patch；
外部调用方和计算出的动态引用仍需人工审查。

14 条债务的实际来源可归纳为：

- `app/agent_runtime/compatibility.py` 仍直接装配 manufacturing、legacy 与 default bootstrap（4 条，MOD-015）；本批只新增一条精确默认装配边，不扩大 Runtime 的全局允许依赖。
- `app/agent_runtime/tools/catalog.py` 与 `registry.py` 仍反向看 bootstrap（2 条，MOD-015）。
- `app/conversation/decision_arbiter.py` 仍直接引用 `memory_system.contracts`（1 条，MOD-015）。
- `app/evidence/validator.py` 仍接 Playbook/Plan 实现（2 条，MOD-015）。
- `app/manufacturing/enterprise_data.py` 接身份、`reports.py` 接 SQLite（2 条，MOD-008；过渡期旧 facade，随旧路径退出处理）。
- `app/model_gateway/compatibility.py` 仍接 `memory_system.context.history/protocol`（2 条，MOD-025；去掉需改公开探针或移动协议逻辑）。
- `app/persistence/execution_store.py` 仍接身份（1 条，MOD-021；REF-027 例外保留公开身份锚点）。

会话、rag/search_registry、模型 health/registry、个人知识 service 和 runtime_status 已改为依赖 `core/storage_identity_ports.py`，
默认实现由 `bootstrap/storage_identity_assembly.py` 在 `app.main` 与 `agent_runtime.service` 的装配路径安装；不经过这两条路径的直接 Python 消费者需先调用 `install_default_storage_identity()`。

26 个 DB 候选是 `api/application.py`、`api/routers/admin.py`、`api/routers/system.py`、
`api/runtime_dependencies.py`、`bootstrap/storage_identity_assembly.py`、`conversation/sessions.py`、`core/sqlite_support.py`、设备健康/过程诊断/生产报表/运行报表/具名查询五个 SQLite Adapter、知识 SQLite 后端、默认知识运行时的显式知识库/质量库只读来源、
`main.py`、`manufacturing/reports.py`、`manufacturing/seed.py`、模型 health/registry、
`persistence/database.py`、`persistence/execution_store.py`、个人知识的 documents/ingestion/jobs/search，
以及 `telemetry/runtime_status.py`。它们并不都是公司业务数据库：其中很多是应用自有会话、
索引、审计或合成 FAB 数据。

F2b 从默认清单、提示和 Dispatcher 移除旧 SQL 能力，但历史代码仍保留：
`planning_runtime/queries.py` 的旧模板、`steps.py` 的 v1 步骤、
`scope.py` / `evidence.semantics.py` 的兼容语义，以及 `manufacturing.reports.safe_select(sql)`。
只有显式历史回放与内部 Python 消费者可以使用这些保留入口，不能据此恢复默认模型执行。
默认业务读取已改走具名原生工具；API 报表、应用自有存储和历史 facade 的残余依赖
仍须在 MOD-012/015 中逐项验证，不能声称整个项目的数据库访问已全部解耦。

## 6. 可搬迁范围与尚不可独立搬迁部分

已经有七个较小源码单元：`memory_core`、`decision_core`、`model_transport`、
`enterprise_data_contract`、`retrieval_policy`、`factory_search_contract`、`identity_contract`；
它们的文件清单在 `evaluations/portable_units_v1.json`，用于契约/规则级仓库外验证。

另有旧 **37 文件** `dispatcher_pilot` 真 venv 安装清单，版本固定为 1.0.0；其用途是保持
MOD-007 的安装回归，并不自动包含后续源码。MOD-013 的 Ready 证明使用 49 文件源码切片；
MOD-014 的 Loop round 已验证 **53 文件**（37 + 3 runtime ports + 4 Agent 装配 + 5 Ready +
4 Loop）。MOD-008 首批在此基础上增加七个真实文件，形成 **60 文件**源码切片；以 -I -S、
空环境、无关 cwd 和持续网络/SQLite/配置/旧模块守卫实际执行 Fake Ready/Loop。
第二批再加入七个生产报表真实文件，**67 文件**源码切片已在上述隔离条件下实际执行三个工具的 Fake Ready/Loop 六条路径，验收结果见 MOD-008 报告。
第三批新增七个运行报表文件，**74 文件**源码切片已实际通过三工具的 Fake Ready/Loop 六条路径；验收证据单列于同一报告。
第四批增加七个企业工具文件及既有纯 data_contracts.py，**82 文件**源码切片已通过三工具 Fake Ready/Loop 及 Provider 夹具样本执行；持续守卫、负向控制、模块来源与空默认 Registry 均通过。Provider 夹具仍为 FAKE，不代表真实公司接入。
第五批知识工具使用单列的 **66 文件**切片（原 Loop 53、本批九文件和既有四个知识文件），
不在企业切片后继续累加制造模块。该切片已实际执行 Fake/Backend 各 Ready/Loop 四条路径，持续守卫、负向控制、模块来源和空默认 Registry 均通过。
第六批 F1 单列 **60 文件**具名查询切片（原 Loop 53 + named_queries 七文件），八工具各
Fake Ready/Loop 共 16 条路径已通过持续守卫、负向控制、来源和空默认 Registry 验证；它与
首批诊断的 60 文件清单不同，不依赖第二至第五批新工具。
MOD-016 另有 **7 文件**独立源码验证切片（六个 app/skills 文件 + 未改写的 app 包锚点），两端均以 -I -S、无关 cwd 和持续负控完成真实包解析/资源读取；不扩写冻结的七个 portable units 或旧 37 文件清单。
MOD-017 另以 **10 文件**切片（九个 Skill 文件 + 原 app 锚点）在两端完成 Catalog → 发现 → 说明 → 显式参考资料的隔离真链路，持续负控、精确模块来源及无效声明/依赖反例通过；旧七文件 MOD-016 隔离仍通过。
MOD-018 另有 **95 文件 + 4 文本资产**的完整光刻试点切片，在两端以 -I -S、无关 cwd 执行真实装配 → Ready/Fake Loop → Dispatcher → Fake 来源 → 证据策略；未改写包锚点，保留现有 runtime 包锚点带入的 Coordinator/stages 依赖，不能据此宣称旧协调器已完全退出。
MOD-019 以原 95 文件清单加 `app/skills/releases.py` 的 **96 文件**切片，在两端验证旧 Run 跨越发布后仍使用原资源、新版本 Loop 与禁用准入；原 95 文件切片不扩容，文件配置通过延迟导入保持可用。
MOD-009 另以 **101 文件**的完整工具来源切片，在两端以 -I -S、无关 cwd 和持续守卫执行 21 项工具加可选汇总的 44 条 Fake Ready/Loop 路径；按声明逐文件复制、核对导入来源，默认 Registry 为空。原 Runtime 包锚点带入的 Coordinator/stages 保留，不宣称旧协调器已退役。替代来源的 17 SQLite / 3 Provider / 1 Backend 双路径在显式临时联合夹具另验收。
这些都是源码切片或试点制品，不是可与整个应用任意组合安装的正式 Wheel。

只读 SQLite 各批工具的双路径数值与 Scope 对照在显式临时库上另行验证。公司账号、公司
数据库方言或报表 API Adapter 尚未接入；迁入时复用工具与 Data Port，具体来源适配另验收。

在 WSL 仓库根目录、既有 Python 环境可查看首批效果（Fake，无真实模型或网络请求）：

```bash
python -m app.bootstrap.diagnostics_demo --mode ready --tool get_process_capability --arguments '{"process_step":"CMP"}'
python -m app.bootstrap.diagnostics_demo --mode loop --tool get_sensor_summary --arguments '{"process_step":"CMP","equipment_id":"CMP-01","signal_name":"pressure"}'
python -m app.bootstrap.production_reports_demo --mode ready --tool get_fab_overview
python -m app.bootstrap.production_reports_demo --mode loop --tool get_process_pass_rate --arguments '{"process_step":"CMP"}'
python -m app.bootstrap.operational_reports_demo --mode ready --tool get_defect_pareto --arguments '{"process_step":"CMP","limit":1}'
python -m app.bootstrap.operational_reports_demo --mode loop --tool get_recent_excursions --arguments '{"process_step":"CMP","equipment_id":"CMP-01"}'
python -m app.bootstrap.enterprise_tools_demo --mode ready --tool get_enterprise_fab_summary --arguments '{"process_step":"CMP","equipment_id":"CMP-01"}'
python -m app.bootstrap.enterprise_tools_demo --mode loop --adapter provider --tool query_enterprise_data --arguments '{"entity":"sensor-events","process_step":"CMP","equipment_id":"CMP-01","signal_name":"RF power"}'
python -m app.bootstrap.knowledge_search_demo --mode ready
python -m app.bootstrap.knowledge_search_demo --mode loop --adapter backend --arguments '{"query":"LITHO 颗粒"}'
python -m app.bootstrap.named_queries_demo --mode ready --tool get_product_yield_breakdown
python -m app.bootstrap.named_queries_demo --mode loop --tool get_lot_excursion_history --arguments '{"lot_id":"LOT-001"}'
```

Loop 的模型响应由固定 Fake Port 提供；输出包含实际结果、Source Scope、TOOL 引用与同一
Guard 的计数。原生工具版本均为 1.0.0；F2b 统一迁移默认能力清单为 2.0.0，保留全局
TOOLS/TOOL_HANDLERS 的容器身份，但有意改变清单内容及默认解析行为。
周良率的产品过滤由完整 Query 核对；当前通用 ToolScope 没有 product 维度，不能将其解释为新增了产品级授权。

当前不能独立搬迁的部分包括：默认 HTTP/API 应用、旧 service/coordinator 链、模型目录/健康
与真实 Provider 配置、历史 Python 兼容入口、会话与个人知识写入的 SQLite 组合、模型健康
存储、知识管理的旧后端选择，以及前端与 API 的整体装配。企业内网迁移应只把已验收切片与明确 Adapter
接口先行带入，不能把该工作树视为所有模块已独立部署。

## 7. 读取本快照的限制

本文件是实际目录与责任地图。MOD-014 的最终 217 项必要定向、3 项旧故障回退系统回归与
修订后预声明 r2 正式性能/独立审计通过，r1 证据保留。MOD-008 首批的 281 项必要回归、
60 文件隔离、旧安装/源码闭包/冻结行为/守卫通过。第二批的 305 项必要回归、67 文件隔离、
旧安装/源码闭包/冻结行为/守卫也通过。第三批最终 328 项必要回归、74 文件隔离及上述兼容门
通过。第四批最终 354 项必要回归、82 文件隔离及上述兼容门也通过；第五批最终 413 项必要回归、RAG 15/15、66 文件知识切片及兼容门通过，首轮仓库边界失败记录保留。第六批 F1 的 431 项必要回归、32 主路径、60 文件具名切片及上述兼容门也通过。F2a 版本化消费映射已验收；F2b 默认切换及 SQL 退出已通过功能/质量复核和 r5 正式性能及原始墙钟独立重算，整个 MOD-008 已验证；原定下一项 MOD-009，MOD-016～019 和 MOD-009 现均已验证，下一项 MOD-012；009 的两端专项、来源替换、101 文件隔离与完整阶段门见对应报告。此后变化须随
工作树重新核对。文档为 UTF-8/LF，源码表不展开测试、日志、runtime 产物或工作簿内容。
