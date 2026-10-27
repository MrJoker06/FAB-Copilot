# MOD-004 工具执行契约

日期：2026-10-24。状态：已验证，下一项 MOD-005。

## 本次交付

`app.agent_runtime.tools.contracts` 是一个仅依赖 Python 标准库的纯叶模块，定义初版
`TOOL_CONTRACT_VERSION = "1.0.0"`。它提供不可变、带 slots 的调用上下文、预算快照、
结果、错误、来源与范围信封，以及 principal 和取消信号的结构化 Protocol。

上下文保留调用方提供的 typed Port 聚合引用，结果信封保留 payload 引用；不会深拷贝，也不会
自行读取设置、时钟或环境变量，不调用数据 Port 或取消方法。为校验 Protocol 形状，它会读取
principal 的 claim 属性，但不认证或授权。预算由运行时拥有，本模块不计数或扣减。
截止时间为 `0.0` 合法；截止时间与耗时字段要求实际 `float`，拒绝布尔、整数、负数和非有限数值；
计数字段要求非负 `int`，也拒绝布尔。信封只冻结外层，调用方仍拥有可变 payload 的内容。

结果 status 与底层 execution state 分别表达事实；后者显式区分 `not_started`、
`completed`、`cancelled_confirmed` 与 `unknown`。例如服务端绑定阶段的内部错误可在
handler 从未调用时返回 `failed/not_started`。超时仅表示等待停止或状态未知，绝不自动
等同于底层调用已取消。错误只包含调用方已净化的
公共代码和消息，不接受异常对象，也不宣称任意字符串会被自动脱敏。

`ToolScope` 只包含租户、日期范围和有限的设备/制程/批次范围；`ToolSource` 只记录安全的
来源引用、适配器、受控来源种类和 Scope。它们不是行级 ACL 的执行器。

## 导入与兼容性

`app.agent_runtime.tools.__init__` 仍保留原有 `__all__` 的顺序和名称，但以显式相对导入
按需加载 catalog、executor 和 registry。已解析对象被缓存在包 globals 中，因此
`TOOLS` 与 `TOOL_HANDLERS` 仍是其 canonical 对象，原有 dict patch 的实时可见性不变。

新契约尚未接入旧 handler、catalog、registry、dispatcher 或公共 Schema。尤其是旧的
`query_manufacturing_data(sql)` 仍启用，按既定 MOD-008 退出条件后续处理；本次不移除或
隐藏它。

## 已验证范围

针对性测试覆盖：状态/错误/执行状态组合、严格数值和日期/Scope 验证、shallow immutable
信封、typed fake Port/principal、禁止 SQL/query 构造字段、lazy export 对象身份与 live
patch、`-I -S` canonical 导入无已加载的 settings/identity/report/knowledge/DB/catalog/
registry 模块，以及将唯一 `contracts.py` 拷贝到仓库外后的独立导入。

后者证明的是源文件叶模块隔离，不是已发布或可共同安装的 wheel。Fake principal 仅供
契约测试，不提供认证或授权证明。守卫的负向控制主动尝试禁用导入、`.env` 读取和 SQLite/socket
连接，并在访问前阻断；没有实际访问数据库、建立网络连接或调用模型。

## 实际验收记录

主代理在实现代理收尾后独立审查源码、导出顺序和测试，并执行：

```bash
python -m unittest tests.test_tool_contracts tests.test_agent_tool_runtime_boundaries \
  tests.test_agent_module_boundaries tests.test_agent_runtime_boundaries \
  tests.test_agent_execution_boundaries tests.test_ready_plan_execution \
  tests.test_refactor_contracts tests.test_modularization_boundaries \
  tests.test_module_boundaries tests.test_repository_checks
python scripts/modularization_baseline.py --skip-performance \
  --behavior evaluations/mod_002_behavior_baseline_v2.json
python scripts/check_repository.py
python scripts/refactor_contracts.py
python -m ruff check app/agent_runtime/tools/contracts.py \
  app/agent_runtime/tools/__init__.py tests/test_tool_contracts.py
python -m ruff format --check app/agent_runtime/tools/contracts.py \
  app/agent_runtime/tools/__init__.py tests/test_tool_contracts.py
git diff --check
```

全部通过：109 项定向测试（21.471 秒），其中新契约 18 项，包含 7 状态×4 执行状态×9 错误/无错误的
252 组组合；冻结行为 v2 的 diff 为空，旧重构契约保持，Ruff/格式/新旧仓库守卫通过。
边界清单现覆盖 172 个 app 文件（144 Python、28 前端），新增契约归属 tool_system/platform_core；
原 30 条依赖债务、13 个兼容入口/80 条静态消费记录与 19 个数据库候选未扩张或自动刷新。
数据库说明精确化为主库加 4 个附加部门库，共 5 库，不改实现。

独立验证产物位于 runtime/quality/mod-004-20261024-r1/：targeted.log、behavior-v2.log、
behavior-v2.json、refactor-contracts.log、repository-check.log、boundary-report.json。

本项未接入新业务执行路径、未变更公开工具 Schema/API/Trace；只运行上述必要验证，未重跑完整浏览器门或正式性能采样。
behavior-v2.json 中 performance 明确为 skipped，不将其记作新的性能通过；P0 完整门及 MOD-002 配对性能证据原样保留。
新增代码和文档使用 LF，未新增 SHA-256 内容校验门，未提交或推送。

## 下一步与回滚边界

MOD-005 选现有设备查询工具，建立其结构化输入、消费方 Data Port 和 Fake/SQLite 实现，再分别验收；
本项 Fake handler 是契约示例，尚不是该业务纵向切片，真实公司 DB/API 和生产身份继续单独授权。

本项生产代码变动仅新增 contracts.py 并调整工具包初始化时机。若需回滚，审查后仅撤回这两个文件的本项变更及
对应清单条目；不要回退整棵工作树或覆盖既有 MOD-001～003 改动。已解析旧导出仍缓存 canonical 对象，
只有显式访问旧业务导出才加载其实现；不保证依赖副作用发生在原来的包导入时点。
