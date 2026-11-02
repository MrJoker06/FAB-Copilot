# MOD-008 工具分批推广与模型 SQL 能力退出

启动：2026-10-26；首批验收：2026-10-27；第二、第三批验收：2026-10-28；第四批验收：2026-10-29；第五批验收：2026-10-30；第六批 F1/F2a 验收：2026-10-31；F2b 验收：2026-11-02。状态：MOD-008 已验证。默认能力、功能/阶段质量复核和第五轮正式迁移性能均通过，三项续作优化及失败记录见末尾；下一项 MOD-009。
前置 MOD-014 已验收，见对应报告。下文 F2a 及更早检查点保留当时的事实；当前默认链路以末尾 F2b 记录为准。

## 首批：Cpk 与传感器诊断工具

按总方案的“分批迁移其余工具、数据 Ports”执行第一个有界批次，迁移 Cpk Ready 场景直接
依赖的 get_process_capability、get_sensor_summary。先在显式 AgentRun/Ready/Loop 中形成
原生调用与可替换来源；不在这一批改变默认全局 TOOLS/TOOL_HANDLERS、规划 SQL 模板、
既有工具版本或冻结行为。任意 SQL 能力的移除及其模型 Schema 版本另列后续批次，不能
声称这一批已解决所有模型 SQL 风险或切换全部默认入口。

| 文件 | 交付 |
| --- | --- |
| manufacturing/process_diagnostics/__init__.py（新） | 无副作用包锚点 |
| contracts.py（新） | ProcessCapabilityInput、SensorSummaryInput、DiagnosticsQuery、DiagnosticsSnapshot、ProcessDiagnosticsPort 及通用 Input/Data/Timeout 错误、输出校验 |
| handler.py（新） | 纯处理器：调用消费方 Port、核对查询/有效 Scope/行级过滤与输出、产生原 ToolResult/来源；不导入报表、SQLite、身份或配置 |
| binding.py（新） | 两个 1.0.0 ToolDefinition、显式 create_process_capability_binding / create_sensor_summary_binding、today 注入和查询前有效 Scope 准备 |
| integrations/manufacturing/fake_process_diagnostics.py（新） | 精确查询夹具，验证主体租户、生成 Fake 来源，不隐式回退 |
| integrations/manufacturing/sqlite_process_diagnostics.py（新） | 只读固定查询；Cpk 只开显式制造库，sensor 只开显式 equipment 库，不附挂其他库 |
| bootstrap/diagnostics_demo.py（新） | --mode ready/loop、Fake 或明确 SQLite 来源的可观察演示，实际复用已验收执行器 |
| execution/tool_result_bridge.py | 修正设备优先假设：来源 Scope 同时声明过程与设备时，两项都投影到 Observation；设备健康只含设备的来源仍按原行为 |
| 专项测试、两份边界清单和结构文档 | 真实源码切片、旧新同夹具数值等价、输入/故障/来源/独立运行与每文件职责 |

contracts 使用冻结 DiagnosticsQuery(kind, start, end, process_step=None, equipment_id=None,
signal_name=None)，kind 仅 capability/sensors，是服务端固定的两种操作，模型无 kind/sql/
表名/列名/排序等自由查询入口。Port 为 fetch(query, principal) → DiagnosticsSnapshot
(query, rows: tuple[dict,...], source: ToolSource)。工具核心分别提供完整输出字段校验及
snapshot.query、source.scope 的精确核对，避免给旧任意字典贴原生标签。

输入兼容现有合法参数：Cpk 为 start/end/process_step，sensor 另含 equipment_id/signal_name；
默认最近 90 天、最大 730 天、结束日包含全天。过程名沿旧实现转大写；sensor 的设备/信号
字符串按旧 SQL 的精确值保留，且 process/equipment/signal 过滤同时生效，不套设备健康的
设备优先规则。原参数不含 null 时的正常调用保持；新增原生边界拒绝未知字段/null/错误类型/
非法日期与范围、坏过程名及非有限输出，旧兼容函数本批不改。

SQLite 固定 SQL/排序/舍入/NULLIF/SQRT 与 manufacturing.reports 的对应函数比较，保持
实际数值与 None 行为。source.scope grain 为 equipment_distribution / equipment_signal，
日期、过程和设备与有效查询一致；signal_name 由 snapshot.query 及输出行核对，Scope 不
伪造不存在的字段。SQLite 路径仅操作员提供，mode=ro/query_only，有限 busy/query timeout、
progress handler、finally close；缺库不创建、不初始化、不改公司 schema，错误不泄露路径。
两库独立配置，当前查询不要求另一个库存在；不引入 Connection Manager 或真实来源配置。

## 验证、范围与回退

按 AGENTS 先审查已有 reports、设备试点、Dispatcher 与本方案，再由 terra_worker 分
不重叠所有权实现；主审等待交付后独立审查/复跑。专项测试：旧新同临时 SQLite 数据数值
完全相等（Cpk 正常/零 sigma/单侧规格/NULL，传感器缺失/异常/信号和联合过滤），Fake
与实际 Dispatcher/Ready/Loop 的合法、拒绝、故障、Scope 和 TOOL 引用；未知 SQL 字段/
工具零查询，主体错配、缺库、不相关库缺失、只读/关闭/期限错误脱敏、无双记账。

仓库外复制现 MOD-014 53 文件加本批七文件，共预计 60 个真实文件；-I -S/空环境/无关
cwd、模块来源清单、持续网络/DB/配置守卫及负向控制，不复制旧 reports/service，不造
initializer，默认全局 Registry 为空。原七单元与 MOD-007 37 文件/1.0.0 清单不改。

运行必要定向集合、Ruff/格式、仓库与新旧模块守卫、旧重构契约、冻结行为 v2、原安装和
闭包回归。本批增加未激活模块，并对共享桥接的有效过滤投影作一处语义修正；不改默认旧
执行热路径，不预设再次正式性能/全量浏览器/覆盖率。桥接专项须同时证明联合过滤保留、
设备健康 Scope 仅含设备时仍剔除未生效的提交过程参数，失败参数仍为空；如实际影响默认
热路径，再单独声明验证，不能沿用本批“不影响默认热路径”的结论。

主要风险为 source.scope 不真实、把 sensor 联合过滤误写为设备优先、Cpk 舍入/NULL 差异、
读取不相关数据库、连接未关闭及以 Fake 结果冒充真实来源。回退仅移除本批新增文件与
清单/文档增量，保留 MOD-001～014 和所有既有工作，不重置工作树、暂存、提交或推送。

## 后续批次（未实施）

其余报告/企业数据/知识工具按消费方契约逐批迁移；规划器的固定 SQL 模板改为具名业务
查询，模型可见与可执行绑定都退出 query_manufacturing_data；列明新能力版本、旧新用例
映射和历史基线的有意差异，不伪装等价重构。之后再验证替换来源及默认调用/兼容入口退出。

## 首批实际交付与审查修订

上述七个新源码文件已落地，两项工具均以原生 ToolDefinition/ToolBinding 进入本地 Registry，
由同一个 Dispatcher/Guard 分别执行 Ready 与固定 Fake 模型 Loop。两模型参数集合中都没有
sql/kind/表名/排序等自由查询字段，未知 SQL 工具与原生参数夹带 sql 分别返回 denied /
invalid_arguments；数据 Port 均不被调用。全局旧 catalog、handlers、默认执行入口未切换。

ProcessDiagnosticsPort 的 Query/Snapshot 归工具消费方所有；处理器核对查询、Source Scope、
行级过程/设备/信号和完整输出字段。Cpk 保留旧排序、ROUND、零/NULL sigma 与负 Cpk；
额外拒绝负 sigma、非有限值和布尔计数。sensor 保留联合精确过滤，允许全部缺失的 NULL
统计，拒绝不完整或倒置的统计范围。原生边界拒绝空白设备/信号或非法过程；旧兼容函数
本批保持原行为，不能把这些原生校验说成对任意旧异常输入都等价。

Fake Adapter 按精确 Query 读取复制后的夹具，明确标识 FAKE 来源。SQLite Adapter 不调用
旧 reports/db_session：只打开当前操作对应的显式库，使用固定参数化 SQL、mode=ro、
query_only、有限 busy/query timeout、progress handler 和 finally close；不 ATTACH、不
创建缺库、不访问另一无关库。路径检查和关闭失败也处于脱敏边界，超时保持专门错误类型。

主审发现 sensor 的 Source Scope 联合过滤会被旧共享桥接的设备优先分支丢弃，已修为按
真实来源保留两项；设备健康自身的 prepare 已消除不生效的过程条件，故其设备优先行为
仍通过对照。没有在 Runtime 按工具名加入新的分派逻辑。

主审还发现初版运行时测试使用 pytest 参数化，项目标准质量门却为 unittest。最终已改为
TestCase/subTest、TemporaryDirectory 和 mock.patch，无新增测试框架依赖；standard module
和 discover 均实际发现四个运行时方法，其内部矩阵覆盖两工具/两模式/两来源。初版 pytest
计数不作为最终门的证据。

## 主审独立验收

环境：WSL Ubuntu-24.04，fab-insight-agent Python 3.11；只使用合成夹具和显式临时 SQLite。

| 项目 | 实际结果 |
| --- | --- |
| 前置最终基线 | MOD-014 r2 的 217 项必要定向、3 项旧回退系统项及正式性能/独立审计已通过 |
| 本批 core / Adapter / bridge 首轮主审 | 16 项通过，0.220 秒 |
| 最终 38 模块必要集合 | **281 项通过，48.177 秒** |
| 本批七新源码、桥接及五测试文件 Ruff/格式 | 13 文件通过 |
| 仓库、新旧模块守卫 | 215 文件 / 0 错误 |
| 冻结行为 v2、旧重构契约 | 通过，冻结行为差异为空 |
| 原七源码单元重建/仓库外闭包与旧 37 文件安装 | 通过，清单及版本未改 |
| 新 60 文件真实源码隔离 | 通过，已包含于必要集合 |

281 是必要定向集合，不是全量测试数；16 项首轮属于该集合，不重复累计。未重跑完整
浏览器、全量覆盖率或正式性能；本批未改变默认旧执行热路径，桥接的有效过滤语义由明确
对照测试验证。此前 MOD-014 的两次性能属于历史验收，不充当本批新增数据源的延迟证明。

测试包括旧/新同临时库的精确数值、排序和 NULL 等价；Cpk 正常/零 sigma/单侧或缺规格、
NULL 测量；sensor 缺失/异常/all-missing/联合过滤及 SQL 字面作为绑定值；两种执行模式的
完整数据/row_count/error、真实 Scope、TOOL:S01 引用；拒绝时零 Port、源故障无回退和单次
Guard 记账；错租户/缺库/无关库、只读/关闭、进度超时与路径错误脱敏。

仓库外复制 MOD-014 的 53 个真实文件加本批七文件，共 60；-I -S、空环境、无关 cwd 下
实际执行 Fake Ready Cpk 与 Fake Loop sensor。网络、DNS、SQLite、配置、旧 service/
reports/settings 等有持续守卫和负向控制；所有 app 模块来源属于显式清单，默认 Registry
保持空。该验证没有伪造 initializer，也没有借用原仓库路径。真实只读 SQLite 在另一组
显式临时库用例验证；不能把 Fake 仓库外证明说成公司数据源已经接通。

当前应用 215 文件（187 Python、28 静态）、28 条精确债务、21 个 DB 调用候选文件、
13 兼容入口/85 静态消费者。新增一个 DB 候选来自显式只读 Adapter。215 个源码文件已与
[精细结构](../current-project-structure.md) 的完整路径表逐项核对，无遗漏、额外项或重复。

证据沿用启动日目录 runtime/quality/mod-008a-20261026-r1/：core-adapter-review.log、
targeted-tests.log、ruff.log、repository-check.log、boundaries.json、refactor-contracts.log、
behavior.json/log、portable-units.log、independent-review.json 和 validation-commands.txt。
旧负向控制中的 usage/error 或 files=1/errors=1 输出属于预期拒绝用例，最终集合为 OK。

尚待后续批次：其余报告/企业数据/知识工具、规划 SQL 的具名查询替代、默认模型可见和
可执行 SQL 能力退出、能力版本与迁移说明。内部会话/Checkpoint 写入仍按 Store/Repository
边界推进，不强制经过模型业务 Tool。首批验收当时未暂存、提交或推送；随后已随 `db4cee6`
同步。第二批基于该提交继续，保留全部前序工作和用户工作簿。

## 第二批生产报表（2026-10-28 已验证）

新增七个源码文件：`app/manufacturing/production_reports/{__init__,contracts,handler,binding}.py`、
`app/integrations/manufacturing/{fake_production_reports,sqlite_production_reports}.py` 与
`app/bootstrap/production_reports_demo.py`。它们提供总览、周良率趋势、制程通过率三个未注册
具名工具，采用消费方 Port、精确 Query Fake 与单库只读 SQLite；Ready 和固定两轮 Loop 都经
Dispatcher。总览良率按晶圆加权，通过率保留 `AVG(pass_flag)`，趋势的产品过滤由完整 Query
验证而不伪造 ToolScope 字段。默认 catalog、旧 SQL 能力和全局绑定未改。当前清单为 222
文件（194 Python、28 静态），DB 候选 22；第二批主审的边界、便携和兼容验收已通过。

### 第二批实施计划与兼容约束

- 契约和处理器位于 production_reports；数据查询经消费方 ProductionReportsPort，SQL 仅位于
  SQLite Adapter。三个原生 Definition 版本为 1.0.0，仅在显式本地装配中启用。
- 总览返回对象（row_count=1），趋势和通过率返回列表；总览使用 COALESCE 完成/开始时间，
  趋势只统计已完成批次，结束日期包含全天。空总览的 SUM/AVG（包括 held_lots）保留 None。
- 良率按晶圆加权；通过率保留 AVG(pass_flag) 对 NULL 的处理，不改成 passed_runs/runs。
  趋势保持 SQLite %Y-%W 分组和原舍入顺序。产品值精确匹配；通过率过程/设备值转大写。
- 产品过滤由完整 Query 与 Snapshot.query 一致性核对；ToolScope 没有 product 字段，
  不伪造产品级授权。原生边界对未知字段、显式 null、错误类型和非法输出更严格，
  这不意味着与旧函数对所有异常输入均等价。
- SQLite 只开显式制造库，mode=ro/query_only、参数绑定、有限 busy/query timeout、
  progress handler 和 finally close；不建缺库、不 ATTACH、不触发全局初始化。
- 验证三个工具 × Fake/临时 SQLite × Ready/Loop 的数据、状态、Scope、引用和单次预算；
  SQL/权限/输入拒绝要求零 Port 调用，来源故障不切换到 Fake。仓库外目标是 67 个真实文件，
  用 -I -S、空环境、无关 cwd、持续守卫与负向控制执行 Fake 双路径。
- 风险集中在 NULL/加权/周分组/日期和有效范围的差异、资源泄漏及隐式旧模块依赖。
  回退只撤销本批七源码及相应清单、测试和文档增量，不重置前序改造或用户文件。

2026-10-28 主审收尾使用 runtime/quality/mod-008b-20261028-r1/；2026-10-27 目录保留为
初步检查，不将初版计数当作最终验收。最终计划为 42 模块必要回归、11 文件 Ruff/格式、
仓库/新旧边界、冻结行为 v2、旧重构契约、七单元和旧 37 文件安装回归。默认热路径未改，
不重复正式性能、全量浏览器或覆盖率；实际通过结果如下。

### 第二批主审修订与实际验收

主审发现初版空总览校验错误地拒绝 held_lots=None；已保留原 SQL，修复原生校验。
另外修复 timeout 参数类型检查、Query 设备类型判断顺序、Schema 属性共享、缺失总览字段
误抛 KeyError，以及演示的固定周编号和用 assert 校验操作员参数。第二轮 Fake 模型明确
要求匹配的工具消息和可解析结果，不能仅凭轮次返回文本。没有修改通用执行器或旧默认路径。

初版运行时测试仅检查成功和单个百分比，不能证明完整结果等价；最终改为明确的完整对象/
列表期望值，逐项核对有效参数、Scope、TOOL:S01、版本/状态和单次 Guard 计数。
未知 SQL/权限拒绝与原生 SQL 参数/非法过程分别断言 denied/authorization 和
invalid_arguments/validation；两模式、两来源均用接口 spy 证明零调用。来源故障只调用一次，
返回脱敏 data_source 错误，不重新执行或切换 Fake。负向用例的预期错误输出不代表质量门失败。

| 主审项目 | 实际结果 |
| --- | --- |
| core / Adapter 独立复跑 | 17 项通过，0.337 秒；属于最终集合，不重复累计 |
| 最终 42 模块必要回归 | **305 项通过，45.695 秒**，含新 24 项及旧 281 项 |
| 七新源码和四测试 Ruff/格式 | 11 文件通过 |
| 仓库与新旧模块守卫 | 222 文件 / 0 错误 |
| 冻结行为 v2、旧重构契约 | 通过；未修改基线、参考 ZIP 或阈值 |
| 七便携单元重建/闭包、原 37 文件安装 | 通过，清单与版本保持不变 |
| 新 67 文件实际源码隔离 | 通过；三个 Fake 工具各运行 Ready/Loop，持续守卫和负向控制有效 |
| 精细结构与默认入口审计 | 222 路径无遗漏/重复；全局容器身份及三个默认 legacy 绑定保留，旧 SQL 仍暴露/绑定 |

新 24 项是标准 unittest 方法数，内部 subTest 覆盖三工具/两来源/两路径、拒绝和故障矩阵；
不是 24 次模型调用。真实 SQLite 数值、舍入、顺序和 NULL 在同一显式临时库上与旧函数
比较，Fake 仅是明确标记的演示。隔离证明没有复制旧 reports 或伪造 initializer；所有加载的
app 模块来源都属于复制清单，默认 Registry 保持空，无配置/数据库/网络依赖。

证据：runtime/quality/mod-008b-20261028-r1/ 下的 validation-commands.txt、review-plan.json、
core-independent.log、targeted-tests.log、ruff.log、format.log、repository-check.log、
boundaries.json/log、refactor-contracts.log、behavior.log、portable-units.log、gate-results.json、
test-result.json 和 independent-review.json；原七制品位于 runtime/portable/mod-008b-20261028-r1/。

截至本批验收仍有 28 条精确依赖债务、22 DB 候选、13 兼容入口/85 消费者。
默认应用未切换到全部原生工具，SQL 退出与能力版本迁移尚未完成；不将本批验收解释为
整个 MOD-008 或公司接入完成。未暂存、提交或推送，用户工作簿保留。

## 第三批运行报表（2026-10-28 已验证）

本批迁移余下三个固定制造报表 get_equipment_productivity、get_defect_pareto、
get_recent_excursions，保持全局旧入口、Planner、冻结基线和 SQL 能力不变。
开工时保留第二批全部未提交改动和用户工作簿；前置第二批四模块 24 项独立回归通过
（1.002 秒），完整 305 项沿用上一批验收记录，不作为本批已通过证据。

| 影响文件 | 预期职责 |
| --- | --- |
| `app/manufacturing/operational_reports/{__init__,contracts,handler,binding}.py` | 三项输入、固定 Query/Snapshot、消费方 OperationalReportsPort、纯处理器、原生 1.0.0 绑定 |
| `app/integrations/manufacturing/fake_operational_reports.py` | 精确查询夹具、租户核对与返回值复制，来源标记 FAKE |
| `app/integrations/manufacturing/sqlite_operational_reports.py` | 固定参数化查询，按操作只打开设备、质量或制造一个显式库 |
| `app/bootstrap/operational_reports_demo.py` | 同一 Dispatcher/Guard 的 Ready 与两阶段 Fake 模型 Loop 可观察演示 |
| 四项专项测试模块、边界清单与进度/结构文档 | 数值、口径、故障和独立运行验收；不扩大产品功能范围 |

SQL 留在技术 Adapter，模型输入只包含具名业务参数。固定 Query 的 kind 由服务端绑定决定，
不进入模型 Schema；不提供表名、列名、排序、连接串或任意表达式。公司真实来源仍未接入。

### 统计与范围约束

- 设备生产率按 interval.start_time 过滤，不改为时间区间重叠；显式 equipment_id 优先于
  process_step，有设备时有效 Query/Scope 消除未执行的制程条件。过程筛选沿原 LIKE 前缀
  语义。原始时长聚合后舍入：舍入后的 recorded_minutes=0.0 不一定意味着原始总时长为零，
  不能据此将合法 productive_pct 改为 None；也不强行求和已分别舍入的组成时长。
- Pareto 保留 GROUP_CONCAT(DISTINCT process_step) 的实际字符串顺序，不对其排序重写。
  share_pct 的窗口分母在 LIMIT 前计算，Top N 的份额和可以小于 100%，不重新归一化。
  全零缺陷数的份额保留 None。默认 limit=10，上限 25。
- 最近异常同时应用 process_step 与 equipment_id，不套生产率的设备优先规则；保留时间
  降序、包含结束日全天和 IS NOT NULL（空字符串代码仍符合旧条件）。默认 limit=20，上限 100。
  测量值/规格可空，measurement_unit 可为空串，合法负测量值不改写。
- 原生输入拒绝未知字段、显式 null、错误类型、无效过程或越界 limit；旧函数的越界 limit
  clamp 行为本批不改。这是严格原生边界，不声称对旧异常输入等价。
- Source Scope 仅声明实际生效的租户/日期/过程/设备和业务粒度；不把返回的批次 ID 伪装成
  查询时已执行的批次权限过滤。Snapshot.query 与实际查询精确核对。

### 验收与回退计划

同一临时库与旧函数对照三个工具的完整结果、排序、舍入、NULL、联合/优先过滤、窗口分母
及 LIMIT；三个相关库独立，缺少无关库仍可查询，缺少相关库不创建、不初始化或回退。
检查只读 URI/query_only、参数绑定、有限 busy/query timeout、progress、连接释放及错误脱敏。

三个工具 × Fake/SQLite × Ready/Loop 核对明确的完整输出、版本、有效参数、Scope、引用和
单次预算；两种模式拒绝旧 SQL/夹带 SQL/非法 limit/权限错误时证明零 Port 调用。
来源失败保持失败，不切换来源。仓库外目标为 74 个真实文件（前批 67 加本批 7），采用
-I -S、空环境、无关 cwd、持续 DB/网络/配置/旧模块守卫及负向控制运行六条 Fake 路径。

必要门为专项/共享执行器回归、Ruff/格式、仓库和模块守卫、旧重构契约、冻结行为 v2、
原七便携单元及 37 文件安装回归。默认热路径未改，不重复正式性能、全量浏览器或覆盖率。
证据目录 runtime/quality/mod-008c-20261028-r1/；具体通过数必须在执行后记录。
风险是有效范围错投影、舍入或窗口口径变化、无关库依赖、初始化副作用及失败回退；
回退只撤销本批七源码、专项测试和清单/文档增量，保留第二批、历史记录和用户文件。

### 第三批主审修订与实际验收

上述七个源码文件及四个标准 unittest 模块已落地。按 AGENTS 分配不重叠所有权给
terra_worker，实现中断后检查实际工作树再续作，主审等待交付后独立检查源码和复跑必要门。
不把中断前的初步测试计数、实现说明或文档状态当作最终验收。

主审修复 Query limit 将布尔/浮点当整数、错误类型抛 TypeError、直接 Input(limit=None)
绕过检查的问题；生产率先验证提交的过程值，再执行设备优先消除条件，保持 Schema 与
实际解析一致。行级过程前缀核对匹配 SQLite LIKE 的 ASCII 大小写语义；异常时间戳必须
完整可解析，不能仅凭前十位日期放行。Pareto 过程集合校验不改变原字符串顺序。
合法的零舍入时长/100% 生产率、零缺陷份额 None、空字符串异常代码与可空测量值均保留。

初版运行时拒绝测试只走 Fake，SQLite 只核对数据；最终补为两来源/两模式的明确状态、
错误类别和零接口 spy 证明，以及 SQLite 完整 Scope、有效参数、模型轮次和预算断言。
最近异常增加“同设备其他过程”和“同过程其他设备”反例，证明联合过滤真实生效；
生产率输入合法矛盾过程/设备时，来源和 Observation 只保留真正生效的设备条件。
所有相关库缺失、执行/关闭失败、超时及超时同时关闭失败均有明确结果，来源故障不回退。

| 主审项目 | 实际结果 |
| --- | --- |
| 最终 46 模块必要回归 | **328 项通过，47.389 秒**，含前批 305 项和新增 23 项 |
| 本批七源码、四测试 Ruff/格式 | 11 文件通过 |
| 仓库、新旧模块守卫 | 229 文件 / 0 错误 |
| 冻结行为 v2、旧重构契约 | 通过；基线、参考 ZIP 和性能阈值未改 |
| 原七便携单元、旧 37 文件安装 | 通过，清单和版本不变 |
| 新 74 文件真实源码隔离 | 三工具各运行 Fake Ready/Loop；持续守卫、分类负向控制、模块来源与空默认 Registry 通过 |
| 结构与兼容审计 | 229 文件（201 Python/28 静态）、28 债务、23 DB 候选、13 入口/85 消费者；源码表无遗漏/重复 |
| 既有工作保留 | 第二批 11 源码/测试与开工副本逐字节相同；默认 Runtime/catalog/bindings/reports/Planner 未改，全局容器身份保持 |

23 项指 unittest 方法数，内部 subTest 覆盖三工具/两来源/两模式、过滤、拒绝和故障。
只用合成临时 SQLite 与标记为 FAKE 的演示，不调用真实公司来源或外部模型。74 文件证明
没有借用原仓库源码、伪造 initializer 或在 import 时读配置/连接数据库；实际 SQLite 查询
由独立临时库矩阵验收，不声称在禁止 SQLite 的隔离进程中执行了真实数据库查询。
测试输出中的预期 usage/error、files=1/errors=1 等负向控制不代表最终集合失败。

证据位于 runtime/quality/mod-008c-20261028-r1/：validation-commands.txt、review-plan.json、
targeted-tests.log、ruff.log、format.log、repository-check.log、boundaries.json/log、
refactor-contracts.log、behavior.log、portable-units.log、gate-results.json、
inventory-precheck.json 和 independent-review.json。demo-ready.json/demo-loop.json 保存实际
Fake 演示输出；retained-batch-b/ 是未改动的前批验收源码/测试副本，不是新的发布制品。
原七重建制品位于 runtime/portable/mod-008c-20261028-r1/。

截至本批，九个固定制造报表均有显式原生路径，默认应用仍使用旧绑定。后续继续企业数据/
知识工具，具名业务查询替换旧 SQL、能力/Schema 版本迁移与默认路径切换；不将本批通过
标为 MOD-008 整体完成。未重复正式性能、浏览器完整门或覆盖率，未暂存/提交/推送，
保留用户工作簿。

## 第四批企业数据工具（2026-10-29 已验证；2026-10-28 启动）

本批迁移 get_enterprise_data_manifest、get_enterprise_fab_summary、query_enterprise_data。
开工保留第二、第三批未提交源码/测试和用户工作簿；第三批及旧 Provider/便携契约的前置
30 项回归通过（3.205 秒），此前完整 328 项仍是第三批历史证据，不充当本批验收。

| 影响文件 | 预期职责 |
| --- | --- |
| `app/manufacturing/enterprise_tools/{__init__,contracts,handler,binding}.py` | 业务输入、可信时间配置、固定 Query/Snapshot、消费方 Port、结果校验及原生绑定 |
| `app/integrations/manufacturing/fake_enterprise_tools.py` | 精确查询与嵌套夹具深复制，来源明确标记 FAKE |
| `app/integrations/manufacturing/provider_enterprise_tools.py` | 显式注入已有 EnterpriseDataProvider Protocol，固定调用 manifest/summary/page；不选择全局 Provider |
| `app/bootstrap/enterprise_tools_demo.py` | Ready/Loop 与 Fake/显式夹具 Provider 的可观察演示 |
| 四个专项测试、边界清单与进度/结构文档 | 旧模拟器完整输出对照、拒绝/失败/来源语义、仓库外独立执行 |

### 数据口径、时间与兼容约束

- 使用冻结的 EnterpriseWindow(as_of, retention_days=730, summary_default_days=90)；汇总默认
  90 天，样本默认源保留期 730 天，按配置裁剪有效范围。prepare 和 handler 使用同一配置，
  不重复读墙钟；原始省略的筛选参数仍省略，不把默认日期写进源请求而改变模拟器输出键。
- Query 保留规范化后的实际输入及有效时间范围。模型仅接受固定实体与结构化字段，
  不接受 SQL、任意 DSL、Provider 名称、连接串、URL 或 cursor。跨实体无效字段直接拒绝；
  lots 支持 product/status，process-runs 支持 process/equipment，sensor-events 另支持 signal。
- manifest 的 Provider API 分页上限（现有模拟源为 500）与模型工具样本上限 50 分开。
  query_enterprise_data 仍仅请求第一页 cursor=None，保留源返回的不透明 next_cursor 元数据，
  不增加模型续页能力。样本不能代表全量统计，不把 estimated_total 改成 records 数量。
- 三个结果保持对象 envelope，框架 row_count=1；样本记录数量由 page.count 与 records 长度
  单独验证，并受请求 limit≤50 限制。保留模拟标记、deterministic_projection/exact=False、
  分类与血缘，不把模拟推算或有限样本标为真实观测。
- Source Scope 声明实际租户、有效日期及联合生效的过程/设备。product/status/signal 不伪造
  为通用 Scope 中不存在的授权维度，改由 Query、返回筛选元数据及记录逐项核对。
- 原生边界拒绝显式 null、错误类型、非法实体/组合/limit 和有效窗口无交集；旧兼容函数
  的 clamp、忽略跨实体字段、空时间窗口输出及最小 Provider dict 行为保留。本批不声称
  对全部旧异常输入或未满足业务输出契约的任意自定义 Provider 等价。
- 复用原有纯 EnterpriseDataProvider Protocol；新 Adapter 不导入旧 enterprise_data、全局
  身份或配置。现有模拟算法与游标签名不改、不复制到新模块，不新增 SHA-256 校验机制。
  显式 Provider 错误不回退到默认模拟器，租户错误必须在调用 Provider 前拒绝。

### 验收与回退计划

在测试中显式构造原有 SyntheticFabProvider，注入固定设置和日期，与旧包装函数比较三个
工具及三种样本实体的完整对象、数量/口径、筛选、血缘和分页元数据；旧模块仅在此独立
对照测试使用，新执行链和演示不依赖它。另验证协议调用、主体对象传递、嵌套复制、源故障、
超时和头部/行级租户/Provider/范围/模拟标记不一致的拒绝。

三个工具 × 两种显式来源 × Ready/Loop 验证完整结果、Scope、有效参数、版本、TOOL:S01、
单次 Guard 和模型轮次；SQL/cursor/非法实体/字段/limit/权限拒绝时证明零 Port/Provider 调用。
仓库外目标 82 个真实文件（前三批 74、本批 7、既有 data_contracts.py 1），以 -I -S、
空环境、无关 cwd、持续 DB/网络/配置/旧模块守卫和负向控制实际执行，不伪造 initializer。

必要门为 52 模块回归、本批 11 文件 Ruff/格式、仓库和模块守卫、冻结行为、旧重构契约、
原七单元和旧 37 文件安装。证据目录 runtime/quality/mod-008d-20261028-r1/；不重复正式
性能、浏览器完整门或覆盖率。主要风险是时间默认值改变源请求、样本误当统计、跨租户/
错误范围结果、元数据不诚实和隐式 Provider 回退。回退只撤销本批新增源码/测试及清单/
文档增量，保留既有改造；不实际接入公司来源、不更换当前默认工具链或退出 SQL 能力。

### 第四批主审修订与实际验收

七个源码文件和四个标准 unittest 模块已落地。三个原生 1.0.0 绑定经同一 Dispatcher/Guard
实际运行 Ready 与两轮固定模型 Loop。EnterpriseDataPort 由消费方持有；Provider Adapter
只调用显式注入的 manifest/summary/page，不选择全局 Provider，也不在故障时切换来源。
演示的 Provider 是内存夹具，来源仍标记 FAKE，不代表公司账号或报表 API 已接通。

主审发现初版核心测试使用 pytest，标准 unittest 不会收录，已改为 TestCase/subTest。
同时补齐嵌套业务字段、模拟统计/分类/血缘、实际查询与 Source Scope、记录级日期/租户/
筛选/模拟标记校验；先验证完整结构再读取嵌套字段，复制或来源错误脱敏。输入严格拒绝
非 YYYY-MM-DD、不可哈希实体、布尔 limit、未知参数和跨实体字段。模拟 manifest 的分页
策略改为诚实的 opaque_fixture_cursor；旧 Synthetic 的签名游标和算法原样保留。

三个工具及三类样本在 Fake/Provider fixture × Ready/Loop 下比较独立写明的完整输出、完整
Scope、TOOL:S01、Loop 工具消息、版本与单次预算。SQL/cursor/非法实体/字段/过程/limit/
角色/租户拒绝均以两个 Adapter 和底层 Provider 的 spy 证明零调用。两来源故障均只调用
一次、无回退；Provider 超时和一般错误另有明确脱敏对照。模拟样本 page.count、请求上限、
estimated_total 与 envelope row_count=1 分开验证，不把样本改写为全量统计。

| 主审项目 | 实际结果 |
| --- | --- |
| 核心与 Adapter 独立复跑 | 12 项通过，0.009 秒；属于最终集合，不重复累计 |
| 最终 52 模块必要回归 | **354 项通过，182.717 秒**；新增 19 项，另含前批 328 项及原有企业边界/便携契约 7 项 |
| 补充异常来源检查 | 47 个直接调用检查通过；不是新增 unittest 数，不计入 354 |
| 本批七源码、四测试 Ruff/格式 | 11 文件通过 |
| 仓库、新旧模块边界 | 236 文件 / 0 错误 |
| 冻结行为 v2、旧重构契约 | 通过；基线、参考制品和阈值未改 |
| 原七便携单元、旧 37 文件安装 | 通过，清单和版本保持不变 |
| 新 82 文件真实源码隔离 | 三工具 Fake Ready/Loop 及 Provider 样本实际执行；持续守卫、负向控制、模块来源、空默认 Registry 通过 |
| 结构与兼容审计 | 236 文件（208 Python/28 静态）、28 债务、23 DB 候选、13 入口/85 消费者；源码表无遗漏/重复 |
| 既有工作保留 | 第二、第三批 22 源码/测试与开工副本逐字节相同；默认 Runtime/catalog/bindings/reports/Planner、旧企业模块和纯 Provider Protocol 未改 |

82 文件由前三批 74、本批七源码和既有 data_contracts.py 组成；没有复制旧 enterprise_data
或伪造 initializer。仓库外 -I -S/空环境/无关 cwd 中持续阻断旧模块、设置、身份、网络/DNS、
SQLite 与环境遍历，并通过故意触发验证守卫有效；所有加载的 app 模块都来自显式清单，
原仓库不在 sys.path。完整旧模拟器对照在单独测试进程中注入固定设置/日期进行，不混入
隔离演示；这也不是实际公司来源的性能或权限验收。

证据沿用启动目录 runtime/quality/mod-008d-20261028-r1/：review-plan.json、
validation-commands.txt、targeted-tests.log、ruff.log、format.log、repository-check.log、
boundaries.json/log、refactor-contracts.log、behavior.log、portable-units.log、gate-results.json、
core-independent.json、default-registry-audit.json、final-worktree-audit.json 和 independent-review.json。
demo-ready.json/demo-loop.json 保存实际演示输出；retained-batches/ 保存前两批审计副本。
原七重建制品位于 runtime/portable/mod-008d-20261028-r1/。预期 usage/error、重复 ZIP 成员与
files=1/errors=1 是已有负向用例的输出，最终集合为 OK。

本批没有改变默认旧执行热路径，未重复正式性能、完整浏览器或覆盖率。当前四十个项目
改动文件包含第二至第四批未提交工作；未暂存、提交或推送，保留用户工作簿。所有变更文本
为 UTF-8/LF。默认企业工具仍为 LegacyBindingAdapter，全局 TOOLS/TOOL_HANDLERS 对象
身份不变，旧 SQL 仍可见且绑定。下一批继续知识工具，再做具名查询替代、能力版本迁移及
默认入口切换；MOD-008 整体、MOD-009、真实公司接入和 SQL 退出均不能据此标为完成。

## 第五批知识工具（2026-10-30 已验证；2026-10-29 启动）

本批迁移联合检索工具 search_knowledge，保留 personal/knowledge/case 三类来源、引用标识、
元数据重排和来源多样性。开工保留第二至第四批全部未提交改动及用户工作簿，33 个既有
源码/测试文件已复制为逐字节审计副本；第四批 354 项为历史证据，不代替本批验收。

| 影响文件 | 计划职责 |
| --- | --- |
| `app/knowledge/search_policy.py`（新） | 从旧 rag 抽出相同的查询推断与过程扩展规则；不接配置、身份或数据库 |
| `app/knowledge/search_tool/{__init__,contracts,handler,binding}.py`（新） | 具名输入、消费方 Query/Snapshot/Port、候选/结果校验、纯处理器与原生 1.0.0 绑定 |
| `app/integrations/knowledge/{__init__,fake_search,backend_search}.py`（新） | 精确 Fake、显式 FactorySearchBackend/个人搜索 Port 组合，租户/owner 核对与错误脱敏 |
| `app/bootstrap/knowledge_search_demo.py`（新） | 同一 Dispatcher/Guard 的 Ready/Loop，Fake 或显式内存后端演示 |
| `app/knowledge/rag.py` | 仅导入/兼容导出被抽出的相同规则，保留旧签名、默认来源选择和调用链 |
| 四个标准 unittest 模块、两份边界清单及进度/结构文档 | 完整结果对照、来源/owner/失败语义、独立运行和源码职责 |

输入只允许 query/limit/process_step/equipment_id/defect_type/source_types；不能由模型指定
owner、租户、后端、SQL 或 cursor。limit 为 1～10 的非布尔整数，来源仅三类且不可空；空白或
不可分词的查询保留成功空结果、零数据源调用。原生边界对错误类型、显式 null 和非法枚举
更严格；不声称对旧 clamp/异常参数行为均等价。旧 SQL 工具与全局绑定本批保持不变。

Owner 根据可信 default_tenant_id 与 principal 的 tenant/user 计算，保持默认租户 user_id、
其他租户 tenant:user 的原映射；不读取会触发设置访问的 Principal.knowledge_owner_id 属性。
个人检索通过独立 Port 接收该 owner，返回 owner envelope 必须一致；缺少被请求的个人来源
应明确失败，不隐式降为只检索工厂。工厂来源保留 Active/Validated，个人来源保留当前用户
范围；别名、候选、Snapshot 主体和可选行级 owner/tenant 不一致均须拒绝，不拼接其他用户数据。

设备/缺陷是排序焦点，并非严格行过滤；process 的 ALL/未知个人元数据也保留原排序语义。
因此 ToolSource Scope 只声明租户和 knowledge_search 粒度，不伪造设备/制程/日期级权限。
查询焦点留在完整 Query 和 retrieval.filters 中；Source 记录实际咨询的检索后端，不替代每条
结果的 reference_id。当前组合按旧规则获取工厂别名与候选，再按最终来源选择重排；即使仅
选 personal，也不能将其解释为独立的个人库部署制品或工厂配置已经退出。

新 Adapter 不导入旧 rag、后端选择器、SQLite 实现、个人 service、配置或全局身份；复用纯
FactorySearchBackend/Request。业务重排复用原 ranking.py，保留现有日历日期的案例衰减，
不改打分公式。只抽出相同推断函数，不复制另一份演进规则，也不改变默认工具激活状态。
业务工具模块新增对纯 knowledge 规则/契约的明确依赖；纯模块守卫同时禁止反向导入旧
facade/registry/SQLite/service，不能通过放宽规则把技术实现重新带回核心。

计划运行 61 模块必要集合（前批 52、既有知识边界/契约/决策/规则五模块及本批四模块）、
隔离临时库 RAG gold、Ruff/格式、仓库/模块守卫、冻结行为、旧兼容契约、原七便携单元及
37 文件安装回归。新知识切片目标为 66 个真实文件（原 Loop 53 + 本批 9 + 既有知识四文件），
不依赖第二至第四批制造/企业工具源码；-I -S/空环境/仓库外运行两来源 Ready/Loop，持续
阻断旧模块、配置/身份、网络/DNS、SQLite 与环境遍历，带负向控制和空默认 Registry 审计。

证据目录 runtime/quality/mod-008e-20261029-r1/。主要风险为 owner 映射错误、把排序参数
当成 ACL、重排/来源多样性漂移、查询在拒绝前访问来源及出错后隐式降级。回退仅撤销本批
新增文件、rag 的纯规则导入和清单/文档增量，保留前批工作。实际通过数见下文验收记录；
本批不接真实公司/外部模型，不新增 SHA-256，不暂存/提交/推送，不预设全量浏览器、覆盖率
或正式性能重跑；抽取之外若出现默认热路径行为变化，须重新声明相应验证范围。

### 第五批主审修订与实际验收

九个新源码文件、四个标准 unittest 模块及 rag 的最小纯规则导入已落地。主审按 AGENTS
审查后交由 terra_worker 实现，额度中断后检查实际文件继续收尾；未把中断前的交付说明或
局部测试当作最终验收。主审最终独立复跑，实际结果如下。

| 主审项目 | 实际结果 |
| --- | --- |
| 最终 61 模块必要回归 | **413 项通过，118.380 秒**；前批 354 项、既有知识专项 30 项及本批新增 29 项 |
| 旧新检索完整对象对照 | 70 组通过，包含于 Adapter 测试；五种查询/limit/焦点 × 七个来源组合 × 两种租户 owner |
| RAG gold | 15/15；hit/source coverage/MRR 均为 1.0，禁止引用 0；全部在隔离临时合成库执行 |
| 66 文件真实源码隔离 | Fake/Backend fixture 各执行 Ready/Loop，共四条路径；持续守卫、负向控制、模块来源与空默认 Registry 通过 |
| 新九源码、四测试 Ruff/格式 | 13 文件通过；旧 rag 单独基线比较，保留原 I001/TRY004 两项、无新增诊断 |
| 旧 facade 纯规则抽取审计 | 10 个保留函数 AST 不变，抽出的推断函数体与两组常量一致；旧排序模块未改 |
| 仓库与新旧边界 | 245 文件 / 0 错误；五条精确公共工具契约导入及九类禁止导入反向验证通过 |
| 冻结行为 v2、旧重构契约 | 通过；基线、参考制品和阈值未改 |
| 原七便携单元及旧 37 文件安装 | 通过，既有清单和版本不变 |
| 主审额外来源故障审计 | 工厂/个人来源 × Ready/Loop 四组通过：Backend 一次、故障阶段一次、Fake 零次；不计入 413 项 |
| 结构与兼容审计 | 245 文件（217 Python/28 静态）、28 债务、23 DB 候选、13 兼容入口/85 消费者；逐文件结构无遗漏/重复 |
| 既有工作保留 | 第二至第四批 33 个源码/测试与开工副本逐字节相同；默认 Runtime、Planner、工具全局绑定及所有既有数据后端未改 |

主审修复了非法参数时 Backend 演示被替换成 Fake 的问题：现在拒绝路径仍保留用户指定的
Adapter，两个 Adapter 和底层别名/工厂/个人来源均以 spy 验证零调用。角色、租户、用户及
未知 SQL 工具明确 denied/authorization，错误参数明确 invalid_arguments/validation，不能
以任意一种失败状态通过。空白/不可分词输入在两来源、两执行模式下均成功返回 []、0 行、
无 Source 且零来源调用；只对该分支准备裸 tenant Scope，以适配既有 Dispatcher，无需修改
共享执行器。正常检索仍准备 knowledge_search 粒度。

候选校验新增整个对象的 JSON 安全与有限数值约束、authority/confidence 范围，以及主体/
owner/Source Scope 核对。知识/案例候选不能夹带私有 owner 字段冒充公共资料；业务文档的
owner 作者字段仍保留。个人 user_id 对应原 user，owner_user_id 等字段对应解析后的 owner，
非默认租户的两者不得混淆。显式错误元数据按数据源失败处理，不通过排序时丢弃来掩盖。
个人来源缺失、批次类型/owner/tenant 错误，以及各阶段内置/类型化超时均明确失败且脱敏。

61 模块首轮曾通过 412 项，但随后真实仓库门拒绝了新知识工具引用公共 ToolSystem 类型：
旧守卫将其归到 knowledge 域。该次 repository-check-r1.log、targeted-tests-r1.log 和
gate-results-r1.json 原样保留。修订仅登记 binding/contracts/handler 到三个公共工具契约/
定义模块的五条精确边，不开放 knowledge 对整个 Runtime 的依赖；新增一项守卫测试，确认
Runtime 实现、全局 registry、设置、身份、旧 RAG/registry、数据库及 socket 九类导入仍拒绝。
最终修订后的 413 项与所有兼容门通过；未修改检查器代码、通配放行或新增依赖债务。

证据沿用启动目录 runtime/quality/mod-008e-20261029-r1/：implementation-plan.txt、
review-plan.json、validation-commands.txt、targeted-tests.log、ruff.log、format.log、
legacy-policy-audit.json/log、legacy-rag-ruff-before/after.json、rag-gold.log、
repository-check.log、boundaries.json/log、refactor-contracts.log、behavior.log、portable-units.log、
gate-results.json、source-fault-independent.json、default-registry-audit.json、
inventory-precheck.json、final-worktree-audit.json 与 independent-review.json。
demo-ready.json/demo-loop.json 保存完整结果、Scope、TOOL 消息和预算；demo-sql-denied.json
保存本地拒绝 SQL 的实际演示。demo-commands.txt 可复现；retained-batches/ 是前批审计副本，
原七重建制品位于 runtime/portable/mod-008e-20261029-r1/。预期 usage/error、重复 ZIP 成员等
负向输出不代表最终测试失败。

本批默认旧热路径只做相同规则的抽取，未激活全部原生工具；未重复正式性能、完整浏览器或
覆盖率。当前 54 个项目改动文件包含第二至第五批工作，未暂存/提交/推送；工作簿保留，
变更文本均为 UTF-8/LF。默认 14 个业务工具绑定仍是 LegacyBindingAdapter，TOOLS/
TOOL_HANDLERS 对象身份不变；默认 SQL 仍可见且绑定，不能把本地 SQL 拒绝解释为全局退出。

下一批进入实际 Planner 用例的具名查询替代、SQL 能力退出与能力/Schema 版本迁移，再完成
默认装配切换和兼容入口收口。知识目录、上传/索引写入、应用内部 Store/Repository、真实公司
Adapter、完整模型生命周期与 Skill/Checkpoint 不在本批验收范围；MOD-008 整体仍进行中。

## 第六批 F1：Planner 固定 SQL 的具名替代能力（2026-10-31 已验证；2026-10-30 启动）

本批先补齐八项具名工具并独立验收，F2 再切换 Planner、证据语义与默认能力版本，并退出
模型 SQL。六类证据需求实际展开八条 SQL；不能只用已有的最近异常工具替代所有明细，因为
列集、排序、过滤及批次全历史口径不同。当前仅增加未默认激活的原生路径，SQL 全局退出
仍未完成。开工保留前批 54 个项目改动和工作簿，47 个源码/测试已存逐字节审计副本。

| 原证据与固定模板 | 新工具名 / 内部 kind | 来源与有效范围 |
| --- | --- | --- |
| YLD-02 产品/技术节点良率分层 | get_product_yield_breakdown / product_yield | 制造库 lots，complete_time 日期、可选精确产品；按晶圆加权 SUM，非批次良率 AVG |
| EQP-03 设备事件时间线 | get_equipment_event_timeline / equipment_events | 设备库 equipment_events，event_time 日期和可选设备 |
| EQP-04 设备关联产品异常 | get_equipment_excursion_history / equipment_excursions | 制造库 process_runs，run_time 日期、设备/过程联合过滤，保留 IS NOT NULL |
| LOT-01 批次身份 | get_lot_identity / lot_identity | 制造库 lots，精确 lot_id，无日期过滤，原 LIMIT 10 |
| LOT-02 批次加工路线 | get_lot_process_history / lot_process_history | 制造库 process_runs，精确 lot_id，全历史 operation_seq/run_time 排序 |
| LOT-03[0] 批次制程异常 | get_lot_excursion_history / lot_excursions | 制造库 process_runs，精确 lot_id，全历史异常，按 operation_seq/run_time 排序 |
| LOT-03[1] 批次缺陷处置 | get_lot_defect_history / lot_defects | 质量库 defect_records，精确 lot_id，全历史 detected_time 排序 |
| LOT-03[2] 批次晶圆图模式 | get_lot_wafer_map_patterns / lot_wafer_maps | 质量库 wafer_maps，精确 lot_id，全历史 wafer_no 排序，不返回 map_seed |

七个新源码为 manufacturing/named_queries 的包锚点、contracts/handler/binding，
integrations/manufacturing 的 fake_named_queries/sqlite_named_queries，以及
bootstrap/named_queries_demo。四个标准 unittest 模块负责核心、Adapter、运行时和仓库外
隔离。原 planning_runtime/queries.py、steps/scope、Playbook、Evidence、默认 catalog/bindings
与既有各批文件均不在本批修改范围。

输入有产品良率、设备事件、设备异常和批次四类，模型只填具名字段，不接收 kind、SQL、
表/列/排序、任意模板、limit 或 cursor。kind 仅由服务器的 ToolDefinition/Binding 决定。
日期采用固定 as_of 配置、省略时近 90 天，严格 YYYY-MM-DD，最大跨度沿现有报告 730 天差；
不裁剪到当前日或所谓保留期。结束日通过下一日排他边界包含全天。批次五工具没有日期
参数，Scope 日期必须为空；不能把 Router 默认时间窗硬套到全历史批次记录上。

保留产品/设备/批次的精确字符串匹配，过程值校验后转大写。SQL 外观的 ID 仍是参数值，
不能通过拼接执行；空值、非法日期/类型、未知字段和跨工具字段在 Port 前拒绝。输出保持
旧 SELECT 的完整列集、排序、空/NULL、负测量值、空字符串异常码和固定行数上限；不添加
隐藏模拟真值列，也不在核心重新聚合。ToolScope 只声明实际日期/设备/过程或批次；产品
由 Query 和返回行核对，不伪造通用 Scope 中没有的维度。

消费方 NamedQueryPort 接收固定 Query，返回 Snapshot/query/rows/source；处理器核对完整
结果和实际范围、深复制并返回列表 ToolResult。Fake 仅匹配精确查询。只读 SQLite Adapter
每次只打开三条显式路径中相关的一库，URI mode=ro、query_only、有限 busy/progress 期限及
finally close；缺库不创建，无初始化/seed/ATTACH，无旧 reports/db_session、配置或身份依赖，
失败和超时脱敏，不切换其他来源。新增一个 DB 候选须经实际源码审查再更新台账。

验收计划：同一显式临时库上，八项新处理器结果与旧 Planner 真实模板经 safe_select 的完整
对象比较；覆盖加权分母、日期末日、产品大小写、全历史批次、联合筛选、排序/上限、空/NULL、
参数绑定、相关库独立、只读/连接释放/期限/关闭故障。八工具 × Fake/SQLite × Ready/Loop
共 32 条主路径核对完整结果、Scope、TOOL:S01、工具消息及单次预算；非法输入和权限拒绝
证明零 Port/连接，来源故障只执行一次，无回退。无效输入也保留指定的 Adapter。

目标仓库外切片为 60 个真实文件（原 Loop 53 加本批七个），不依赖第二至第五批新工具；
-I -S/空环境/无关 cwd，持续旧模块/配置/身份/DB/网络/DNS/环境遍历守卫与负向控制，运行
八个 Fake 工具各 Ready/Loop；SQLite 查询在另一组显式临时库验证。默认 Registry 保持空，
不伪造 initializer，所有加载的 app 模块来源属于复制清单。

必要门为前批 61 加本批四个，共 65 模块；本批 11 文件 Ruff/格式、仓库/新旧边界、冻结行为、
旧重构契约、原七便携单元和旧 37 文件安装。证据目录 runtime/quality/mod-008f1-20261030-r1/。
F1 为未激活新增路径，不重跑正式性能、全量浏览器或覆盖率。主要风险是丢失全历史范围、
列集/排序/分母变动、错开其他库、拼接参数或来源回退；回退仅撤销 F1 新文件与文档/清单
增量，保留前批工作。实际通过数见下文验收记录；不接公司来源，不新增 SHA-256，不暂存、
提交或推送，不将 F1 通过标为整个 MOD-008 或模型 SQL 退出完成。

### F1 主审修订与实际验收

上述七个源码和四个标准 unittest 模块已交付。AGENTS 要求的计划、委派与独立审查已执行；
子代理额度中断后，主审接手剩余运行时/隔离测试和少量夹具修订，未把未完成的 32 路矩阵、
无守卫的源码复制或中断前局部计数标为验收通过。最终统一复跑结果如下。

| 主审项目 | 实际结果 |
| --- | --- |
| 四模块独立预检 | 18 项通过，1.456 秒；属于最终集合，不重复累计 |
| 最终 65 模块必要回归 | **431 项通过，64.487 秒**；前批 413 项加本批 18 项 |
| 八项旧模板完整对象对照 | 通过：实际 _manufacturing_queries 输出经旧 safe_select，与新 SQLite Snapshot 和 Handler 的完整结果比较；包含于 Adapter 测试 |
| 运行时 32 条主路径 | 八工具 × Fake/临时 SQLite × Ready/Loop；完整结果、Scope、类型/版本、引用、工具消息、单次预算与模型轮次通过 |
| 空结果与拒绝/故障矩阵 | 空列表保留咨询来源；错误参数/权限/旧 SQL 工具明确拒绝且零 Port/连接；失败/超时单次执行、不回退、错误脱敏 |
| 新 60 文件真实源码隔离 | 八个 Fake 工具各 Ready/Loop，共 16 条路径；持续守卫、分类负向控制、来源清单和空默认 Registry 通过 |
| 七源码、四测试 Ruff/格式 | 11 文件通过 |
| 仓库、新旧模块边界 | 252 文件 / 0 错误 |
| 冻结行为 v2、旧重构契约 | 通过，参考制品、基线和阈值未改 |
| 七便携单元重建及旧 37 文件安装 | 通过，既有清单和版本不变 |
| 结构及存储台账 | 252 文件（224 Python/28 静态）、28 债务、24 DB 候选、13 兼容入口/85 消费者；仅新增经人工审查的一个只读 Adapter 候选 |
| 既有工作保留 | 前批 47 个源码/测试逐字节不变；Planner、Playbook、Evidence、默认 Runtime/catalog/bindings、持久化与配置等受保护路径与 HEAD 相同 |

首轮审查发现 technology_nm 被误作文本，priority 的测试类型及 yield_rate 数据也不符合
实际 lots Schema。最终使用整数技术节点、文本优先级、0～1 批次比率；聚合 yield_pct 仍为
百分数，例如 96.0，与 0.96 明确区分。核心拒绝负时长/错误计数或关系/坏时间戳，保留合法
负测量值、可空规格、可空完成时间及空字符串异常码。用不同晶圆数证明分层良率是加权
93.33%，不是批次均值 90%；完整列集与顺序保持旧模板投影，不在核心重新计算或补造字段。

实际临时库对照还覆盖产品精确大小写、日期末日、NULL 完成时间排除、101 条事件截为
100 行、设备与过程各自的反例、全历史批次和负测量/空异常码。相关库独立配置，缺少无关
库仍可执行，缺少所需库不创建；只读 URI/query_only、连接释放、执行/关闭故障、期限及
超时与关闭同时失败的优先级均通过。主审保存的 SQLite Loop 只配置制造库，仍成功读取
2020 年批次异常，Source 日期为空，没有把默认时间窗或其他库伪装成必要条件。

60 文件为原 Loop 53 加本批七个，与首批诊断的 60 文件清单不同；没有借用第二至第五批
新工具或旧 reports/Planner SQL 构造器。-I -S、空环境、无关 cwd 中持续阻断旧模块、设置/
身份、数据库、网络/DNS 与环境访问/遍历；故意触发证明守卫有效，之后 16 条实际路径无
被禁止活动。所有加载的 app 模块均来自显式清单，默认 Registry 为空，不伪造 initializer。
真实 SQLite 查询由独立临时库矩阵验证，不声称在禁止 SQLite 的进程内执行了数据库查询。

证据沿用启动目录 runtime/quality/mod-008f1-20261030-r1/：implementation-plan.txt、
review-plan.json、validation-commands.txt、independent-preflight-*.log、targeted-tests.log、
ruff.log、format.log、repository-check.log、boundaries.json/log、refactor-contracts.log、
behavior.log、portable-units.log、gate-results.json、inventory-precheck.json、
default-registry-audit.json、final-worktree-audit.json 和 independent-review.json。
demo-ready.json 为 Fake 产品分层，demo-loop-sqlite-alltime.json 为实际临时 SQLite 全历史
批次异常，demo-sql-denied.json 为本地 SQL 拒绝。retained-previous/ 是前批审计副本，原七
重建制品位于 runtime/portable/mod-008f1-20261030-r1/。已有负向测试预期 usage/error、重复
ZIP 成员等输出不代表最终集合失败。

当前 65 个项目改动文件包含前批工作；未暂存、提交或推送，工作簿保留，变更文本均为
UTF-8/LF。没有真实公司或外部模型调用，未重复正式性能、全量浏览器或覆盖率。默认
14 个工具仍为 LegacyBindingAdapter，全局 TOOLS/TOOL_HANDLERS 身份不变，新八工具尚未
进入默认清单；默认 SQL 仍可见且绑定。本批证明替代能力已具备，未完成全局 SQL 退出。

下一步 F2 将这张八项映射落到实际 Planner/Playbook/Evidence，再按能力版本迁移默认工具
清单与可执行绑定，记录有意行为差异及旧历史证据，不自动覆盖冻结基线。MOD-008 整体
仍进行中；不能把 F1 的本地 SQL 拒绝当作默认应用、公司权限或目标量化模型已通过验收。

## 第六批 F2a：版本化 Planner / Playbook / Evidence 消费链（2026-10-31 已验证）

F2a 先建立实际规划器消费新工具的显式版本，F2b 再统一切换默认装配、模型清单与执行
绑定，避免默认 Planner 生成新名字、默认 Registry 却没有绑定的中间状态。本批不代表
HTTP 默认应用已切换，也不是整个 MOD-008 收口。

### 实施与版本边界

| 文件 | 变化 |
| --- | --- |
| `app/manufacturing/named_playbooks.py`（新） | 六类 v2 Playbook 与选择器；只替换 SQL 工具，保留原证据 ID、字段、必需性、安全要求和其他非 SQL 工具。 |
| `app/planning_runtime/named_planner.py`（新） | `create_named_execution_plan` 校验当前路由的声明版本，拒绝旧版、跨路由和伪造选择，生成版本化具名计划。 |
| `app/planning_runtime/queries.py`、`steps.py`、`scope.py` | 共享步骤构建器支持八项结构化参数、来源、范围和语义；原 SQL 版本仍保留。 |
| `app/evidence/semantics.py`、`validator.py` | 新具名工具语义可直接描述；精确匹配产品、设备、制程、批次和日期，错误范围不能计入证据。 |
| 三项新测试模块 | `test_named_planner`、`test_named_planner_evidence`、`test_named_planner_runtime`，共 12 项标准 unittest 方法，含表驱动反例。 |

显式调用 `select_named_playbook(route)` →
`create_named_execution_plan(question, route, selection)`；省略 selection 时也只选新的
canonical Playbook。能力为 `manufacturing-named-queries` / `2.0.0`，Playbook 的
schema/version 为 `2.0` / `2.0.0`，Plan 为 `1.2` / `2.0.0`，plan_id 使用
`named-2.0.0-` 前缀。F1 各工具契约仍为 `1.0.0`，两类版本不混用。

八项映射沿用 F1：产品分层、设备事件、设备异常及批次身份/路线/异常/缺陷/Wafer Map。
保留产品加权良率、设备事件的实际设备过滤、设备异常的制程与设备联合过滤。五项批次
只有 lot_id、不附加默认 90 天或 route 日期；身份上限 10，其余具名结果上限 100。
日期输入沿用 F1 的严格格式与 730 天跨度约束，不暗中裁剪或回退旧 SQL。

旧 `select_playbook` / `create_execution_plan`、默认 catalog/bindings、Ready/Loop 服务
装配和公开 TOOLS/TOOL_HANDLERS 未切换。新计划通用预算不再声明 SQL，旧默认预算保留。
旧冻结基线与制品未覆盖；复用原计划标识机制，没有新增哈希校验。

### 主审修订与实际验收

按 AGENTS 先规划、再由 terra_worker 实施，主审审查并有界修订。初版曾重复保留 EQP
辅助工具、选择校验未绑定当前路由，随后又拒绝 canonical 非选中状态；已修正并补回归。
旧 SQL 起止日期元数据仍分别判断，新测试冻结日期。实现阶段曾误用 Windows Python，
其输出不作为有效项目验收；以下最终命令均在 Ubuntu-24.04 WSL 的 fab-insight-agent 执行。

| 独立项目 | 实际结果 |
| --- | --- |
| 72 模块必要回归 | **476 项通过，75.754 秒**；含既有工具、执行器、安装门及新增 Planner/Playbook/Evidence 检查。 |
| 六类真实规划矩阵 | 能力异常、良率下降、设备、批次、SOP、综合诊断的版本/依赖/预算通过；未知、歧义、缺 Lot 及错误选择处理通过。 |
| 独立功能核验 | **12 条路径通过**：6 条完整批次计划、6 条日期型证据子计划，实际复用原生 Dispatcher。 |
| 完整批次计划 | Fake / 临时 SQLite × Ready / Loop；五项完整具名结果与独立字面量对照，来源、全历史范围、六次单一 Guard 记账通过。 |
| 日期型证据子计划 | 三项实际规划器生成的命名步骤各经 SQLite Ready/Loop；仅在验收子计划中清除依赖、收缩预算，不声称完整良率/设备计划已验收。 |
| Evidence 与故障 | 产品/设备大小写、缺少/错误联合过滤、错误批次及额外日期不计证据；八项语义通过。Ready 首步失败后五个后继阻断，Port 仅一次，错误脱敏。 |
| 新装配旧 SQL 拒绝 | Ready/Loop 均拒绝、零 Port 调用；不等于默认全局 SQL 已退出。 |
| Ruff / 格式 | 新五文件通过；既有五文件与 HEAD 对照无新增诊断。 |
| 仓库、新旧模块边界 | **254 文件 / 0 错误**；226 Python、28 静态；无新增依赖债务、DB 候选或兼容消费者。 |
| 旧冻结行为、重构契约、便携交付 | 全通过；七单元重建与旧 37 文件安装检查在必要门内。未声称新增 Planner 已有独立安装制品。 |
| 保留审计 | 前批 58 项源码/测试逐字节不变；旧默认运行时、catalog/bindings、原 Playbook/service、存储、配置和模型路径未改。 |

“全部步骤成功执行”与“必需证据全部覆盖”分别核对。原不完整 Fake 夹具的空完成日期、
知识 source 缺失仍被判为 partial，未错误计为 covered。补齐独立知识夹具后的 SQLite
Ready/Loop 均覆盖四项必需证据（100%）；知识明确仍为 Fake，不冒充真实公司文档。
Loop 验收是工具执行轮，直接提供确定性工具响应、模型调用为零，不代表真实模型效果。

额外 Ruff 对照发现一项新增 SIM102，等价合并条件后，主审再次独立运行受影响的
52 项测试（1.844 秒）、12 路功能核验和冻结行为，均通过。476 项为本批完整必要集合，
修正后的 52 项不重复累计。既有五文件诊断保留，首轮静态审计记录也保留。

证据目录 `runtime/quality/mod-008f2a-20261031-r1/` 包含 implementation-plan.txt、
starting-state.json、review-plan.json、八门日志 / gate-results.json、
independent-functional-check.py / independent-functional-results.json、after-style-*.log、
after-style-results.json、inventory-review.json、默认绑定及最终工作树审计。
retained-previous/ 为前批审计副本；七单元制品位于对应 runtime/portable 目录。

当前仍为 28 债务、24 DB 候选、13 兼容入口/85 消费者。未接公司来源或真实模型，未重跑
正式性能、完整浏览器或覆盖率；未暂存、提交、推送。工作簿保留，文本 UTF-8/LF。
回退可撤销本批版本化入口、共享映射及文档/清单增量，保留前批工作和旧数据。

### F2a 验收时的下一步：F2b

默认准备阶段、Ready、Loop 及必要的知识预取/降级入口接入原生装配，核对可信身份、
显式来源、同一 Guard 预算和工具清单/执行绑定一致性；移除模型可见和可执行的
`query_manufacturing_data`，同步提示、能力版本与迁移说明。兼容入口消费者逐项核对，
旧基线和失败保留，默认应用入口另行验收。在这些完成前，MOD-008 仍进行中，不能声称
模型全局已无法提交 SQL。

## 第六批 F2b：默认原生工具与 SQL 能力退出（2026-11-01 启动，2026-11-02 已验证）

本批是默认能力迁移，不是等价目录重构。模型清单由 21 项业务原生定义加独立的
`submit_analysis` 协议组成；八项具名查询替代模型提交 SQL。默认准备阶段选择
v2 Playbook / planner 2.0.0，生成 schema 1.2 计划。业务运行组合 21 项原生绑定；
通识知识问题仅组合并授权 `search_knowledge`，不把其他业务能力带入该运行。
每次运行使用独立 Registry、Dispatcher、可信 principal 和同一 LoopGuard，Ready、模型 Loop、知识预取和必要的
无模型业务降级共同使用这一执行边界。

`query_manufacturing_data` 从默认模型清单、提示字段目录、可执行绑定和兼容桥白名单退出。
即使模型伪造该调用，或 Python 调用方往全局 Handler 字典加入同名函数，默认 Dispatcher
仍须在读取来源前拒绝。保留 `safe_select`、旧 Planner、`LEGACY_TOOLS` 和旧提示，仅供
内部历史消费者及显式 legacy-v1 回放；这些入口仍需要 MOD-009/015 审核和收缩，不能
声称仓库内所有 SQL 代码已删除。

13 项旧 kwargs Handler 保留对象身份及实时 patch 兼容。当受信 Python 调用方替换其中
一项时，运行时明确使用 `legacy-v1` 适配；正常未替换的默认调用解析为 21 项原生绑定。
模型不能启用这个兼容开关，也没有配置回退到 SQL 的路径。

来源按需初始化。制造工具按具体查询选择显式只读 SQLite Adapter；知识搜索单独读取
知识库和质量库中的缺陷别名，个人知识 owner 来自可信身份，不触发全库初始化。
企业 Provider 接收本次 settings 和日期快照；合成来源明确标为 Fake，外部 Provider
须声明来源种类。任何配置或来源失败均不自动改读其他数据库或旧 Handler。

验收分开记录：当前默认 v2 功能/拒绝路径与能力清单；显式 legacy-v1 的旧行为和契约回放；
当前默认 v2 对冻结 v1 的性能迁移比较。历史回放通过不代表新默认链路通过，不能自动
刷新旧基线或用 CPU 时间替代墙钟 p95。阶段全量离线质量门、隔离安装/边界检查和性能
结果待完成后补入本节；当前不标记 F2b 或 MOD-008 已验收。

本批保留审计以 `runtime/quality/mod-008f2b-20261031-r1/starting-state.json` 和
`retained-previous/` 的 68 项副本为准。已审查的一处必要前批增量是
`BackendKnowledgeSearchAdapter.personal_source_kind` 可选参数：旧调用默认继承工厂来源
种类，默认运行时可分别声明外部工厂来源与个人 SQLite 来源，避免把二者错误标为同一种。
其余前批源码/测试需逐字节核对。工作簿不进入本次修改、暂存或提交。

### F2b 修复记录与验收方法

首轮全量非系统回归发现 22 项失败、6 项错误，主要是默认 availability 新增的顶层导入
破坏旧隔离源码包，以及旧测试仍将 v1 Planner / Playbook 当成默认消费链。具体原生离线
调度已改由 bootstrap 注入；未扩大旧 37 文件安装清单或其他已验收源码切片。
后续 1046 项非系统测试通过；模型治理系统项暴露的默认降级回归也已修复：只在已有的
“首个正文前、模型可用性故障、重试结束”条件下调用原生降级。显式注入且未提供该回调的
模型链路继续传播失败，不回退到旧业务读取。原生工具事件只发送一次。

阶段完整离线检查已分段通过，覆盖率 88%；静态 Schema 缓存及通识能力收缩后的最终
复查结果待下节补齐。缓存仅限版本化 Schema 投影和最多 16 项成功的不可变 Schema 文本
验证，不缓存消息、业务结果或权限判断；不同文本及无效输入仍逐项验证。

独立性能迁移夹具在冻结 v1 与当前 v2 的隔离进程中执行相同 `_run_agent_impl` 边界。
两侧使用相同问题、完整固定业务行及模型响应：Ready 一次综合、Loop 一次选工具加一次
综合、通识按来源预取后一次综合。旧侧执行真实报告/RAG 处理器并注入 Fake 来源；新侧
执行真实原生处理器和 Fake Ports。除来源行、调用及 Guard 计数外，还比较完整可用检索
结果及排序元数据。持续审计 socket、DNS 和 SQLite 访问均须为零。

夹具明确采用 `minimal-counts-v1` 观察器和 `steady-worker-loop-v1` 生命周期：记录模型和
工具事件计数，单个隔离 worker 内复用服务事件循环，各请求的身份上下文独立复制。
这衡量预热后的离线服务逻辑，不声称覆盖冷启动、实际 HTTP/SSE 序列化或公司数据源延迟。
早期每次重建事件循环、复制但不使用完整请求、或用旧 RAG 占位回调的结果均保留为诊断，
不作为正式迁移证据。正式比较仍为每场景每侧 **1000 × 2**、每批 10 次预热、50 次 AB/BA
分块；每批原始墙钟 median 和 p95 均须通过原有 15.65% / 16.36% / 15.64% 限额。
不修改冻结档案、阈值或业务输出，也不以 CPU 时间替代墙钟指标。

模型发布/健康 Store 通过内存配置夹具隔离；这些结果不代表真实 API 生命周期已无全局
数据库依赖。模型生命周期与内部存储的剩余收口仍属于 MOD-012/015。

### 正式性能结果：前两轮未通过（历史检查点）

两轮均保留完整原始样本、每批统计、来源审计和输入一致性证明。
第一轮 Ready 通过，Loop 与知识检索未通过；执行器减少中间任务与无必要的轮询后，
第二轮结果如下。表内百分数只用于展示，判定使用未舍入数据。

| 场景 | 冻结限额 | 两批 median 增幅 | 两批 p95 增幅 | 结果 |
| --- | --- | --- | --- | --- |
| Ready | 15.65% | 6.53% / 6.20% | 6.26% / 5.73% | 两批通过 |
| Loop | 16.36% | 16.88% / 16.44% | 15.05% / 28.98% | 未通过 |
| 知识检索 | 15.64% | 16.00% / 15.87% | 14.23% / 13.40% | median 未通过 |

正式数据位于 `native-performance-formal-r1.json`、`native-performance-formal-r2.json`；
每侧每场景 1000 × 2，双方各 60 次预热，socket / DNS / SQLite 持续审计均为零。
`formal-r1-source/`、`formal-r2-source/` 保存对应应用源码及同一测试夹具；第一轮仅需将
第二轮的 Dispatcher 恢复为 HEAD 版本，重建说明保存在 snapshot-note.json。
正式比较后只修复旧独立阶段对象缺少可选 hook 的兼容读取；该增量单独记录，不重判
性能结果。整个工作包保持进行中，后续继续定位 Loop 尾延迟与两场景的中位数开销。
不采用反复抽取有利批次、取消权限/预算/结果验证、切回旧 SQL 执行或改动阈值来收口。

进程 CPU 只用于诊断：第二轮 Loop 的第二批墙钟 p95 为 7.104 ms，进程 CPU p95 为
7.090 ms，同步上升，不能将尾延迟全部归因于 WSL 调度。中位数超限则已接近边界，
仍需继续分析结构化执行的 CPU 开销和少量 off-CPU 等待，不能用 CPU 指标替代失败的
墙钟结果。

### 最终功能与质量复核（分段完成）

| 检查 | 实际结果 |
| --- | --- |
| Python 非系统全量 | 执行 1051 项；发现一项旧独立阶段对象缺少可选 hook 的兼容问题，修复后对受影响的 10 模块、105 项补测全部通过。补测还隔离了一项依赖本地已发布模型的旧测试夹具。未将重复执行累计成新增测试数。 |
| 系统回归 | 70 项、五模块全部通过；总耗时 208.72 秒，触发 180 秒预警，未超过 300 秒失败线。 |
| 覆盖率 | 88%，高于 80% 要求。 |
| Node / 浏览器 | 61 / 61；Playwright 17 / 17（45.5 秒）。 |
| 既有评估 | RAG 15 / 15、OCR 8 / 8、Playbook 12 / 12、Ready 3 / 3、Trace 7 / 7。 |
| 默认 v2 / 显式历史 v1 | 新默认迁移检查通过；legacy-v1 行为与重构契约分别通过，未冒充新默认验收。 |
| 分块与边界 | 旧 37 文件真实安装、各源码切片和七单元回归在非系统全量中覆盖；最终仓库及新旧边界检查通过。258 文件、29 精确债务、25 DB 候选、13 兼容入口 / 97 静态消费者。 |
| 独立复核 | 取消、超时、迟到 Future、ContextVar 和不可变 Schema 缓存经只读复核，未发现新的正确性问题。 |
| 保留与格式 | 前批 68 源码/测试中 67 项逐字节相同，知识 Adapter 可选个人来源类型增量已审查；冻结 MOD-002 档案未改。258 行职责表与清单精确对应；UTF-8 / LF、工作簿保留，暂存区为空。 |

最终证据见 `full-gate-final.log`、`full-gate-final-completion-r2.log`、`final-checks.json`。
后者覆盖必要补测、系统、仓库、评估和浏览器的完整尾段，退出码为 0；前面的失败日志
保留。该检查点只确认功能与质量复核完成，当时 F2b / MOD-008 因正式性能未通过而保持进行中；最终状态见下节。
本轮未提交、推送，也未接入真实公司来源或真实模型。

### 2026-11-02 性能收口与最终验收

本次沿用 WSL，先审查代码和调用分析，再按 AGENTS 将三个有界优化分别交由
terra_worker 实施，主审独立复核、补测及重算。每轮正式比较均对应新的已审查源码；
未重复相同版本挑选有利批次，也未修改夹具、冻结档案、样本数或验收阈值。

| 改动 | 行为与兼容约束 |
| --- | --- |
| Coordinator 依赖字段元数据 | 最多 32 个依赖类型的不可变字段名集合；每次仍读取当前运行的分组实例，保留查找顺序、子类字段及回调隔离，不缓存依赖值。 |
| 默认原生清单装配 | 未暴露可变视图时复用已声明的不可变 JSON，省去立即解码再编码；仍逐项 resolve 当前绑定、限制旧适配器并验证 ModelRequest。首次公开读取/替换清单后永久使用原通用路径，安装前持有的列表引用也保留。每个运行的可变清单独立。 |
| Evidence 序列化 | 精确内置 dict/list/tuple 使用等价的递归构造；最多 32 类的有序字段名元数据缓存。保留自定义容器、namedtuple、deepcopy 和最终 JSON 往返，不缓存业务数据或省略输出/错误验证。 |

第三轮 Ready、知识检索及 Loop 中位数通过，但 Loop 两批 p95 为 +19.04% / +18.64%，失败。
第四轮仅 Loop 第一批 p95 +17.50% 超限，其他批次/指标通过，整轮仍失败。两轮均保留，
各自原始样本经主审重算；不能将第四轮的单个通过批次当作最终验收。

第五轮在上述最终源码上一次执行，**每场景每侧 1000 × 2、双方各 60 次预热，所有批次
的墙钟 median / p95 均通过**。表内数值为展示舍入，判定使用原始样本的未舍入增幅。

| 场景 | 固定限额 | 两批 median 增幅 | 两批 p95 增幅 | 结果 |
| --- | --- | --- | --- | --- |
| Ready | 15.65% | 1.01% / 1.33% | 2.27% / 3.82% | 全通过 |
| Loop | 16.36% | 11.69% / 10.76% | 13.20% / 14.71% | 全通过 |
| 知识检索 | 15.64% | 13.75% / 12.52% | 12.67% / 13.90% | 全通过 |

主审独立复算 12,000 个原始墙钟样本，与 CLI 判定一致；完整输入、固定业务行、模型/
工具/Guard 计数及可用知识结果/排序元数据一致，socket / DNS / SQLite 持续审计均为零。
258 个应用文件与测量前保存的源码逐字节相同；第三至第五轮使用的性能夹具逐字节不变。
这是 capability-v2 的迁移性能证据，仍不冒充 MOD-002 历史行为等价、真实网络或公司来源验收。

最终必要集合 **25 模块、205 项通过（7.820 秒）**，覆盖依赖/回调隔离、原生默认、全部
工具组的 Ready/Loop、注册表、执行器、源码隔离、Evidence 与综合。阶段全量质量证据仍为
上一检查点的分段全量、88% 覆盖率、70 系统、Node 61 和浏览器 17；本次有界优化只重跑
必要范围，未将旧覆盖率或重复执行的测试算为本次新增全量。
仓库检查、258 文件/零错误的新旧模块边界、默认 v2 迁移检查、显式 legacy-v1 契约与行为
回放均通过。六个依赖/装配源码测试文件 Ruff 通过，序列化源码通过；序列化测试与开工
副本的诊断对照均仅有原 SIM117，无新增诊断或全局抑制。

续作证据目录为 `runtime/quality/mod-008f2b-20261102-r3/`：三份 implementation-plan、
各轮 worker 与 independent-validation/review、`formal-r3/r4/r5-source/`、
`native-performance-formal-r3/r4/r5.json` 和独立重算 JSON。早期继承代理变量的进程内
profile 仅作诊断，另有 clean service-only profile；不作为正式比较。原 r1/r2 的失败、
全量日志及前批保留副本继续存放在上一目录，均未覆盖。

**MOD-008 F2b 及整个 MOD-008 现已验证，下一项为 MOD-009：批量工具来源替换、
新增能力入口与独立演示。** 模型客户端生命周期仍属 MOD-012，剩余兼容/存储债务属
MOD-009/015；不宣称整个模块化计划或公司迁移已完成。本次未暂存、提交、推送。
