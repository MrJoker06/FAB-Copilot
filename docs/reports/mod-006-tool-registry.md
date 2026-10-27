# MOD-006 单一工具 Registry 与旧绑定适配

日期：2026-10-24。状态：已验证，下一项 MOD-007。

## 已确定的实施边界

新增纯 `app/agent_runtime/tools/tool_registry.py` 内核及显式 `LegacyBindingAdapter`；
原有 catalog/registry 的具体 Schema 与 handler 装配移到 `app/bootstrap/`。
旧 `TOOLS` 列表、`TOOL_HANDLERS` 字典继续是 Registry 持有的原生兼容容器，
不建立独立 handler 快照，旧 adapter 在执行时读取当前映射。

保留旧 Schema、工具顺序、导出对象身份、live patch、kwargs 调用及结果对象身份；
`submit_analysis` 为独立协议，不变成普通可执行工具。未迁工具明确标识为 legacy 模式，
不宣称其已有完整的结构化验证。新 typed binding 只在隔离 Registry 中验证注册/解析，
不把 MOD-005 设备试点切换进现有 Ready/Loop。

本项不实现 Dispatcher、Policy、自动重试或失败后回退旧 handler；不改变 SQL 工具退出阶段，
不接入公司库/API，不修改真实数据或冻结基线。兼容 facade 到 bootstrap 的实际反向装配边
必须按精确依赖债务登记，不能以扩大整个 tool_system 白名单掩盖。

## 实际交付

| 文件 | 职责 |
| --- | --- |
| `app/agent_runtime/tools/tool_registry.py` | 纯 Registry、显式 legacy/native 两种绑定模式及协议角色；空的默认实例不装配业务 |
| `app/bootstrap/__init__.py` | 无装配副作用的包锚点 |
| `app/bootstrap/tool_catalog.py` | 原 Schema、日期属性及协议常量的显式装配；导出 Registry 持有的同一列表 |
| `app/bootstrap/tool_bindings.py` | 原 14 个 handler 的启动期批量装配；保留原函数对象 |
| `app/agent_runtime/tools/catalog.py` | 旧 catalog 兼容导出及隐式可见的常量 aliases |
| `app/agent_runtime/tools/registry.py` | 同一 handler 字典与旧函数 aliases 的兼容导出 |
| `app/agent_runtime/tools/executor.py` | 通用 Mapping 调用改为显式 LegacyBindingAdapter，解析器保留旧语义 |
| `tests/test_tool_registry.py` / `tests/test_tool_registry_portable.py` | 注册、兼容、导入顺序与仓库外实运行验收 |

Registry 持有原生 `list` / `dict`，兼容入口与其对象身份相同，不使用 dict 代理或独立的 handler
执行快照。legacy metadata 的新查找读取当前 Schema 单元，不缓存另一份名称索引。native Binding
与 legacy handler 分开标识且名称互斥；native 的公开 Schema 从 Definition 派生并深拷贝为投影，
不向旧 kwargs 执行入口塞入假 bridge。新增 native 工具排在协议项之前，保留协议项末尾位置。

catalog 与批量 handler 安装在写入前预校验；重复安装、缺失/多余 handler、错误类型、协议冲突、
同名绑定和 Schema 导出错误均有失败后状态不变的测试。该注册服务用于启动期装配，不宣称提供
并发注册事务。`legacy-v1/legacy_kwargs` 明确表示旧 kwargs 契约，不能冒称其已通过 typed 输入/
输出验证；`answer_submission_protocol` 不是普通业务 binding。

所有原有工具名称、Schema 和顺序保持不变：全局仍为 15 个模型条目、14 个旧 handler。
MOD-005 typed 设备绑定仅在本地隔离 Registry 中验证，没有替换全局设备查询。
未知/None handler 仍抛原始 `ValueError("未知工具: name")`；合法调用保持 kwargs 与结果引用，
已捕获 adapter 对新增、替换、清空及恢复的映射实时可见，单次调用仅查找/执行一次。

`submit_analysis` 的不可执行角色由 Registry 装配元数据约束，不在通用 executor 或 Ready/Loop
添加按工具名称分发的分支。兼容 Python 容器仍允许直接 patch，通用 Mapping executor 仍是旧低层
能力；这些都不是生产授权或防篡改边界，后续 Dispatcher 必须另行执行能力与主体策略。

## 隔离与边界证据

仓库外测试复制 MOD-005 的 26 个实际源码文件，再增加纯 Registry，共 27 文件；不复制全 app、
不替换包初始化器、不添加 bootstrap。`-I -S`、临时 cwd、空环境下真实注册并解析设备健康
binding，以 Fake Port、显式时钟和上下文返回 ToolResult。默认全局实例的列表/字典保持空，
typed 调用失败时调用计数为一、同名 legacy sentinel 为零。所有 `app.*` 模块真实来源必须在
临时单元内且属于清单；环境读取、socket 创建、SQLite 连接及禁止模块都有主动拒绝/负向控制。
这验证纯内核接缝，不是正式安装、公司适配或整个 Runtime 已解耦。

导入顺序测试在真实子进程验证 catalog-first 和 registry-first；全程 audit hook 拦截 socket
连接/解析等操作及 SQLite 连接，负向控制后清空事件，真实导入结束仍须没有被拒绝访问。
仅 catalog 阶段另拒绝具体 bindings/reports/rag/settings；随后允许旧 registry 装配，但不撤销
网络/DB 守卫。旧 registry 仍会导入旧依赖，不能称其本身已是纯模块。

新增 4 个 app 文件后清单为 185 文件（157 Python、28 静态文件）。移除 catalog 的 2 条及
registry 的 3 条直接业务依赖债务，增加两个兼容 facade → bootstrap 的真实债务，共 27 条；
分别按 MOD-011 / MOD-008 退出。新旧守卫均仅增加精确兼容边与纯模块登记，没有放宽整个
tool_system 的目标依赖。DB 候选仍为 20，兼容台账仍保留现有范围及静态扫描局限。

## 主审实际回归

在 WSL Ubuntu-24.04、`fab-insight-agent` Python 环境独立执行 19 个相关测试模块：Registry/
portable、工具契约/旧工具边界、执行/检索/Ready、制造/知识边界、设备切片四组、模块/仓库守卫、
Runtime/旧重构契约及 LoopGuard。结果为 **163 项通过，40.348 秒**。

Ruff 与 9 个新增/修改 Python 文件的格式检查通过；真实仓库检查、新旧守卫通过（MOD-003：
`185 files / 0 errors`）；旧重构契约通过，冻结行为 v2 差异为空。日志中的 argparse 错误、
seed 路径提示和 `files=1 errors=1` 分别来自 CLI/Mock/非法配置负向测试，不是真实生成数据库或
真实仓库守卫失败。

证据目录：`runtime/quality/mod-006-20261024-r1/`，包括 `targeted.log`、`ruff.log`、
`repository-check.log`、`boundary-report.json`、`refactor-contracts.log` 和 `behavior.json`。
正式性能结果见下节，不能把行为命令中的 performance skipped 当作性能门通过。

## 预声明验证策略（采样前记录）

以下保留采样前的验证承诺；实际通过结果见后续小节。

先执行 Registry/native/legacy 边界、Schema/身份/live patch、导入顺序、仓库外隔离和相关
设备/Ready/Loop/知识兼容的必要定向测试，再执行新旧守卫、仓库检查和冻结行为比较。

由于本项修改单次执行热路径，主审还将执行一次正式配对性能回归：

```bash
python scripts/modularization_paired_baseline.py --samples 1000 \
  --report runtime/quality/mod-006-20261024-r1/paired-formal.json
```

采用已批准的 reference/current 协议：每场景 1000×2、原冻结行为、同轮隔离临时树、
原 15.65%/16.36%/15.64% 容差，墙钟 median/p95 门控。该路径在采样前声明；失败保留，
不追加无代码变更的重跑挑成功，不改阈值，不把 CPU 或 observation 冒充正式通过。
本声明不自动要求重复 MOD-002 reference 审批，也不等于本项已经通过性能门。

完整质量门、浏览器全量和覆盖率暂不重跑；若定向/冻结检查暴露超出本项的实际回归，再按风险
追加必要检查。最终报告将填入真实执行结果，不沿用前序工作包数字。

## 正式配对性能结果

上述预声明路径实际执行一次，exit 0，`mode=formal/status=passed`。三场景各侧 1000×2，
共 12,000 个原始墙钟样本，120 个 AB/BA 块；无追加重跑挑选结果。

| 场景 | reference median / p95（ns） | current median / p95（ns） | 原容差 | 结果 |
| --- | --- | --- | --- | --- |
| Ready | 7277028 / 8041080 | 6684615 / 7334433 | 15.65% | 通过 |
| Loop | 5116767 / 5719493 | 5061195 / 5734979 | 16.36% | 通过 |
| Knowledge | 4662548 / 5359778 | 4646750 / 5320045 | 15.64% | 通过 |

主审不调用 runner 的统计函数，独立排序并重算每批/合并样本的整数 median 与 nearest-rank p95，
与存储统计逐项一致，再按原容差以整数算式核对通过。双方冻结行为均通过，差异为空，环境一致；
模块来源分别属于各自临时树，网络/DB 实际调用计数为零，环境文件均为 `/dev/null`，临时树已清理。
原始报告为 `paired-formal.json`，独立审计为 `independent-audit.json`，实际命令输出为
`paired-formal.log`，均位于同一证据目录。

这是与既有冻结 reference 的离线热夹具比较，不是只与 MOD-005 的差分性能实验，不把数值差异
归因于本项加速；也不证明生产 SLO、真实模型/公司来源延迟或消除了 WSL 调度噪声。
CPU/cleanup 继续仅作观察，未修改协议、阈值、参考 ZIP 或冻结行为。

## 后续与回退

本项完成的是纯 Registry 接缝、单一兼容容器所有权和显式装配归属；两个兼容 facade 的反向
装配依赖仍是精确登记的债务，不能称整个工具系统或 Runtime 已完成解耦。
MOD-007 将实现最小公共 Dispatcher、策略/能力限制与结果桥接。Ready/Loop 的 typed 切换仍按
MOD-013/014 执行；旧 `query_manufacturing_data(sql)` 继续存在，退出仍为 MOD-008。

七个原便携源码制品没有变成本次新 Wheel；27 文件测试是源码切片证明，不替代 MOD-007 的正式
A 门安装。没有接公司 DB/API、修改真实数据、增加生产授权或提交/推送。

若需回退，应按本项增量成套恢复三个旧工具模块和两份边界清单，并移除本项新增 core/bootstrap/
测试；不能整体重置工作树或覆盖 MOD-001～005 及用户已有的未提交改动。无需数据库迁移或回滚。
