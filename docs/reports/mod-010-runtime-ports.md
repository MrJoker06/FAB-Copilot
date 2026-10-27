# MOD-010 最小 Runtime Ports 与类型化上下文

日期：2026-10-24。状态：最小 Runtime Ports / 类型化上下文试点已验收；旧执行路径未切换。

## 已批准实施方案

以 MOD-007 为依赖，增加试点所需的小型消费方接口和实际单步消费者。不修改现有
CoordinatorDependencies / AgentLoopContext / Ready / Loop；它们的 Any、供应商客户端和
旧装配依赖仍由后续任务逐步退出。本项不是完整模型网关、AgentDefinition 或新 Coordinator。

| 文件 | 变更与职责 |
| --- | --- |
| `execution/runtime_contracts.py` | RuntimeContext、模型消息/调用/请求/响应/Usage、版本化安全摘要事件、StageResult |
| `execution/runtime_ports.py` | 异步 ModelResponsePort、ToolDispatcherPort、EventSink；不创建任何实现 |
| `execution/pilot_stages.py` | 单次模型响应、单次工具调用、独立事件发布三个最小消费者，无循环/重试/状态归约 |
| `tests/test_runtime_ports.py` | Fake 与真实 Dispatcher 的签名、行为和上下文契约测试 |
| `tests/test_runtime_ports_portable.py` | 真实源码闭包的仓库外运行及主动隔离守卫 |
| 两份模块边界清单 | 登记三个 runtime/platform_core 文件及纯模块；不增加债务或扩大允许方向 |

RuntimeContext 只含可信主体、run_id、既有 ToolExecutionLimits 和取消信号；为单次调用创建
dependencies=None 的 ToolExecutionContext。数据依赖仍由 Dispatcher 的 binding 注入，不携带
配置、客户端、DB、原始凭据或动态服务字典。复用现有 ToolPrincipal/取消/限制和 ToolResult，
不重复定义授权范围或预算算法。执行 call_id 明确由调用方服务端传入，不能用模型自报的 ID
改写可信运行身份；模型调用 ID 仅作供应商响应关联。

模型契约采用冻结 dataclass 与 tuple：消息/原始工具参数字符串、非负整数 Usage、响应 ID。
模型可见工具 Schema 是经过 JSON 数组结构验证的序列化投影，不是另一份 Registry 或能力权威。
错误 JSON 工具参数不在模型响应层提前解析，仍交给 Dispatcher 的单一解析边界。保留工具调用
和最终正文，不传递 reasoning、供应商 HTTP 请求、连接信息或重试/健康策略。

单步消费者接受 Protocol 参数，不导入 bootstrap、制造/证据/配置/持久化或供应商实现。
Tool 阶段原样采用 ToolResult 与状态，不第二次 claim/record 或修改 trace/messages/sources。
StageResult 只持有本次产出与安全事件摘要，不是第二份可变 RunState。事件不包含模型正文、
工具参数、数据 payload、原始异常或凭据，保留状态/执行状态/关联 ID/必要计数与 Usage。
工具事件必须保留 ToolExecutionState，区分 not_started、completed 与 unknown；模型事件不
伪造工具执行状态。模型工具名的元数据长度上限与 Dispatcher 的 128 字符约束保持一致，
避免上层接受无法按原名关联的非法调用名；参数 JSON 仍只由 Dispatcher 解析。

事件发布与执行分离：先获得 StageResult，再向 EventSink 发布其事件。sink 失败向调用方传播，
不重执行模型/工具、不丢失调用方已持有的结果；不承诺持久化投递或 exactly-once。模型异常及
外层取消同样传播，不新增兜底或隐式重试。完整供应商取消/期限执行、流事件与生命周期留给
MOD-012；本项只建立最小响应接缝，不宣称取代旧 ModelGateway。

## 验收与风险

契约测试选择 inspect.signature / typing.get_type_hints 配合真实行为测试，而不是新增下载静态
类型检查依赖；不能把运行测试称为整个仓库的静态类型检查。验证 Fake 模型 → 模型调用产出 →
同一真实 Dispatcher/设备 Fake → 类型化阶段结果 → Fake EventSink；SQL 伪造调用仍由服务端
能力清单拒绝。测试必须包含上下文身份/依赖窄化、错误参数和拒绝、Usage/tuple/Schema 校验、
错误 Port 返回、取消传播、sink 失败不重执行、产出 payload 引用及事件无敏感内容。

仓库外只复制显式声明的实际 MOD-007 37 文件闭包加本项三个文件，不插入仓库路径、不伪造
initializer；-I -S、无关 cwd、空环境、主动 DB/外联/配置/禁止模块守卫和负向控制，运行真实
最小消费者。该测试是新增 Port 的源码切片证明，MOD-007 安装门另作兼容回归，不冒充本项
新增独立发布包，也不改原七单元或 MOD-007 清单/版本。

先运行旧 Dispatcher/设备/Runtime 相关必要定向测试作为基线，再运行新两测试模块与相关旧
回归、Ruff/格式、新旧边界、仓库检查、旧重构契约与冻结行为 v2；重跑 MOD-007 安装测试。
旧热路径不改，本项不预设重复配对性能、浏览器全量或覆盖率；如实际改动越界或出现回归则
追加相应验证，不放宽原阈值。所有主审结果必须独立实际执行后填写。

风险在于建立重复 Registry、把响应摘要当完整 Gateway、重复预算或事件失败重执行。
回退只移除本项三个新增模块/两个测试和精确清单记录，保留 MOD-001～007、既有未提交修改
及用户工作簿。不初始化/迁移数据库，不接真实来源/模型，不新增 SHA-256 校验，不提交推送。

## 实际实现与审查

按上述范围新增三个生产模块和两个测试文件。主审完整审查源码后补充了两项必要约束：
工具事件保留真实 execution_state，模型事件不得伪造工具执行状态；模型工具名最多 128 字符，
与 Dispatcher 的可关联名称范围保持一致。工具原始参数仍不在模型响应层解析。

主审同时修正了测试中的自我比较断言、并未超过大小上限的无效 JSON 样例，以及只拦截高层
socket.create_connection 的不足。最终以 RecordingDispatcher 委托真实 Dispatcher 验证对象
身份、一次数据读取/预算/进展；以有效超大 JSON 和 dict 内非有限数验证对应拒绝分支。
协议与消费者的全部参数/返回类型用 get_type_hints 精确比较，不只是检查“存在注解”。

真实集成使用 Fake 模型产出 → 模型阶段 → 本地 Registry/设备健康 Fake/同实例 LoopGuard/
Dispatcher → 工具阶段 → Fake EventSink。模型调用一次，设备读取一次、预算一次、新证据
进展一次；结果与 data 引用均保持。sink 失败后调用方仍持有原结果，不追加查询/预算。
错误参数、未获准 SQL 名及零工具预算均在数据读取前拒绝。失败、取消和超时的 ToolResult
状态及 not_started/unknown 执行状态不会在阶段事件中被改写成成功。

## 主审实际验证

WSL Ubuntu-24.04，fab-insight-agent Python 3.11 环境：

| 检查 | 实际结果 |
| --- | --- |
| 改动前相关基线 | 45 项通过，1.682 秒 |
| 新 Port / source-slice 及相关旧回归，22 个测试模块 | **171 项通过，67.993 秒** |
| 最终测试断言修订后的两个新增模块复验 | 8 项通过，1.074 秒；属于上行集合，不重复累计 |
| Ruff / 格式 | 5 个 Python 文件通过 |
| 仓库检查、新旧模块边界 | 通过；194 个应用文件 / 0 错误 |
| 旧重构契约、冻结行为 v2 | 通过；行为差异为空，性能明确跳过 |
| MOD-007 的原 37 文件新 venv 安装回归 | 包含在上述定向集合中，通过 |

171 是本轮选择的必要定向集合，不是当前全量测试数，不与历史 MOD-007 的 204 项累加。
未重跑全量覆盖率、浏览器、Live 或配对性能；未改变原参考制品、Schema/API、热执行路径或
验收阈值。日志中的重复 ZIP 成员警告、2 files 安装提示及 files=1/errors=1 来自既有负向/
最小包测试，不是实际交付包或实际仓库守卫失败。

仓库外测试使用 MOD-007 实际清单 37 文件加本项 3 文件，共 40 文件；复制真实包及父闭包，
不是整个 app，也不构造替代 initializer。在 -I -S、无关 cwd、空环境下运行上述实际链路，
MetaPathFinder 阻断旧装配/制造报表/配置/模型网关/Evidence/持久化模块；audit hook 阻断
SQLite、底层 socket.connect 和 DNS。先主动触发各类负向控制，再清零记录并保持守卫开启，
实际运行后无阻断事件。环境读取只放行空值的标准库演示/调试键，禁止配置键和环境迭代。
所有已加载 app 模块来源属于临时目录和显式 40 文件清单，全局默认 Registry 仍为空。

该 40 文件测试是源码切片证明，**不是新的发布/安装制品**。MOD-007 的 37 文件 Bundle 清单、
1.0.0 版本及原七单元清单没有修改，其正式安装回归另行执行；不把源码复制冒充安装。

复现核心验收：

```bash
python -m unittest tests.test_runtime_ports tests.test_runtime_ports_portable
python -m unittest tests.test_dispatcher_bundle_install
python scripts/check_modularization_boundaries.py
python scripts/refactor_contracts.py
python scripts/modularization_baseline.py --skip-performance
```

证据目录为 `runtime/quality/mod-010-20261024-r1/`：prechange-tests.log、targeted-tests.log、
ports-review-tests.log、ruff.log、repository-check.log、boundary.log、boundary-report.json、
refactor-contracts.log、behavior.log/json、independent-audit.json。

## 本项边界与下一步

当前 194 个应用文件（166 Python、28 静态），依赖债务仍为 27，DB 候选 20，兼容入口/静态
消费仍为 13/80。没有通过修改允许方向掩盖新依赖，旧 Any 字段与兼容装配债务也没有被虚假
清零。本项新增的是试点可消费的接缝，**不代表整个 Coordinator / Loop 已完成类型化或解耦**。

ModelResponsePort 不是完整 ModelGatewayPort：供应商适配、流事件、运行中模型取消/期限执行、
重试/健康/客户端生命周期仍在 MOD-012 范围。本项把现有取消信号/限制原样交给 Port，外层
task 取消与异常传播不等于已经实现所有供应商的取消能力。模型失败不会生成伪成功结果或
自动重试，调用方负责后续失败处理。事件摘要不是任意字符串脱敏器，也不承诺可靠投递、
跨进程恢复或 exactly-once；调用标识和其他元信息需由后续装配/审计适配保持可信。

下一项 MOD-011 将通过显式装配和最小 AgentDefinition 让这些 Ports 可配置组合，保留旧
装配适配；之后 MOD-013/014 才接入 Ready/Loop 双路径。旧 SQL 工具仍待 MOD-008 退出。
本轮未暂存、提交或推送，未接真实数据/模型，保留用户工作簿与此前未提交工作，文档保持 LF。
