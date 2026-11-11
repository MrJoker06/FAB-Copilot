# 模块化工作包追踪

本表记录已获用户授权的架构解耦与分块迁移工作。它不是产品分类 TODO，不改变既有任务统计，也不自动激活企业级真实数据、生产 ACL、SSO 或部署任务。

上一轮已完成的实施顺序（2026-11-02 用户确认，2026-11-07 全部验证）：**MOD-016 → MOD-017 → MOD-018 → MOD-019 → MOD-009 → MOD-012 → MOD-015**。MOD-016～019、MOD-009 及 MOD-012 已验证（009：2026-11-06；012：2026-11-07）；MOD-015 分 a～e 五批，015d 原验收统计存在一处计数待核实项，详见 [Runtime 收口报告](../reports/mod-015-runtime-convergence.md)。保留的兼容 facade 与配置锚点改由 MOD-027 处理。MOD-024 于 2026-11-10 完成首批组合制品验收；当前优先讨论 MOD-030（合并 Issue #1 第 3/4/6 条：Skill 业务包与 Tool 通用标准）；第 8 条 Validator 独立评审后再重审 MOD-029，卸载方案暂缓。当前共 10 项未完成：MOD-020～023、MOD-025～030。本轮已获用户授权实施 c～e，仅本地提交、不推送；具体依赖与状态见下表；P0～P5 保留职责分类，任务编号不表示施工时间顺序。

| 工作包 | 阶段 | 状态 | 依赖 | 当前验收证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `MOD-001` | P0 | 已验证 | 无 | 七个便携源码单元重建、仓库外验证、仓库检查和身份契约回归；见 [基线报告](../reports/mod-001-portable-baseline.md) | `MOD-002` |
| `MOD-002` | P0 | 已验证（2026-10-24，配对协议） | `MOD-001` | 174 成员来源核对、隔离 observe、完整门 758 Python/89%/17 浏览器、CLI 修正后 76 定向项通过；两次预声明 1000×2 正式比较 A/B 均通过，原始墙钟独立重算通过；r1–r5 失败保留，见 [基线报告](../reports/mod-002-behavior-baseline.md) | `MOD-003` |
| `MOD-003` | P0 | 已验证（2026-10-24） | `MOD-002` | 171 文件唯一归属、30 条精确依赖债务、13 个兼容入口/80 条静态消费、19 个 DB 候选；55 定向项与 r2 完整门 786 Python/89%/17 浏览器通过；r1 浏览器失败及同步修正证据保留，见 [边界报告](../reports/mod-003-module-boundaries.md) | `MOD-004`（P1 契约） |
| `MOD-004` | P1 | 已验证（2026-10-24） | `MOD-003` | 纯契约 1.0.0、旧导出按需加载、真实包隔离导入/仓库外 Fake、109 定向项与冻结行为 v2/旧重构契约/仓库守卫通过；见 [契约报告](../reports/mod-004-tool-contracts.md) | `MOD-005` |
| `MOD-005` | P1 | 已验证（2026-10-24） | `MOD-004` | 设备健康输入/Definition/Binding/Data Port、Fake/双库只读 SQLite；26 文件仓库外真运行、旧新结果/生命周期、130 定向项、冻结行为 v2 与守卫通过，181 文件/0 错误；见 [试点报告](../reports/mod-005-equipment-health.md) | `MOD-006` |
| `MOD-006` | P1 | 已验证（2026-10-24） | `MOD-005` | 单一 Registry、原生兼容容器/live patch、bootstrap 与 LegacyBindingAdapter；27 文件隔离、163 定向项、冻结行为/守卫及一次 1000×2 正式配对性能/独立重算通过；185 文件/27 依赖债务，见 [Registry 报告](../reports/mod-006-tool-registry.md) | `MOD-007` |
| `MOD-007` | P1 | 已验证（2026-10-24） | `MOD-006` | 最小 Dispatcher、Scope/能力 Policy、同实例 LoopGuard、结果桥接；204 项必要定向、37 文件真实 venv 隔离安装/Fake/双库 SQLite、取消/超时/安装包拒绝及冻结行为/守卫通过；191 文件/27 债务，见 [验收报告](../reports/mod-007-tool-dispatcher.md) | `MOD-010` |
| `MOD-008` | P1 | 已验证（2026-11-02，F2b 收口） | `MOD-014` | 默认 v2 / 原生工具及模型 SQL 退出、阶段全量质量分段通过；续作 205 项必要回归通过，第五轮 1000×2 全部墙钟 median/p95 及 12,000 原始样本独立重算通过，r1～r4 失败保留；258 文件/零边界错误，见 [报告](../reports/mod-008-tools-rollout.md) | `MOD-016`（优先级调整） |
| `MOD-009` | P1 | **已验证（2026-11-06）** | `MOD-008` | 七类 Port / 21 项工具来源替换与 Ready/Loop；可选查询注册、两端 9 项专项/各 6 组 CLI、101 文件隔离及完整离线阶段门通过，275 文件/零边界错误；残余兼容依赖保留交给 015，见 [报告](../reports/mod-009-tool-sources.md) | `MOD-012` |
| `MOD-010` | P2 | 已验证（2026-10-24） | `MOD-007` | 三个最小 Ports、类型化上下文/阶段结果、安全摘要事件；171 项必要定向、40 文件仓库外实际链路、原 37 文件安装回归与冻结行为/守卫通过；194 文件/27 债务，见 [验收报告](../reports/mod-010-runtime-ports.md) | `MOD-011` |
| `MOD-011` | P2 | 已验证（2026-10-25） | `MOD-010` | 显式 AgentDefinition/Run 装配、真实旧快照组装迁移；185 定向、44 文件仓库外链路、原安装/冻结行为/守卫及一次 1000×2 正式配对/独立审计通过；199 文件/28 兼容债务，见 [验收报告](../reports/mod-011-agent-assembly.md) | `MOD-013` |
| `MOD-013` | P2 | 已验证（2026-10-26） | `MOD-011、007` | Ready 显式注入 Dispatcher、单次预算及过滤后结果采用；204 定向、49 文件隔离链路、原安装/冻结行为/守卫及一次 1000×2 正式配对/独立审计通过；204 文件/28 债务，见 [验收报告](../reports/mod-013-ready-dispatcher.md) | `MOD-014` |
| `MOD-014` | P2 | 已验证（2026-10-26） | `MOD-013、011` | 217 定向 + 3 旧回退系统项，真实 Loop 综合/双 SQLite 对照/53 文件隔离/守卫通过；r1 通过后修复注入模型故障隐式回退，预声明 r2 及独立审计通过，阈值未改；208 文件/28 债务，见 [验收报告](../reports/mod-014-loop-dispatcher.md) | `MOD-008` |
| `MOD-012` | P2 | **已验证（2026-11-07）** | `MOD-014` | ModelGatewayPort + HTTP Adapter 接管 Loop/Ready/Context 的客户端生命周期、URL/凭据头与聊天模板整形，重试/健康/回退留在调用方；新增 20 项专项，WSL 定向 313 项及治理 17 项通过，Windows 同集仅既有环境失败；278 文件/零边界错误，见 [报告](../reports/mod-012-model-gateway.md) | `MOD-015` |
| `MOD-015` | P2 | **已验证（2026-11-07，015a～015e）** | `MOD-009、012、014` | 拆为 a～e 五批。015a 兼容台账收敛：删除 5 个 coordinator 转发模块、`conversation/context_resolver.py`、旧 `(client, endpoint, headers)` synthesis facade、`ClientModelSession` 和 `state.endpoint`，探针 URL/凭据头改由 `ModelEndpoint` 提供，配置优先级修为“进程环境 > 项目 `.env` > 工作区 `.env`”。WSL 定向 251 项、扩展 183 项通过；Windows 同集只有既有环境失败。015b 依赖组/状态类型化：新增 `agent_runtime/ports.py` 结构化端口（`RuntimeSettings`/`RuntimeModelConnection` 视图、22 个可调用 Protocol、`ToolRunBindings`），`dependencies.py` 58 字段、`CoordinatorRunState` 与 `AgentLoopContext` 全部类型化（仅 TYPE_CHECKING 导入，运行时零变化），`telemetry.py` 新增 `AuditEventSink`/`runtime_stage_completed` 审计适配器（默认路径未接入），便携打包器跳过 TYPE_CHECKING 导入；新增 17 项专项，WSL 定向 433 项通过，Windows 同集只剩与 HEAD 一致的既有环境失败。273 文件/零边界错误，兼容入口 7、债务 29 不变，消费记录 91→92。015c Loop 职责拆分：`run_agent_loop` 拆为 `loop_state`（`LoopRunState` 单一可变状态与唯一 context 回写点）、`loop_request`、`loop_model_call`、`loop_answer`、`loop_tool_round`、`loop_round_validation` 六个模块，`agent_loop.py` 812→196 行，只保留上下文与编排；纯重构，37 个场景的事件/进度/消息/结果黄金样本（HEAD 导出副本重录字节一致）逐项相等，另有真实取消验证；WSL 定向 339 项通过，Windows 同集只剩与 HEAD 一致的既有环境失败。279 文件/零边界错误，兼容入口 7、债务 29、消费记录 92 不变。015d 存储/身份依赖注入 Port：新增只含标准库的 `core/storage_identity_ports.py`（`PrincipalView`、`StorageIdentityBindings` 与安装/读取函数，未安装时抛出写明安装函数的错误）和 `bootstrap/storage_identity_assembly.py`（调用时读取具体模块属性的默认绑定，由 `app.main` 与 `agent_runtime.service` 的装配路径安装），能力默认值移到 `core/model_capabilities.py`、`sqlite_fts_query` 移到 `search_query.py`；会话、rag、search_registry、模型 health/registry、个人知识 service、runtime_status 改为同名委托函数，SQL 与 patch 点不变。债务 29→14；5 条延后（enterprise_data/reports → MOD-008，model_gateway.compatibility → memory ×2 → MOD-025，execution_store → identity → MOD-021）。WSL 全部 168 个模块 1290 项与 HEAD 对照无新增失败。282 文件/零边界错误，兼容入口 7、消费记录 92、DB 候选 26 不变，边界例外 37→32。015e 完整链路与无泄漏验收：新增 `tests/test_runtime_convergence_acceptance.py`（11 项），类型化应用（Skill 关闭、Skill 文件根、Skill 发布库）× Ready/Loop 与旧 `run_agent` 的 Loop/Ready/上下文解析，各跑成功、取消、模型异常、工具或 Skill 重新校验失败；每次失败后无残留任务、会话全部关闭、每 Run 新预算/Dispatcher、发布库与 Skill 快照、`runtime_status`、身份 ContextVar、存储/身份绑定和 `TOOLS`/`TOOL_HANDLERS` 不变，后续运行与首次干净运行一致；三种注入泄漏的变异自检均被发现。未发现运行时泄漏。`decision_arbiter` 与 `evidence.validator` 改用只读 Protocol，债务 14→11；其余 MOD-015 台账项（6 条债务、3 个过渡文件、7 个兼容入口、19 条 DB 来源、2 条边界例外）保留并改挂 MOD-027。WSL 全部 169 个模块 1301 项与 HEAD 对照无新增失败，Windows 定向 37 模块 412 项只剩与 HEAD 一致的既有环境失败。282 文件/零边界错误，入口 7、消费记录 92→94、DB 候选 26。见 [报告](../reports/mod-015-runtime-convergence.md) | `MOD-027` 承接保留的 `run_agent` facade、`TOOLS`/`TOOL_HANDLERS`、`compatibility` 装配与配置锚点 |
| `MOD-016` | P3 / 当前优先 | **已验证（2026-11-02）** | `MOD-008、011、014`（已验证） | 标准库独立清单/依赖校验与显式资源读取；两端各 16 项专项（WSL 跳过 2、Windows 跳过 1，均为另一平台专用项）、各 22 项额外非法输入检查；65 项既有回归、3 项旧隔离回归和仓库/兼容门通过，见 [验收报告](../reports/mod-016-skill-manifest.md) | `MOD-017` |
| `MOD-017` | P3 / 当前优先 | **已验证（2026-11-03）** | `MOD-016` | 显式 Catalog、确定性发现、渐进内容快照；两端各 31 项专项（WSL 跳过 2 / Windows 跳过 1），10 文件仓库外真链路及各 5 组演示/读取观测通过，基线 84 项及必要守卫通过；267 文件/零边界错误，见 [验收报告](../reports/mod-017-skill-catalog.md) | `MOD-018` |
| `MOD-018` | P3 / 当前优先 | **已验证（2026-11-04）** | `MOD-017、008、014` | 实际 opt-in skill_refs 装配、原命名 Playbook/Planner 与双路径；WSL 139 项 + Dispatcher/旧安装 27 项，Windows 51 项必要检查通过（平台跳过分别 2/1）；95 文件+4资产隔离、两端各5组演示通过，旧 Windows 基线失败另列，见 [报告](../reports/mod-018-litho-cpk-skill.md) | `MOD-019` |
| `MOD-019` | P3 / 当前优先 | **已验证（2026-11-04）** | `MOD-018` | 进程内不可变发布、精确激活/禁用/回退与真实 Run 内容固定；主审两端专项、96 文件隔离和各5组 CLI 通过，完整离线阶段门通过，272 文件/零边界错误，见 [报告](../reports/mod-019-skill-releases.md) | `MOD-009` |
| `MOD-020`～`MOD-023` | P4 | 计划中 | P2 | Checkpoint、提交和恢复协议 | 按需求启用 |
| `MOD-024` | P5 | **已验证（2026-11-10）** | `MOD-003` 及已稳定 Ports | 五类唯一所有者 ZIP、290 源码/资源成员、三个组合 Profile；WSL/Windows 各 11 项专项与 44 路工具、Cpk 双路径、Skill 发布/禁用、离线模型传输独立验收通过；286 应用文件未改，见 [报告](../reports/mod-024-module-delivery.md) | `MOD-030`（待审核） |
| `MOD-030` | P3/P5 / 当前优先 | **030a/b 已交付；c1～c7 已本地提交；030d 定向验收完成；030e 进行中** | 已有 Tool/Skill/交付能力；不锁定当前目录 | 合并 Issue #1 第 3/4/6 条；按 Agent Skills、MCP Tools 与 JSON Schema 形成标准 Skill 业务包和包内/共享 Tool，职责归属、描述、加载和迁移验收见 [详细计划](../skill-tool-standardization-plan.md)；030a 规范映射、模板与 51 文件执行起点清单见 [报告](../reports/mod-030a-standard-baseline.md)；030b 光刻标准 Skill 1.1.0、共享 `get_capability_trend`、单一描述源与 MCP 视图、证据策略四态、删除 `safe_select`、冻结 `LEGACY_TOOLS`，见 [报告](../reports/mod-030b-litho-pilot.md) | 审核 030b；030c 按消费者分批迁移业务 Tool；第 8 条 Validator（MOD-031）单独讨论 |
| `MOD-029` | P2/P5 | **暂缓，待前置讨论后重审** | 结合 MOD-030 标准与第 8 条 Validator 职责结论；不等待完整恢复链 | 保留 [旧草案](../tool-result-offloading-plan.md)，仅更新暂缓状态，不重写预算/实现方案，也不执行 | 前置讨论后修订并审核，随后再确定实施排期 |
| `MOD-025`～`MOD-028` | P5 | 计划中 | 对应稳定 Ports | 交付制品、演示、Fake 集成与迁移评审；MOD-027 另承接 MOD-015 收尾时保留的 `run_agent` 兼容 facade、`TOOLS`/`TOOL_HANDLERS`、`compatibility` 装配边和 `core/settings.py` 配置锚点（台账 exit_task 已改为 MOD-027） | 与里程碑交错执行 |

2026-11-02 依赖修订说明：016 不再等待完整 015，改用已验证的 008/011/014 接口；018 必须在实际入口补齐已预留但尚未支持的 skill_refs/装配接缝，不能只做文档加载或测试内手工调用。019 完成后，015 再统一收口 Skill 与 Runtime 状态/事件，验收包括版本固定和每次调用的权限/预算。最小完整 Agent 与整体迁移里程碑仍需 009/012/015，先行 Skill 通过不提前代表它们完成。

业务数据访问采用 `Agent / Skill / Workflow → Tool → Data Port → Adapter`；会话、Checkpoint 和知识管理等内部写入采用 Store/Repository Port。SQL 与数据库方言只允许存在于 Adapter/Repository。状态变更和验收记录必须引用实际执行命令，不得以文档更新代替通过。

## 2026-10-22 文档补充：量化小模型与数据接入

总方案已修订为 v1.2，保留单工具 → Ready/Loop 双路径 → 批量推广的原顺序。模型只调用具名业务工具并填写结构化参数，不生成/提交可执行 SQL，也不通过任意查询 DSL、连接串或隐藏工具名绕过服务端限制。

| 工作包 | 补充要求（尚未实现/验收） |
| --- | --- |
| `MOD-003` | 登记 `query_manufacturing_data(sql)` / `safe_select` 的定义、消费者、模型暴露点、替代业务用例和退出条件 |
| `MOD-004～007` | 业务 Data Port 归消费方；输入不新增任意查询文本；Dispatcher 限制允许能力，伪造 SQL 调用在查询前拒绝 |
| `MOD-008` | 用具名业务工具覆盖实际用例，从目标模型清单与可执行绑定移除旧 SQL 能力；能力/Schema 变化单列版本与迁移说明，不伪装等价重构 |
| `MOD-009/015` | 验证替换 Adapter 不改调用方、双路径拒绝行为、旧调用退出及来源/统计口径；不自动刷新历史基线 |
| `MOD-025～028` | 按总方案 D0～D3 能力层级逐块验收；Fake 通过不等于真实数据库、权限或目标量化模型效果通过 |

当前代码仍存在旧 SQL 工具，本次仅更新文档，未禁用或移除该入口。SQL/查询构造由服务端受控实现；D1 即具备最小连接生命周期与安全约束，但不提前建设统一 Connection Manager 或企业数据平台。不改变任务完成状态、历史性能失败或企业任务授权范围。

## 2026-10-24 文档补充：数据库与报表/API 双接入边界

总方案现为 v1.3。公司侧可能提供只读数据库账号，也可能提供报表/API，具体接入方式未定；这不等于实际接入资料和生产授权已经齐备。当前先固定业务 Data Port 和输入/输出口径，以 Fake/SQLite 验收；真实来源按业务能力显式绑定，不同时预建两套实现，不在故障时隐式切换来源。

| 工作包 | 数据库处理补充（计划要求，不代表通过） |
| --- | --- |
| `MOD-003` | 登记业务查询/内部存储消费者、库/表依赖、全库挂载/初始化副作用及兼容退出条件，明确数据与源码所有者 |
| `MOD-005～007` | 单工具绑定 Fake/SQLite；不加载其他业务数据库，不触发全局初始化；真实数据库/API 保留接缝，暂不实际接入 |
| `MOD-008/009` | 推广按需访问与来源替换；保持统计口径/血缘；未迁数据库依赖单列，不强删兼容入口 |
| `MOD-011/015` | Runtime 所需内部存储走 Store/Repository Port，现有会话/知识存储实现可暂作 Adapter；按消费者迁移进度收缩统一入口，不一次重写全部持久化 |
| `MOD-025～028` | 按能力确认来源、权限、字段/口径、标识映射、刷新时间和接口限额；记录绑定及实际证据，公司接入另按企业任务授权 |

公司业务库仅按获准范围读取，不由本项目建表、迁移或 seed；应用自有存储的初始化、升级、备份与恢复独立管理。演示库不是公司来源的必需依赖。报表缺少必要字段或口径不兼容时，明确能力不可用/证据不足，不补造或静默降低契约。

现有 SQLite 统一连接/多库挂载/初始化机制尚未改造；当前数据与兼容路径保留。本次仅修订计划，保持工作包编号、依赖、完成状态和原施工主线不变；不自动启动数据库迁移、真实接口调用或真实模型验收。
