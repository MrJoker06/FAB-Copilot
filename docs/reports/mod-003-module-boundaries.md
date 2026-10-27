# MOD-003：模块责任与迁移边界

日期：2026-10-24。状态：已验证；P0 完整离线门 r2 通过，下一项 MOD-004。

本任务建立可执行的迁移清单，不移动业务源码、不修改数据库、不禁用旧工具。清单通过不代表现有耦合已消除，也不代表真实公司数据源或生产权限已验收。

## 1. 文件与制品归属

[显式清单](../../evaluations/mod_003_boundaries_v1.json) 覆盖 171 个 app 普通文件：143 个 Python、28 个前端文件。每个文件恰有一个主要逻辑责任和一个建议发布所有者；混合文件还记录拆分目标、原因和退出工作包。

| 逻辑责任 | 文件数 | 建议制品组 |
| --- | ---: | --- |
| application_bootstrap | 24 | application_bundle |
| static_ui | 28 | application_bundle |
| runtime | 36 | platform_core |
| tool_system | 4 | platform_core |
| orchestration | 17 | platform_core |
| context_memory | 11 | platform_core |
| core_contracts_configuration | 3 | platform_core |
| evidence | 5 | platform_core |
| knowledge（含个人知识用例） | 23 | platform_core |
| manufacturing_domain | 2 | platform_core |
| models | 5 | platform_core |
| observability | 4 | platform_core |
| integrations | 2 | enterprise_adapters |
| persistence | 4 | enterprise_adapters |
| business_tools | 2 | manufacturing_capability |
| simulation | 1 | simulation_fixtures |

制品组是目标归属，不是已构建的 wheel；enterprise_adapters 暂含现有演示身份、SQLite 和应用自有存储适配实现，并不表示完成了企业接入。一个制品可以包含多个逻辑模块，不按目录强制建包。

已有七个源码 ZIP 仍是独立验收单元，不可直接当作共装发布包。四项 app 文件重叠已精确登记，并指定未来唯一发布所有者：app/__init__.py、app/manufacturing/__init__.py、app/manufacturing/processes.py、app/knowledge/__init__.py。此项只检查 app 成员，不宣称覆盖测试/评测资源的全部发布所有权。

## 2. 目标依赖与现状债务

[检查器](../../scripts/check_modularization_boundaries.py) 不导入 app，使用 AST 读取源文件。目标规则禁止工具框架依赖业务 Handler，禁止 Runtime 直接依赖具体集成、持久化或装配，禁止业务工具直接依赖 SQL 持久化。装配层可以知道所有具体实现；其他模块只列明确允许的依赖。

按此目标，当前存在 30 条精确的 source→target 债务：Runtime 兼容装配、工具 Catalog/Registry、会话、证据、知识后端选择、制造查询、模型存储与持久化反向初始化等。每条有原因和 MOD-006/008/011/012/015 等对应退出任务。新越界、重复债务和已不存在的旧债务均失败，不提供自动接受现状的刷新命令。

以下文件明确仍混合职责：

- agent_runtime/compatibility.py：Runtime 兼容与具体装配。
- agent_runtime/tools/registry.py：工具注册与业务绑定。
- core/settings.py：配置契约与环境装载。
- manufacturing/reports.py：业务 Handler、SQL 与领域计算。
- manufacturing/enterprise_data.py：业务包装、集成与合成数据回退。

identity_contracts.py 属纯契约，core/identity.py 属环境身份适配器；model_gateway/compatibility.py 是真实供应商协议实现，不作为待删转发门面。

## 3. 兼容入口与数据库台账

兼容台账含 13 个入口，记录 80 条已知静态消费记录（不是 80 个独立消费者）：导入、字面量动态导入、常见 unittest.mock patch、patch.object 和 patch.dict。run_agent 保留公开入口；TOOLS/TOOL_HANDLERS 保留对象身份及实时修改行为；5 个 coordinator 转发模块和 context_resolver 记录 P2 收敛条件。_EXPORT_NAMES 来自 globals 动态计算，因此采用保守的模块级登记，不假称已静态枚举全部导出名。

数据库候选覆盖 19 个文件，记录导入、调用符号、有限的字面 SQL 表名提示、主要责任、存储用途、初始化副作用和退出任务。会话/模型/个人知识等内部存储不强行变成模型工具；制造业务读取经后续 Tool→Data Port→Adapter 改造。

全局 connect/db_session 仍可能初始化缺失存储，连接主库并挂载 4 个附加部门库（总计 5 库）；应用启动还可能执行演示 seed。台账通过不代表这些副作用已收缩。公司业务库不由应用建表、迁移或 seed，真实来源另按授权验收。

旧 query_manufacturing_data(sql) 仍由 Catalog 暴露、Registry 绑定到 reports.safe_select，SYSTEM_PROMPT 仍包含数据库提示。MOD-004～007 建立受控契约与执行边界，MOD-008 单独版本化移除该能力，MOD-009/015 验证替代用例与双路径拒绝；本任务不伪装为已完成无 SQL 目标。

## 4. 验收与限制

已实际执行并通过：

```text
python -m unittest tests.test_modularization_boundaries tests.test_repository_checks tests.test_module_boundaries
python -m ruff check scripts/check_modularization_boundaries.py tests/test_modularization_boundaries.py
python scripts/check_repository.py
git diff --check
```

定向测试 55 项，包含完整合法 Fake 项目、真实仓库、归属遗漏/重复/孤儿、路径与 symlink、依赖新增/陈旧、制品重叠、别名与包内相对导入、兼容消费者新增/陈旧、DB 候选漂移、畸形嵌套清单及新进程无 app 导入验证。CLI 的失败场景必须报出目标规则，不能借前置错误产生假阳性。

完整离线门首轮 r1：786 项 Python 和其他离线分项通过，浏览器 16/17；会话旅程失败。Trace 证明新建会话接口已返回新 ID，但测试未等待客户端状态更新，第二条聊天请求仍使用旧 ID。测试现等待响应、localStorage 和界面完成，并额外断言发送请求的 session_id；原有两个不同会话、恢复、重命名与删除断言均保留。该同步修正连续 3 次通过（28.9 秒）。没有修改生产前端，也不宣称快速连续操作的生产竞态已修复。

r1/full-gate.log、failed-browser-trace.zip、system_test_timings.json 和 browser-regression.log 均保留在 runtime/quality/mod-003-20261024-r1/。第二轮完整门在 runtime/quality/mod-003-20261024-r2/full-gate.log，实际 exit 0：786 项 Python（716 非系统、70 系统）、coverage 89%、Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7、Playwright 17/17（1.1 分钟）。系统测试总墙钟 115.756679168 秒，五组及总预算均通过；timings 已另存至 r2，不覆盖 r1。本任务未改业务执行源码，不重跑或改写 MOD-002 的正式性能比较证据。

需要机器报告时，先创建目标目录，再执行：

```text
python scripts/check_modularization_boundaries.py --report runtime/quality/mod-003-20261024-r1/boundary-report.json
```

静态限制：目标依赖表约束 app 内逻辑模块间的已知导入，不是第三方包/系统调用的通用沙箱；既有纯模块守卫和便携验收继续保留。不能证明动态 SQL 数据流、任意赋值/重绑定后的别名、计算式导入/patch、外部消费者、真实 ACL 或全部运行期访问；SQL 提示不是完整解析器。候选/未知项必须人工审查。普通解耦、新 SQL 能力收缩与真实企业接入分别验收，不以此静态门相互替代。
