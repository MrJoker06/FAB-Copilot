# MOD-007 公共工具 Dispatcher 与隔离安装

日期：2026-10-24。状态：已完成最小 Dispatcher 试点及仓库外安装验收；旧 Ready/Loop 未切换。

## 实施方案与所有权

本项不切换旧 Ready/Loop、不批量迁移工具、不移除旧 SQL 工具。独立试点采用同一 Registry，
建立严格参数解析 → 服务端能力清单 → 绑定/输入与范围准备 → 演示授权 → 取消/期限/预算 →
执行 → 输出校验 → 结果及事件投影。核心不导入制造、配置、SQLite、Evidence 实现或 Bootstrap。

| 文件 | 计划职责 |
| --- | --- |
| `tools/dispatch_contracts.py` | 小型 Policy/Budget Protocol、决策与通用输入/来源/超时异常 |
| `tools/dispatch_policy.py` | 显式演示租户、角色、能力与设备/日期范围策略；不是生产 ACL |
| `tools/dispatcher.py` | 每运行实例的异步 Dispatcher；同步 handler 在线程中执行，无重试或隐式回退 |
| `tools/definition.py` | 增加可选 prepare hook / ToolPreparation；保留既有三参数 Binding 构造 |
| `execution/tool_budget.py` | 包装原 ToolLoopGuard，仅此适配器完成 claim/record；不复制预算算法 |
| `execution/tool_result_bridge.py` | 纯函数投影到兼容 observation payload、trace、来源与结束事件，不修改 Run |
| `execution/__init__.py`、`planning_runtime/__init__.py` | 必需的按需兼容导出，保留旧 __all__/对象身份，隔离导入不装配整个应用 |
| `manufacturing/equipment_health/` | 接通纯 prepare hook，归一化有效日期/过滤；业务异常继承通用异常 |
| `integrations/manufacturing/sqlite_equipment_health.py` | 识别本地 progress deadline 并保留关闭连接及 DataError 兼容 |
| `bootstrap/dispatcher_demo.py` | 显式 Fake/SQLite 装配和可观察 JSON 演示，不加载旧全局 registry |
| `evaluations/mod_007_dispatcher_bundle_v1.json` | 单个试点组合 Bundle 的显式源码清单与版本 |
| `scripts/install_dispatcher_bundle.py` | 将已验证的声明源码 Bundle 安装到明确的空白目标，禁止覆盖已有 app |

新增 app 文件按 tool_system/runtime/application_bootstrap 归属登记，新旧守卫不得扩大框架到
业务的依赖。为保持旧源码复制测试闭包，MOD-005 的活动清单仅补所需的通用异常模块，历史报告
的原文件数保留为阶段证据。原七个便携单元不改造成八个可合装 Wheel。

## 行为约束

调用主体、run/call ID、能力清单、来源、时钟与预算由服务端提供。Binding 的窄依赖替换 incoming
context 的依赖，模型不能提交 SQL、租户、连接串或 adapter 选择。试点只开放设备健康能力；
伪造 SQL 工具名即使存在于其他旧 Registry，也须在查询/预算 claim 前拒绝。

准备阶段固定日期与设备优先语义，并向 Policy 提供真实有效 Scope，不查询数据。通用异常桥接
不识别制造类名，也不把所有 ValueError 当输入错误。来源故障、解析/验证、授权、预算、超时与
取消分开分类，异常文本不直接公开。native 返回的元数据、输出、来源 Scope 和行数须校验。
最大结果行数先采用超限明确失败，不悄然截断；旧 Ready/Loop 的截断差异留待接入时保留。

只有 LoopGuard 记账，拒绝/错参不 claim；允许的尝试 claim 一次，结果最多 record 一次。
旧算法与既有去重签名保持不变，不新增制品 SHA-256 校验。Dispatcher 不管理模型轮次，也不
自行重复 begin/finish_round。legacy 执行须显式允许，不升级成具有来源/细粒度授权的 typed 工具。

同步调用不能被 Python 安全强杀。开始前的取消/期限可返回 not_started；已开始后的超时/取消
保守标记 unknown，丢弃迟到结果，不能更新已结束 Run 的进度/事件。启动与停止判定需要同步，
不能报告 not_started 后线程仍启动 handler。外层 asyncio task 取消继续向上传播；线程须由来源
自身有限超时最终收尾。无公共 EventBus 接入，桥接只返回可供调用方采用的终态事件。

## 验收与风险

先分批完成内核/预算/策略，再完成设备桥接、演示和安装。主代理独立审查全部新增源码及实际
测试，不以子代理汇报代替验收。

必要测试覆盖合法/空结果、错参零读取、未授权 SQL 零执行、有效 Scope、单次预算/重复阻断、
输出/来源元数据、故障/超时/取消、迟到结果隔离、legacy 无双执行，以及旧导出/冻结行为。
在仓库外创建无 pip 的新 venv，安装声明源码到该环境 site-packages，再以该解释器 `-I`
从无关 cwd 实际运行 demo；不得插入仓库路径、伪造包初始化器或只做源码复制冒充安装。
Fake 与两个临时 SQLite 来源分别运行，主动阻断原仓库配置、未知来源和网络；检查模块真实来源。
安装器须拒绝路径穿越、额外/缺失成员、符号链接、覆盖和损坏清单，失败前完成预检。

运行相关定向 unittest、Ruff/格式、新旧边界/仓库检查、旧重构契约及冻结行为 v2；重建验证原七个
源码单元，确认兼容闭包。旧热执行路径未接 Dispatcher，本项不预设重复性能门、完整浏览器或
覆盖率；若实际修改旧热逻辑或暴露回归，再追加必要验证，不降低已有阈值。

风险：兼容 initializer 的导入顺序、线程迟到、预算双扣和授权 Scope 漂移。回退须成套恢复新增
接口接缝/两个 initializer/设备 hook/边界清单，保留 MOD-001～006 和用户的既有脏改动；不执行
数据库迁移或工作树整体重置。本轮不提交或推送，不接公司系统。

## 实际完成与限制

实现严格 JSON 快照、服务端能力限制、输入与有效 Scope 准备、显式 Policy、取消/期限和预算
检查、单次执行及输出验证。设备健康 prepare 固定默认日期和设备优先语义，授权与来源使用
相同 Scope；输入、来源失败及来源超时通过通用异常分类，Dispatcher 不识别业务异常类名。
来参依赖被 binding 的窄依赖替换，调用者不能用上下文替换数据来源。旧全局 Registry 不注册
本试点，旧 Schema 和执行路径保持不变。

预算适配器调用同一个 ToolLoopGuard 的 check_call/record_result，不复制去重/进展算法或
管理模型轮次。成功记账异常返回 ACCOUNTING_FAILED，不重试或回滚不确定的记账副作用。
legacy 必须另行显式授权；仅检查原 Schema 的少量 required/type/additionalProperties，
不是完整 JSON Schema 验证，也不声称具备 typed 来源或细粒度数据授权。

排队中取消/超时原子阻止 handler 启动，状态为 not_started；已启动的调用为 unknown。
同步线程不能安全强杀；调用方已结束后不采纳迟到结果，不更新预算进展或发送完成事件。
外层 task 取消继续传播。来源自身仍须保证有限超时，asyncio.run 退出可能等待工作线程收尾；
不能把停止等待等同于已终止数据库查询。桥接仅返回 observation/trace/provenance/终态事件
payload，尚未接入旧 Runtime 的事件接收器、状态归约和 Evidence 执行链。

## 主审验收结果

WSL Ubuntu-24.04、fab-insight-agent Python 3.11 环境独立执行：

| 检查 | 实际结果 |
| --- | --- |
| 21 个相关兼容测试模块（含设备 prepare） | 169 项通过，73.673 秒 |
| Dispatcher、边界、桥接、demo、安装与安装包拒绝测试 | 35 项通过，6.980 秒 |
| Ruff 检查与格式 | 20 个 Python 文件通过 |
| 仓库检查、新旧模块守卫 | 通过；191 文件 / 0 错误 |
| 旧重构契约与冻结行为 v2 | 通过；行为差异为空，性能明确跳过 |
| 原七个源码单元 | 全部重建并通过各自 --verify |
| 新试点组合 Bundle | 37 个真实源码文件、38 个 ZIP 成员；元数据、LF、100644 模式和源码逐字节核对通过 |

合计 **204 项必要定向测试通过**，不是全量 Python 测试/覆盖率或浏览器验收。旧热路径未接入
Dispatcher，本项未重跑配对性能，不修改历史基线、阈值或此前失败记录。兼容测试日志中的
非法日期、seed 提示及 files=1/errors=1 属于 Mock/负向用例，不是实际仓库守卫失败；安装包
重复成员警告和“2 files”输出来自恶意包/最小包测试，不是交付 Bundle 的文件数。

重点专测包含：窄依赖、错参和 SQL 能力拒绝、解析/准备/来源/内部错误分类、来源与结果元数据、
行数上限、validator 不替换 payload、成功记账异常、同实例 LoopGuard 重复阻断；受控线程池
队满后的取消/期限、运行中超时/取消、外层 task 取消传播、迟到异常消费与结果不采纳；两个
lazy initializer 的旧导出顺序与 canonical 对象身份。

### 仓库外安装 A 门

新清单 `evaluations/mod_007_dispatcher_bundle_v1.json` 只定义 dispatcher_pilot 1.0.0。
测试实际构建 ZIP，在仓库外创建无 pip 的新 venv，将声明源码安装到其 site-packages，再用
该 venv 的 Python -I、空环境、无关 cwd 运行 demo。没有插入仓库/源码切片路径，没有替换
真实包 initializer；所有已加载 app 模块来源必须属于安装目录和声明清单。

安装后运行 Fake、指定设备和双临时 SQLite 查询；验证缺失数据库不创建、租户/角色/SQL
能力拒绝及预算/期限的执行前阻断。Fake 子进程持续开启网络连接/DNS、SQLite、禁止模块和
配置环境读取守卫，并先执行负向控制；仅放行空值的标准库演示/调试环境键
PYTHONASYNCIODEBUG、COLUMNS、LINES、TERM、LANG、LANGUAGE、LC_*。
asyncio 自用 socketpair 不等于外部网络连接，不把它冒充外联或关闭整个网络守卫。

安装器在写入前完成成员、路径、模式、大小、包锚点、UTF-8/LF 和语法预检；拒绝额外/缺失/
重复成员、路径穿越、符号链接、错误权限、损坏内容/元数据及已有 app，失败不留下部分 app。
它只适用于明确的空白目标，不是 Wheel/pip 包管理器，不承诺同名 app 命名空间合装、恶意并发
修改目标的原子安全或制品真实性认证；不新增 SHA-256 校验。正式移交需信任获准的源码来源。

可复现命令（在 WSL 激活上述 Python 环境）：

```bash
python -m unittest tests.test_tool_dispatcher tests.test_tool_dispatcher_boundaries \
  tests.test_tool_result_bridge tests.test_dispatcher_demo \
  tests.test_dispatcher_bundle_install tests.test_dispatcher_bundle_safety
python scripts/build_portable_unit.py dispatcher_pilot \
  --manifest evaluations/mod_007_dispatcher_bundle_v1.json \
  --output-dir runtime/portable/mod-007-20261024-r1
python -m app.bootstrap.dispatcher_demo
python -m app.bootstrap.dispatcher_demo --tool query_manufacturing_data \
  --arguments '{"sql":"SELECT 1"}'
```

前一条 demo 返回明确标记的 Fake 来源；后一条返回 denied/authorization、not_started，
调用预算为零。这是试点能力限制，**不代表旧全局 SQL 工具已经禁用**。

## 证据与下一项

证据位于 `runtime/quality/mod-007-20261024-r1/`：compatibility-tests.log、
dispatcher-acceptance-tests.log、equipment-review.log、ruff.log、repository-check.log、
boundary-report.json、refactor-contracts.log、behavior.json、old-portable.log、
dispatcher-build.log、independent-audit.json。交付源码 Bundle 位于
`runtime/portable/mod-007-20261024-r1/dispatcher_pilot-1.0.0.zip`。

当前归属清单 191 文件（163 Python、28 静态），精确依赖债务仍为 27，DB 候选 20，
兼容入口 13 / 静态消费 80；原七单元清单不变。MOD-005 活动源码复制清单因通用异常桥接
变为 27 文件，其历史 26 文件验收记录及 MOD-006 历史 27 文件记录不改写。

下一项按依赖是 MOD-010（最小 Runtime Ports/类型化上下文），不是直接推广 MOD-008。
随后 MOD-011 → MOD-013 → MOD-014 验证同一工具的 Ready/Loop 双路径，再批量迁移其余工具
并退出旧 SQL 能力。公司只读账号或报表/API 仍待明确，未接真实来源/真实模型或生产 ACL；
不宣称整个 Runtime 已解耦。本轮没有暂存、提交或推送，用户工作簿与既有脏改全部保留。
