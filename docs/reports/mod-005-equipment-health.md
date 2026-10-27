# MOD-005 设备健康查询纵向切片

日期：2026-10-24。状态：已验证，下一项 MOD-006。

## 交付与依赖方向

本项新增未注册的 `get_equipment_health` 试点，而不是切换现有生产兼容调用路径。

| 文件 / 目录 | 职责 |
| --- | --- |
| `app/agent_runtime/tools/definition.py` | 标准库级 `ToolDefinition` / `ToolBinding`；输入解析和公开 Schema 委托给同一个输入模型 |
| `app/manufacturing/equipment_health/contracts.py` | 输入、有效查询范围、聚合行、快照、消费方 Data Port 和输出验证 |
| `app/manufacturing/equipment_health/handler.py` | 窄依赖、显式时钟、健康分级与排序、来源范围校验及结果信封；不含 SQL |
| `app/manufacturing/equipment_health/binding.py` | 同一 Definition/handler 与所选 Port 的显式绑定 |
| `app/integrations/manufacturing/fake_equipment_health.py` | 按有效查询精确匹配的夹具，无未知范围复用或来源回退 |
| `app/integrations/manufacturing/sqlite_equipment_health.py` | 双来源只读 SQLite 查询与连接生命周期 |
| `scripts/demo_equipment_health.py` | 显式选择适配器、可信操作员参数和受控 JSON 输出的独立演示 |
| `evaluations/mod_005_equipment_health_source_v1.json` | 26 个实际源码文件的复制清单，包括现有 Runtime 父包所需的标准库闭包 |

业务核心只依赖自己定义的 Port 及纯工具契约，技术 Adapter 反向实现该 Port。
工具框架没有新增对设备业务的导入。Fake 与 SQLite 共用同一 Definition 和 handler，
替换来源只更换装配，不修改业务核心。

## 输入、结果及兼容性

契约版本为 `1.0.0`。公开工具名称、描述、四个可选参数及 Schema 与旧 catalog 精确比较通过。
只接收 `start/end/process_step/equipment_id`；SQL、任意查询文本、租户、URL、路径等额外字段
被拒绝。可信主体和来源配置不从模型参数中获取。

两个日期分别以注入的当天默认值补齐：开始为当天减 89 天，结束为当天；不是相对用户所填结束日
计算开始日。设备过滤优先于制程过滤，有效来源范围不再声称同时应用被忽略的制程条件。
设备/已知制程按旧语义转大写。保留空日期字符串的默认语义。

返回原有八个字段，保留 SQLite 的三位/两位/一位小数聚合、全部事件 duration 求和、
无事件时补零、健康等级与排序。特别验证 `499.96 → 500.0 → Critical`，不以 Python
舍入替代 SQLite ROUND。完整来源 Scope 必须匹配租户、日期、设备/制程和 equipment grain。
计数、有限数值、通过率范围和异常数不大于运行数均有校验，损坏来源不得补造为正常数据。

新增验证是试点契约增强，而非宣称与旧函数所有偶然输入完全等价：显式 JSON null、未知制程、
非字符串、空白设备、额外参数、倒置/超 730 天范围及无法扩展为次日的日期均明确拒绝。
这些限制目前仅作用于试点；旧公开工具路径没有被悄然收紧。

## 资源与隔离验收

SQLite 显式接收两个文件路径，只连接制造主库并挂载一个设备库，即 `main.process_runs` 和
`equipment.equipment_events`。两个 URI 均为 `mode=ro`，并启用 `query_only`；SQL 过滤值绑定参数，
不接收模型 SQL，也不调用全局 `database.connect/db_session`。缺库不创建，缺表/坏数据明确失败，
不建表、迁移、seed，不回退 Fake，不读取其他部门库。

已使用真实临时双库连接代理验证成功、挂载失败、查询失败和受控 progress 超时都关闭连接；
查询时挂载集合恰为 main/equipment，两库写入均被拒绝。坏指标触发来源错误且真实底层连接已关闭。
busy timeout 与 progress deadline 有界并拒绝布尔值；超时测试为受控回调注入，不是长查询性能测试，
也不代表公共 Dispatcher 已具备统一取消或硬墙钟期限。

仓库外测试逐文件复制清单源码，不替换包初始化器、不复制全 app。在临时目录以 `-I -S` 和空环境
实际执行 Fake、SQLite、非法 SQL 参数、坏 JSON 和缺失来源场景。捕获 CLI 退出后逐个检查所有
`app.*` 模块的真实来源，必须属于临时单元和清单；主动拒绝环境读取、禁止模块和 socket 创建，
并执行负向控制。标准库 argparse 的翻译/终端排版被固定，避免把其展示配置读取混同业务配置依赖。
Fake 路径不导入 SQLite adapter；仅产生显式的两个临时夹具库，不产生缺失库、`.env` 或日志目录。
带 `#` / `?` 的路径也实际运行通过。

旧新对照只 patch 旧报表的数据会话和日期时钟，不用新实现的日期计算覆盖旧逻辑。测试分别检查默认
90 天首日、单侧日期、制程、冲突设备优先、日期首尾、相同排序键、无事件和零行，并比较完整数据、
JSON 与预期设备/运行数。独立演示中参数错误为 `INVALID_ARGUMENTS`，来源失败为 `SOURCE_FAILURE`，
意外异常为脱敏 `INTERNAL_ERROR`；这只是 CLI 桥接，不是提前实现公共 Dispatcher/Policy。

## 边界清单

新增 9 个 app 源文件，当前清单为 181 文件（153 Python、28 静态文件）。原有 30 条依赖债务、
13 个兼容入口和 80 条静态消费记录保留；DB 候选从 19 增至 20，仅增加新只读 Adapter，台账明确
它在 MOD-009 做符合性验收并保留，而非要求删除。

MOD-003 目标依赖增加 `business_tools → tool_system` 与 `integrations → tool_system`，用于消费
纯工具契约；`tool_system → business_tools` 仍不允许。旧粗粒度守卫相应增加
`manufacturing → agent_runtime`，不是声称旧域级白名单完全未变；MOD-003 的细粒度所有权与
精确债务守卫继续限制实际方向，不能借此引入新框架反向业务依赖。

## 实际验证

WSL Ubuntu-24.04，Python 3.11.15，环境 `fab-insight-agent`。主审最后一次执行：

```bash
python -m unittest \
  tests.test_equipment_health_tool tests.test_equipment_health_equivalence \
  tests.test_equipment_health_lifecycle tests.test_equipment_health_portable \
  tests.test_tool_contracts tests.test_agent_tool_runtime_boundaries \
  tests.test_modularization_boundaries tests.test_module_boundaries \
  tests.test_repository_checks tests.test_agent_runtime_boundaries \
  tests.test_ready_plan_execution tests.test_refactor_contracts
python scripts/check_repository.py
python scripts/check_modularization_boundaries.py --report runtime/quality/mod-005-20261024-r1/boundary-report.json
python scripts/refactor_contracts.py
python scripts/modularization_baseline.py --skip-performance --behavior evaluations/mod_002_behavior_baseline_v2.json
git diff --check
```

结果：130 项定向测试通过（46.307 秒）；真实双边界守卫/仓库检查通过，MOD-003 为
`181 files / 0 errors`；冻结行为 v2 差异为空，旧重构契约通过。新增源码/测试的 Ruff 与格式检查通过。
联合测试日志末尾的 `files=1 errors=1` 为非法配置负向测试的预期输出，不是真实仓库守卫结果。

主审证据位于 `runtime/quality/mod-005-20261024-r1/`：`targeted-final.log`、`boundary-report.json`、
`repository-check.log`、`refactor-contracts.log`、`behavior-final.json` 及 Ruff/格式日志。
最初的 Ruff 宽异常捕获错误记录保留在 `ruff-source.log`；CLI 脱敏边界采用局部、带说明的豁免，
未降低仓库检查规则。实现子代理额度耗尽后，由主审完成小范围测试/静态检查收尾并实际复验。
随后新增测试的一处 SIM117 样式错误也保留在 `ruff-final-r2.log`；合并上下文管理器后，
最终 Ruff/格式检查通过（`ruff-final-r3.log`），相关 3 项生命周期测试再次通过。

本轮为未接入旧链路的增量试点，未重跑完整质量门、浏览器全量、覆盖率或性能门；性能明确 skipped。
不以旧阶段的全量/覆盖率数字冒充本轮结果。

## 未完成的后续边界与回退

旧 `reports.equipment_health`、catalog、registry、executor、Ready/Loop 均未切换，
`query_manufacturing_data(sql)` 仍启用，按 MOD-008 退出。MOD-006 接单一 Registry 和显式
LegacyBindingAdapter；MOD-007 接公共 Dispatcher，后续再接 Ready/Loop 双路径。

该源码复制单元不是第八个便携制品、可合装 Wheel 或 MOD-007 的正式 A 门安装。它仍携带现有
Runtime 父包的纯闭包，不代表 Runtime 已整体解耦。演示租户绑定不是生产 SSO/行级 ACL；
跨库实时一致快照、刷新时间、公司字段口径/权限和实际 DB/API 接入需按后续任务另验。
没有修改真实 data、接入公司系统或提交/推送。回退时停止调用 demo/新 binding 即可，旧执行路径不依赖它；
源文件和所有权清单的删除须成套处理，不能删除或覆盖此前 MOD-001～004 的未提交改动。
