# MOD-008 工具分批推广与模型 SQL 能力退出

启动：2026-10-26；首批验收：2026-10-27。状态：首批已验证，整个 MOD-008 进行中。
前置 MOD-014 已验收，见对应报告；旧 SQL 退出尚未验收。

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
边界推进，不强制经过模型业务 Tool。未暂存、提交或推送；保留全部前序工作和用户工作簿。
