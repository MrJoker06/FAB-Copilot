# 非企业级 TODO 执行计划

状态核对：`experiment/parallel-platform`，2026-10-27。

本计划只安排当前单机样例和产品能力建设。企业 SSO、真实制造系统、分布式数据基础设施、多实例治理、网关和生产部署统一暂缓，未经用户重新确认不进入开发。

任务定义与完成状态的唯一来源是各分类 TODO 中的 `[x]` / `[ ]`。本文件只维护当前执行顺序、依赖、检查点和暂缓边界；已完成的历史顺序见 [TODO 执行历史](execution-history.md)。

## 执行规则

1. 严格按顺序一次只实现一个任务编号，不并行混合多个功能。
2. 开始前确认工作区干净，或记录经审查的脏工作树清单、明确保留用户改动；确认依赖任务已完成，并记录基线测试结果。
3. 每个任务必须包含实现、针对性测试、必要文档和对应 TODO 状态更新。
4. 一个任务一个提交，提交标题包含任务编号，例如 `feat(UX-015): add desktop visual regression`。
5. 针对性测试通过后才能提交；每个阶段结束时运行完整 Python 回归和已有浏览器回归。
6. 未满足验收门槛时保持 `[ ]`，不得以“主体完成”或“文档完成”代替完成。
7. 发现企业级依赖时先记录阻塞，不扩展本期范围。
8. 发布或标签前，依赖或 Python/FastAPI/SQLite 升级，Schema/API/认证/RAG/流式链路重大变化，或累计约 5 个 feature/fix 后，必须运行完整测试审计。

## 当前状态

| 类型 | 数量 | 任务 |
|---|---:|---|
| 已完成 | 182 | 以各分类 TODO 为准；`AGENT-044` 已通过完整离线验收；此前阶段完成情况见执行历史 |
| 当前队列 | 0 | 仅指既有产品队列：答案综合灵活性改善队列已收口；模块化工作包另见下文，不自动激活暂缓或 `OPTIONAL` 任务 |
| 用户暂缓 | 2 | `QA-010` 远程 Live 验收、`UX-029` 移动端 |
| 企业级暂缓 | 43 | 见本文件末尾分类清单 |
| 可选候选 | 4 | `RAG-024`、`AGENT-039`、`REF-025`、`REF-026` `OPTIONAL`，不计入主任务统计 |

## 当前串行队列

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

2026-09-17 新增的产品任务定义与完成状态见 [Agent 执行架构 TODO](agent-architecture.md#答案综合灵活性改善2026-09-17-新增已完成)。`AGENT-040` 已于 2026-10-15 完成，`AGENT-041`、`AGENT-042` 已于 2026-10-16 完成，`AGENT-043`、`AGENT-044` 已于 2026-10-17 完成；本队列收口。`AGENT-039` 与 `REF-025` 保持 `OPTIONAL`，未自动激活。

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

`REF-001` 至 `REF-024`、`REF-027` 至 `REF-034` 及 `QA-005` 至 `QA-009` 已完成；Coordinator、Router、Planner、制造、存储、遥测、模型访问、会话运行时、知识与证据领域的职责边界已经冻结。2026-09-08 用户批准的 `REF-027` 至 `REF-034` 领域目录重构已在 2026-09-13 完成；具体映射、兼容与验收见 [代码可维护性 TODO](code-maintainability.md#领域目录重构已完成)。`REF-025`、`REF-026` 仍为 `OPTIONAL`，未激活内部拆分。`QA-010` 本地完整 7-run 已于 2026-09-04 通过，但远程 Environment/Secret/full 验收于 2026-09-05 由用户暂缓，故仍保持未完成且不阻塞本轮离线结构重构。普通 push/PR 不访问真实模型；必要 Live `provider-matrix` 不替代完整 7-run Live 门，未来发布或打标签前仍必须完成受保护的完整 Live 门；任一任务若产生未批准的产品行为差异，不得作为测试或重构完成。

### 检查点 D：上一阶段收口

`DEPLOY-012` 已完成：全部当前任务已标记 `[x]`，GitHub Actions 完整门与分支 required check 已收口。`AGENT-037`、`AGENT-038`、`OBS-017`、`QA-004` 与 `DEPLOY-012` 均是本期已完成的非企业级产品任务。

已完成的检查点 A、B 和 C 及其实测记录保留在 [TODO 执行历史](execution-history.md)。

## 可选候选（不一定需要）

长期记忆启用门槛：首先验证目标量化模型在长文本、干扰信息、冲突条件和多证据关联下的可靠性，之后才评估长期经验收益；不是仅以需求确认或收益判断放行。详见 [复杂上下文风险与压力测试](../memory-system-extraction-plan.md#8-量化模型的复杂上下文风险与启用门槛)。

2026-09-22：长期记忆明确为 `OPTIONAL`，暂不实施；不作为 Memory 抽离或当前任务记忆的依赖。跨任务自动沉淀与召回须另行确认并使用实际量化模型验证；既有知识/案例检索不受影响。`AGENT-039` 仍不排期，队列和任务数量不变，详见 [抽离路线 B3](../memory-system-extraction-plan.md)。

| 任务 | 状态 | 排期 | 候选范围 |
|---|---|---|---|
| `RAG-024` | `OPTIONAL` | 不排期 | 评估是否接入 Ragas；保留现有确定性 Hit Rate/MRR/Source Coverage/Forbidden Hits/ACL/引用页码门，候选观察 Context Precision/Recall、Faithfulness/Response Groundedness、Answer Relevancy、Factual Correctness 和 Noise Sensitivity。评审模型与 embedding 必须固定并显式配置，禁止隐式联网；只有用户明确激活后才转为普通 `[ ]` 并排期。 |
| `AGENT-039` | `OPTIONAL` | 不排期 | 评估/设计统一 Memory Manager：生命周期采用感官/输入 → 短期/工作 → 长期记忆，长期再分语义、情景、程序；覆盖输入规范化与过滤、状态/上下文预算/checkpoint、长期写入与召回、Writer、Retrieval Gate、Consolidation/冲突与遗忘治理。复用 Session/Context/Plan/Trace、知识/案例/个人知识及 Playbook/Planner/Guard，不重复造 RAG；落实 ACL/租户隔离、来源/置信度、版本/生效期/TTL/删除权，不从日志直接生成记忆、不保存隐藏思维链，程序变更须离线回放/黄金集和人工审批。只有用户明确激活后才转为普通 `[ ]` 并排期，不混入 `REF-006` 至 `REF-021`。 |
| `REF-025` | `OPTIONAL` | 不排期 | 拆分 Answer Synthesizer 的工具 Schema、contracts、解析、声明守卫、渲染和服务编排；冻结工具 Schema 哈希、证据降级、引用、章节顺序、措辞与报告。因其安全敏感，只在继续修改综合规则时激活。 |
| `REF-026` | `OPTIONAL` | 与 `DATA-019` 协调且不排期 | 拆分 SQLite schema、迁移、连接/Session、部门库和缺陷目录边界，保留 `app.database` facade；不实现 Oracle/MySQL Provider、不迁移 Schema。仅在数据库结构或 Provider 工作重启前激活。 |

## 用户暂缓（非当前）

| 任务 | 依赖 | 后续范围 | 状态 |
|---|---|---|---|
| `QA-010` | `QA-005` 至 `QA-009`、`DEPLOY-012` | 远程 live-e2e Environment、Secret 与首次完整实测验收；本地完整 Live 已通过 | 用户暂缓，保持未完成，不阻塞本轮重构 |
| `UX-029` | `UX-012` 至 `UX-015` | 集中补齐移动视口启动和布局、无水平溢出或关键重叠、触摸交互、关键工作流、无障碍和视觉回归 | 用户暂缓，非当前队列 |

## 企业级暂缓清单

以下 43 项保持 `[ ]`，但不进入当前执行队列：

| 工作流 | 暂缓任务 |
|---|---|
| 身份与权限 | `AUTH-007` 至 `AUTH-013` |
| 企业数据 | `DATA-008` 至 `DATA-015`、`DATA-017` 至 `DATA-019` |
| 模型治理 | `MODEL-008`、`MODEL-010`、`MODEL-011`、`MODEL-012` |
| 可观测性 | `OBS-008` 至 `OBS-013` |
| RAG 与知识库 | `RAG-013`、`RAG-014`、`RAG-015`、`RAG-017`、`RAG-018`、`RAG-019`、`RAG-020` |
| 部署架构 | `DEPLOY-008`、`DEPLOY-009`、`DEPLOY-010`、`DEPLOY-011`、`DEPLOY-013`、`DEPLOY-014`、`DEPLOY-015`、`DEPLOY-018` |

重新启用企业级任务前，需要先确定身份提供方、真实数据接口、部署环境、容量指标和运维责任边界。
