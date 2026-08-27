# 非企业级 TODO 执行计划

状态基线：`experiment/parallel-platform`，2026-08-26。

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
| 已完成 | 138 | 以各分类 TODO 为准；`REF-004` 已完成 Agent 准备阶段拆分 |
| 当前队列 | 17 | `REF-005` 至 `REF-021` |
| 用户暂缓 | 1 | `UX-029` |
| 企业级暂缓 | 41 | 见本文件末尾分类清单 |
| 可选候选 | 1 | `RAG-024` `OPTIONAL`，不计入主任务统计 |

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
| 10 | `REF-005` | `REF-004` | 工具运行时目录化 | Schema、Registry、Executor 分离，工具行为与业务实现不变 |
| 11 | `REF-006` | `REF-005` | Agent 执行阶段 | Ready Plan、兼容 Loop 与失败传播等价迁移 |
| 12 | `REF-007` | `REF-006` | 通用知识检索阶段 | 查询、过滤、降级披露与引用等价迁移 |
| 13 | `REF-008` | `REF-007` | Agent 综合与结果阶段 | Ready、离线降级、Contract 和结果字段等价迁移 |
| 14 | `REF-009` | `REF-008` | Agent coordinator 收口 | `agent.py` 成为兼容门面，完整质量门通过 |
| 15 | `REF-010` | `REF-009` | API 基础边界 | application、errors、schemas、dependencies 等价迁移 |
| 16 | `REF-011` | `REF-010` | 领域 Router | URL、认证、状态码、响应和 OpenAPI 等价迁移 |
| 17 | `REF-012` | `REF-011` | Chat 与流式服务 | NDJSON、取消、持久化、Session 和遥测不变 |
| 18 | `REF-013` | `REF-012` | `main.py` 收口 | 只保留应用创建、Router 注册和兼容导出 |
| 19 | `REF-014` | `REF-013` | 前端核心层 | state、API、DOM、Toast 和版本检查等价迁移 |
| 20 | `REF-015` | `REF-014` | 前端业务控制器 | 知识、报表、能力和模型设置交互不变 |
| 21 | `REF-016` | `REF-015` | Session 与聊天流 | 增量 Markdown、复制、重试、归档和诊断不变 |
| 22 | `REF-017` | `REF-016` | 布局与启动收口 | `app.js` 成为兼容启动门面，视觉基线不变 |
| 23 | `REF-018` | `REF-017` | 个人知识基础边界 | contracts、metadata、storage 与 ACL 等价迁移 |
| 24 | `REF-019` | `REF-018` | 个人知识处理流程 | Job、抽取器、OCR、入库、重试和删除语义不变 |
| 25 | `REF-020` | `REF-019` | 个人知识查询收口 | 文档、Cursor、FTS、Chunk 与兼容导出不变 |
| 26 | `REF-021` | `REF-020` | 第二梯队只读审计 | 只生成候选计划，不机械拆分、不改代码 |

已完成的 `UX-015` 只覆盖桌面端；移动视口、触摸交互和移动端回归统一由用户暂缓的 `UX-029` 后续处理。

## 当前阶段检查点

### 检查点 E：结构可维护性

`REF-001` 至 `REF-004` 已完成，跨层兼容契约已经冻结。当前从 `REF-005` 开始，按照 Agent、API、桌面前端和个人知识后端四个边界串行拆分，最后只读审计第二梯队；任一任务若产生契约或产品行为差异，不得作为重构完成。

### 检查点 D：上一阶段收口

`DEPLOY-012` 已完成：全部当前任务已标记 `[x]`，GitHub Actions 完整门与分支 required check 已收口。`AGENT-037`、`AGENT-038`、`OBS-017`、`QA-004` 与 `DEPLOY-012` 均是本期已完成的非企业级产品任务。

已完成的检查点 A、B 和 C 及其实测记录保留在 [TODO 执行历史](execution-history.md)。

## 可选候选（不一定需要）

| 任务 | 状态 | 排期 | 候选范围 |
|---|---|---|---|
| `RAG-024` | `OPTIONAL` | 不排期 | 评估是否接入 Ragas；保留现有确定性 Hit Rate/MRR/Source Coverage/Forbidden Hits/ACL/引用页码门，候选观察 Context Precision/Recall、Faithfulness/Response Groundedness、Answer Relevancy、Factual Correctness 和 Noise Sensitivity。评审模型与 embedding 必须固定并显式配置，禁止隐式联网；只有用户明确激活后才转为普通 `[ ]` 并排期。 |

## 用户暂缓（非当前）

| 任务 | 依赖 | 后续范围 | 状态 |
|---|---|---|---|
| `UX-029` | `UX-012` 至 `UX-015` | 集中补齐移动视口启动和布局、无水平溢出或关键重叠、触摸交互、关键工作流、无障碍和视觉回归 | 用户暂缓，非当前队列 |

## 企业级暂缓清单

以下 41 项保持 `[ ]`，但不进入当前执行队列：

| 工作流 | 暂缓任务 |
|---|---|
| 身份与权限 | `AUTH-007` 至 `AUTH-013` |
| 企业数据 | `DATA-008` 至 `DATA-015`、`DATA-017`、`DATA-018` |
| 模型治理 | `MODEL-008`、`MODEL-010`、`MODEL-011`、`MODEL-012` |
| 可观测性 | `OBS-008` 至 `OBS-013` |
| RAG 与知识库 | `RAG-013`、`RAG-014`、`RAG-015`、`RAG-017`、`RAG-018`、`RAG-019`、`RAG-020` |
| 部署架构 | `DEPLOY-008`、`DEPLOY-009`、`DEPLOY-010`、`DEPLOY-011`、`DEPLOY-013`、`DEPLOY-014`、`DEPLOY-015` |

重新启用企业级任务前，需要先确定身份提供方、真实数据接口、部署环境、容量指标和运维责任边界。
