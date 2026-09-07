# 非企业级 TODO 执行计划

状态基线：`experiment/parallel-platform`，2026-09-07。

本计划只安排当前单机样例和产品能力建设。企业 SSO、真实制造系统、分布式数据基础设施、多实例治理、网关和生产部署统一暂缓，未经用户重新确认不进入开发。

任务定义与完成状态的唯一来源是各分类 TODO 中的 `[x]` / `[ ]`。本文件只维护当前执行顺序、依赖、检查点和暂缓边界；已完成的历史顺序见 [TODO 执行历史](execution-history.md)。

## 执行规则

1. 严格按顺序一次只实现一个任务编号，不并行混合多个功能。
2. 开始前确认工作区干净、依赖任务已完成，并记录基线测试结果。
3. 每个任务必须包含实现、针对性测试、必要文档和对应 TODO 状态更新。
4. 一个任务一个提交，提交标题包含任务编号，例如 `feat(UX-015): add desktop visual regression`。
5. 针对性测试通过后才能提交；每个阶段结束时运行完整 Python 回归和已有浏览器回归。
6. 未满足验收门槛时保持 `[ ]`，不得以“主体完成”或“文档完成”代替完成。
7. 发现企业级依赖时先记录阻塞，不扩展本期范围。
8. 发布或标签前，依赖或 Python/FastAPI/SQLite 升级，Schema/API/认证/RAG/流式链路重大变化，或累计约 5 个 feature/fix 后，必须运行完整测试审计。

## 当前状态

| 类型 | 数量 | 任务 |
|---|---:|---|
| 已完成 | 162 | 以各分类 TODO 为准；`QA-005` 至 `QA-009` 已完成 E2E 基础、双通道验证与桌面关键旅程，`REF-023` 已完成 Router 边界收口 |
| 当前队列 | 2 | `QA-010`（本地完整 7-run 已通过、远程验收由用户暂缓，保持未完成），随后 `REF-024` |
| 用户暂缓 | 1 | `UX-029` |
| 企业级暂缓 | 42 | 见本文件末尾分类清单 |
| 可选候选 | 4 | `RAG-024`、`AGENT-039`、`REF-025`、`REF-026` `OPTIONAL`，不计入主任务统计 |

## 当前串行队列

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
| 35 | `REF-024` | `REF-023` | Planner 边界 | 用户已激活，等待 `REF-023` |

已完成的 `UX-015` 只覆盖桌面端；移动视口、触摸交互和移动端回归统一由用户暂缓的 `UX-029` 后续处理。

## 当前阶段检查点

### 检查点 E：结构可维护性

`REF-001` 至 `REF-022` 及 `QA-005` 至 `QA-009` 已完成；Coordinator 的五阶段、依赖快照和单一状态视图已经冻结。用户已激活 `REF-023`、`REF-024`，必须按顺序执行；`REF-025`、`REF-026` 仍为 `OPTIONAL`。`QA-010` 本地完整 7-run 已于 2026-09-04 通过，但远程 Environment/Secret/full 验收于 2026-09-05 由用户暂缓，故仍保持未完成。普通 push/PR 不访问真实模型；必要 Live `provider-matrix` 不替代完整 7-run Live 门，未来发布或打标签前仍必须完成受保护的完整 Live 门；任一任务若产生未批准的产品行为差异，不得作为测试或重构完成。

### 检查点 D：上一阶段收口

`DEPLOY-012` 已完成：全部当前任务已标记 `[x]`，GitHub Actions 完整门与分支 required check 已收口。`AGENT-037`、`AGENT-038`、`OBS-017`、`QA-004` 与 `DEPLOY-012` 均是本期已完成的非企业级产品任务。

已完成的检查点 A、B 和 C 及其实测记录保留在 [TODO 执行历史](execution-history.md)。

## 可选候选（不一定需要）

| 任务 | 状态 | 排期 | 候选范围 |
|---|---|---|---|
| `RAG-024` | `OPTIONAL` | 不排期 | 评估是否接入 Ragas；保留现有确定性 Hit Rate/MRR/Source Coverage/Forbidden Hits/ACL/引用页码门，候选观察 Context Precision/Recall、Faithfulness/Response Groundedness、Answer Relevancy、Factual Correctness 和 Noise Sensitivity。评审模型与 embedding 必须固定并显式配置，禁止隐式联网；只有用户明确激活后才转为普通 `[ ]` 并排期。 |
| `AGENT-039` | `OPTIONAL` | 不排期 | 评估/设计统一 Memory Manager：生命周期采用感官/输入 → 短期/工作 → 长期记忆，长期再分语义、情景、程序；覆盖输入规范化与过滤、状态/上下文预算/checkpoint、长期写入与召回、Writer、Retrieval Gate、Consolidation/冲突与遗忘治理。复用 Session/Context/Plan/Trace、知识/案例/个人知识及 Playbook/Planner/Guard，不重复造 RAG；落实 ACL/租户隔离、来源/置信度、版本/生效期/TTL/删除权，不从日志直接生成记忆、不保存隐藏思维链，程序变更须离线回放/黄金集和人工审批。只有用户明确激活后才转为普通 `[ ]` 并排期，不混入 `REF-006` 至 `REF-021`。 |
| `REF-025` | `OPTIONAL` | 不排期 | 拆分 Answer Synthesizer 的工具 Schema、contracts、解析、声明守卫、渲染和服务编排；冻结工具 Schema 哈希、证据降级、引用、章节顺序、措辞与报告。因其安全敏感，只在继续修改综合规则时激活。 |
| `REF-026` | `OPTIONAL` | 与 `DATA-019` 协调且不排期 | 拆分 SQLite schema、迁移、连接/Session、部门库和缺陷目录边界，保留 `app.database` facade；不实现 Oracle/MySQL Provider、不迁移 Schema。仅在数据库结构或 Provider 工作重启前激活。 |

## 用户暂缓（非当前）

| 任务 | 依赖 | 后续范围 | 状态 |
|---|---|---|---|
| `UX-029` | `UX-012` 至 `UX-015` | 集中补齐移动视口启动和布局、无水平溢出或关键重叠、触摸交互、关键工作流、无障碍和视觉回归 | 用户暂缓，非当前队列 |

## 企业级暂缓清单

以下 42 项保持 `[ ]`，但不进入当前执行队列：

| 工作流 | 暂缓任务 |
|---|---|
| 身份与权限 | `AUTH-007` 至 `AUTH-013` |
| 企业数据 | `DATA-008` 至 `DATA-015`、`DATA-017` 至 `DATA-019` |
| 模型治理 | `MODEL-008`、`MODEL-010`、`MODEL-011`、`MODEL-012` |
| 可观测性 | `OBS-008` 至 `OBS-013` |
| RAG 与知识库 | `RAG-013`、`RAG-014`、`RAG-015`、`RAG-017`、`RAG-018`、`RAG-019`、`RAG-020` |
| 部署架构 | `DEPLOY-008`、`DEPLOY-009`、`DEPLOY-010`、`DEPLOY-011`、`DEPLOY-013`、`DEPLOY-014`、`DEPLOY-015` |

重新启用企业级任务前，需要先确定身份提供方、真实数据接口、部署环境、容量指标和运维责任边界。
