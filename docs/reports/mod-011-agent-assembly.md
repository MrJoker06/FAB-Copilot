# MOD-011 显式装配与最小 AgentDefinition

启动：2026-10-24；验收：2026-10-25。状态：已验收；旧 Ready/Loop 尚未切换。

## 实施方案

本项将 MOD-010 的接缝变为实际可组合的试点应用，并迁移旧 coordinator 依赖组装的所有权。
不切换旧 Ready/Loop，不提前实现 Skill/Checkpoint 或完整 ModelGateway，不另建 Coordinator。
保留全部既有未提交工作和用户工作簿，不提交/推送，不接真实模型/公司来源，不新增 SHA-256。

| 文件 | 职责与变化 |
| --- | --- |
| `agent_runtime/definition.py`（新） | 冻结 ComponentReference / AgentDefinition：角色、指令、模型/默认策略引用、精确工具版本及契约版本 |
| `agent_runtime/application.py`（新） | 小型 AgentRun 绑定门面；只消费 MOD-010 Ports/单步函数，不创建客户端、注册表或预算算法 |
| `bootstrap/agent_assembly.py`（新） | 显式校验并创建 AgentApplication；每个 Run 新建本地 Registry/Dispatcher 和预算 |
| `bootstrap/legacy_agent_assembly.py`（新） | 从显式调用快照构建旧 CoordinatorDependencies，保持类/函数/容器 patch 语义 |
| `bootstrap/agent_demo.py`（新） | Fake 模型/事件与 Fake 或显式双库只读 SQLite 的组合演示，使用新装配而非旧 service |
| `agent_runtime/compatibility.py` | 原 _coordinator_dependencies 保留签名，委托 bootstrap；其他兼容逻辑不重写 |
| 两份边界清单及新增专项测试 | 精确所有者、兼容反向边与消费者登记；测试实际新装配及旧调用路径 |

AgentDefinition 不保存主体、RunState、服务实例、连接、凭据或全局配置。工具声明只限定最大
能力，实际有效能力为 Definition 与显式服务端能力清单的交集，主体/Scope 仍经 Policy 校验。
模型与策略引用必须与注入绑定的 ID/版本精确匹配；工具版本/缺依赖/重复绑定/未知契约版本
在执行前拒绝。引用不是生产权限认证器，也不是新的工具注册权威。Skill 非空引用暂拒绝，
不伪造未实现的 Skill Catalog。新模型可见 Schema 只投影有效工具，不增加第二份权威 Schema。

AgentApplication 保存明确的装配输入，不保存 Run 可变事实。new_run 由可信 RuntimeContext
创建 AgentRun，调用预算 factory 一次；每次运行使用独立 Guard/Dispatcher/Registry，模型和
事件 Port 可由服务端明确复用。预算 factory 负责返回新实例，不能静默复用全局 Guard。
AgentRun 调用模型时加入声明的 system 指令，工具调用使用显式服务端 call_id；事件发布与
执行继续分离，拒绝其他 run_id 的事件。事件失败不重执行业务调用，不承诺 exactly-once。

旧组装函数从 facade 的 globals 快照接收绑定，不改为读取 bootstrap 的固定全局对象；旧
service 的 live patch、构造器替换和 TOOLS/handler 容器身份均须保留。新路径禁止导入旧
service/compatibility/catalog/registry/settings，旧适配器不冒充新 typed Ports。

## 兼容债务范围校准

MOD-011 是试点显式装配，不等于清除全部旧应用依赖。compatibility 中准备/离线综合适配及
conversation.sessions 的内部 Store/identity 迁移仍随消费者在 MOD-015 收口；此前以 MOD-011
为退出点的相关精确台账应明确更新为 MOD-015，保留原因与历史记录，不删除未退出的边。
新增 compatibility → bootstrap.legacy_agent_assembly 只登记为单条兼容债务，不扩大整个
runtime 的允许方向。预计应用文件 194→199、精确债务 27→28；新增测试消费者按扫描实数登记。
依赖债务数不是完成度，不能因为实际装配迁移而把剩余旧依赖标成纯内核。

## 验收与预声明验证

先核对 MOD-010 证据并运行相关测试基线。实现由 terra_worker 按不重叠所有权执行，主审等
交付后独立审查并实际复跑，不以子代理汇报替代验收。新旧明确验证：

- 缺 Port/版本不匹配/重复工具/不支持 Skill/非法能力均在查询前拒绝。
- 有效能力交集、主体和 Scope 授权、未获准 SQL 零执行，Schema 不泄露未获准工具。
- 两个 Run 独立预算/调用上下文；真实设备 binding 单次执行，无额外模型/工具重试。
- 模型指令/精确绑定可查看；Fake 与只读 SQLite 可替换，数据路径只由操作员提供。
- 旧组装直接调用及 service facade 实际消费，函数/类/live patch/共享容器兼容。
- 40 文件 MOD-010 闭包加新现代路径四文件，共 44 文件仓库外真实运行；不导入旧适配器，
  不伪造 initializer、不注入仓库路径，主动网络/DB/环境/导入守卫及负向控制有效。

原七单元及 MOD-007 的 37 文件清单/版本保持原样；新装配采用单独源码切片证明，不冒充
另一个可安装发布包。旧 37 文件安装门作为回归运行。新源码登记 precise pure/assembly 角色。
运行必要定向测试、Ruff/格式、新旧守卫、仓库检查、旧重构契约及冻结行为 v2。

由于修改了旧运行入口的依赖装配热路径，在功能检查通过后预声明执行一次正式配对性能：

```bash
python scripts/modularization_paired_baseline.py --samples 1000 \
  --report runtime/quality/mod-011-20261024-r1/paired-formal.json
```

使用既有 reference、1000×2、原墙钟 median/p95 和 15.65%/16.36%/15.64% 容差。失败保留，
不以无代码变化重跑挑成功、不放宽阈值、不把 CPU/observe 当正式通过。主审独立重算原始
墙钟统计和来源/清理记录。非本阶段收尾，不预设重跑完整浏览器/覆盖率；实际越界再追加门。

风险：全局快照语义变化、声明自授权限、预算跨 Run 共享、版本错配及旧 facade 反向依赖。
回退只按本项增量恢复 facade/清单及移除五个新模块和对应测试，不整体重置工作树或迁移数据。

## 实际实现和主审修订

五个新模块与兼容委托已落地：新路径通过 assemble_agent / AgentApplication.new_run 组合
模型、事件、工具 Binding、Policy 和预算 factory，AgentRun 实际消费 MOD-010 的三个 Port。
AgentDefinition 只保存冻结声明，不保存服务实例或运行状态。模型可见 Schema 从本地 Registry
投影有效能力，不能由声明自行扩大服务端权限；每次运行重新建立 Registry/Dispatcher。

旧 coordinator 五组依赖的构建已迁入 bootstrap.legacy_agent_assembly；旧 facade 仍从每次
service namespace 快照委托，所有构造器也取自快照，因此 live patch 和原容器身份得以保留。
没有用固定 canonical 构造器偷偷替代被 patch 的旧类，也没有重写准备阶段/离线综合/旧 Loop。

主审补充修正了 messages 列表隐式转 tuple、Schema 检查晚于预算 factory、异步 Policy/预算
方法混入同步协议以及 awaitable factory 配置错误；错误配置使用固定消息拒绝，不回显输入。
预算对象只能在 new_run 调用 factory 后验证，不能为了提前验证而在装配时执行 factory。
同理，不在装配时预执行 authorize 猜测其返回类型；错误授权结果由 Dispatcher 拒绝，查询和
预算 claim 均为零。预算 factory 由服务端负责返回新实例，当前演示/测试验证了两个独立 Guard；
不是对任意恶意 factory 副作用或共享对象的自动认证。

新增 demo 输出声明版本/绑定引用、有效能力、Fake 模型标识、数据来源、完整工具结果、
版本化事件摘要及同一个 Guard 的 summary。拒绝 SQL 时不回显查询字符串。事件发布仍与执行
分离，跨 run_id 的事件拒绝，sink 失败不会重新执行查询；不承诺跨进程持久投递或 exactly-once。

## 独立验收结果

在 WSL Ubuntu-24.04、fab-insight-agent Python 3.11 环境，主审实际执行：

| 项目 | 结果 |
| --- | --- |
| 改动前相关测试 | 55 项通过，2.192 秒 |
| 新装配/旧兼容/Port/Dispatcher/安装及守卫等 25 个测试模块 | **185 项通过，31.825 秒** |
| 最终兼容导出标注后的旧入口复验 | 23 项通过，0.066 秒；属于上行集合，不重复累计 |
| 新增 8 个 Python 文件 Ruff / 格式 | 通过 |
| 仓库检查、新旧模块守卫 | 通过；199 文件 / 0 错误 |
| 旧重构契约、冻结行为 v2 | 通过；行为差异为空 |
| 唯一一次正式 1000×2 配对性能 | 通过，原始墙钟独立重算与来源/清理核对通过 |

185 是本轮必要定向集合，不是全量 Python 测试数；未重跑完整浏览器、覆盖率或真实模型。
旧 compatibility.py 并非全文件 Ruff 清零：主审用 HEAD 原源码与当前源码的 JSON 诊断按
code/message 独立比较，均为原有 9 项（2 I001、6 F401、1 DTZ011），没有新增问题。
迁移后仍须保留的 19 个动态兼容导出以逐项 noqa:F401 明确标注，未删除导出或添加全文件豁免。

前期守卫曾因消费者列表顺序而失败（集合相同，new/stale 均为空），现已按实际扫描顺序修复；
最终消费者不是预估的 81，而是原 80 加新测试的 import/service patch/TOOLS patch 三条，
共 **83**。主审也修正了把同步 Policy 的坏返回值误当成装配阶段可预知错误的测试预期，
保留了实际 Dispatcher 的错误决策拒绝测试。初步失败日志保留，不是放宽守卫或授权规则。
现有负向测试中的重复 ZIP 警告、2 files 提示及 files=1/errors=1 不属于真实仓库失败。

### 新旧路径专项证明

- Definition 的精确版本、只读 Binding、缺 Port、重复/缺工具、非法能力、坏 Schema 和暂不支持
  的 Skill 引用均有拒绝测试；同步/异步方法边界按实际协议验证。
- 有效能力取交集；空交集不暴露 Schema，额外服务端能力不扩大 Definition。错误授权决定、
  伪造 SQL、错参、错误主体、预算耗尽及执行前 deadline 均保持受控结果。
- 两个 Run 使用独立 Dispatcher/Guard，首个 Run 的耗尽/重复调用不影响另一个。sink 故障、
  外部调用 ID 和跨 Run 事件不会触发隐式重试或身份改写。
- 新 demo 实际运行 Fake 与两个明确的临时只读 SQLite 来源；缺库不创建、不回退、不泄露路径。
  这验证同一工具的契约/范围和装配可替换性，不把不同夹具的数值宣称为精确等价。
- 旧 service 实际消费迁移后的 builder，函数、构造器、时钟、AsyncClient、TOOLS 和结果引用
  的实时 patch/快照语义保持。新路径没有调用旧 service 或全局旧工具绑定。

仓库外验证复制 MOD-007 的 37 个真实源码文件、MOD-010 的 3 个文件和本项现代路径 4 文件，
共 **44 文件**，不复制旧装配适配器。使用 -I -S、空环境、无关 cwd，主动阻断原仓库配置、
旧 service/compatibility/registry/catalog、模型网关、持久化、Evidence 和制造报表；网络连接/
DNS/SQLite 使用持续 audit hook，配置环境读取有负向控制。所有已加载 app 模块来源均属于
临时目录与显式清单，默认全局 Registry 保持为空。该证明仍是源码切片，不冒充新发布包。
原七单元和 MOD-007 的 37 文件/1.0.0 清单未改，原新 venv 真安装门已作为定向回归通过。

## 正式性能与独立审计

按上述预声明实际采样一次：每场景每侧 1000×2，共 12,000 个原始墙钟样本、120 个 AB/BA
块。配对顺序在第二批反向，未改原协议。主审不调用 runner 的统计函数，独立排序并重算
每批/合并样本的 min/max、整数 median、nearest-rank p95，再用整数算式复核原容差。

| 场景 | reference median / p95（ns） | current median / p95（ns） | 原容差 | 结果 |
| --- | --- | --- | --- | --- |
| Ready | 7386687 / 8195764 | 6710051 / 7612537 | 15.65% | 通过 |
| Loop | 5158208 / 5928413 | 5169922 / 6113914 | 16.36% | 通过 |
| Knowledge | 4708076 / 5486241 | 4702579 / 5505471 | 15.64% | 通过 |

双方冻结行为通过、差异为空，环境和冻结时钟一致，网络/DB 实际调用数为零，环境文件为
/dev/null。app 和 scripts 来源均属于各自隔离树，采样后临时树已清理。独立审计初版对跨批
反向顺序及 scripts 来源的断言已校正；这是审计器对既有协议的修正，没有重新采样或改阈值。
这些数字是既有离线热夹具回归，不证明真实模型/公司数据延迟，也不把差异归因于本次提速。

证据保留在启动日目录 `runtime/quality/mod-011-20261024-r1/`：prechange-tests.log、
targeted-tests.log、assembly-review-initial.log、legacy-review-final.log、ruff.log、
legacy-ruff-baseline.log、legacy-ruff-observation.log、repository-check.log、
refactor-contracts.log、behavior.json、paired-formal.json/log、independent-audit.json。
初始旧 Ruff 文本观察日志用于记录迁移前后差异，最终无新增诊断结论以独立 JSON 比较为准。

## 边界、回退与下一项

当前应用 199 文件（171 Python、28 静态），精确债务 28、DB 候选 20，兼容入口 13 / 消费者 83。
债务从 27 增加到 28，是明确记录保留 facade → bootstrap 的一条兼容边，不是扩大 runtime 的
允许依赖方向。尚未退出的制造/会话/身份和旧 catalog 装配依赖继续登记到 MOD-015；配置文件
和 service._coordinator_dependencies 兼容 seam 同样保留到 MOD-015。旧 registry 文件的阶段
标记与其原绑定债务对齐到 MOD-008。此为试点装配与消费者退出范围的明确校准，不删除残留
边、不让已验收 MOD-011 的标记伪装这些旧入口已退出。因此不能声称整个 Runtime/Memory 已解耦。

下一项为 MOD-013：Ready 通过本项已装配的 Dispatcher 接入，保持确定性拓扑和单一预算；
随后 MOD-014 完成 Loop 双路径，再按顺序批量推广工具与退出旧 SQL。Skill 仍未实现，
非空 Skill 声明会被拒绝，不靠 metadata 冒充能力已经可用。本轮无暂存/提交/推送，保留
此前工作和用户工作簿，文档与新增源码均保持 LF。
