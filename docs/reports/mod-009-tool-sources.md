# MOD-009：批量工具来源替换与新增能力入口

日期：2026-11-06。基线：`6dd6544`。状态：已验证。按用户要求，最终验收通过后单任务提交并同步；提交及远程状态以 Git 记录为准。

## 实现与验收边界

`app/bootstrap/tool_sources.py` 提供显式的 `ToolSources` 和 `create_tool_bindings`。七个字段使用消费方定义的 Data Port；只为已提供的 Port 建立绑定，缺少的族不会自动发现来源、读取配置或初始化数据库。所有原生定义和处理器继续来自原有 canonical binding 工厂，没有增加第二套 Registry。

完整组合覆盖原有 21 项工具。替换来源只改变装配参数，工具定义、Schema、Handler 和 Runtime 保持一致；数据源可以返回各自的数据，验收不假定不同夹具的业务数值相同。

| 工具族 | 数量 | Fake 路径 | 替代路径 |
| --- | ---: | --- | --- |
| 设备健康 | 1 | FakeEquipmentHealthAdapter | SQLiteEquipmentHealthAdapter |
| Cpk / 传感器 | 2 | FakeProcessDiagnosticsAdapter | SQLiteProcessDiagnosticsAdapter |
| 总览 / 良率 / 通过率 | 3 | FakeProductionReportsAdapter | SQLiteProductionReportsAdapter |
| 生产率 / Pareto / 异常 | 3 | FakeOperationalReportsAdapter | SQLiteOperationalReportsAdapter |
| 八项具名制造查询 | 8 | FakeNamedQueryAdapter | SQLiteNamedQueryAdapter |
| 企业目录 / 汇总 / 样本 | 3 | FakeEnterpriseToolsAdapter | ProviderEnterpriseToolsAdapter + 内存 Provider 夹具 |
| 知识检索 | 1 | FakeKnowledgeSearchAdapter | BackendKnowledgeSearchAdapter + 内存搜索后端夹具 |

替代组合中 17 项明确标为 SQLite，企业与知识的 4 项仍标为 FAKE。SQLite 使用测试临时库和只读 Adapter；Provider/Backend 夹具没有接入真实公司数据库、报表 API 或模型端点。未来公司来源应实现相同的业务 Port，并单独验收权限、标识映射和统计口径。

新增可选 `get_equipment_health_summary`，复用原设备健康 Handler 的等级计算，返回设备总数及 Critical / Watch / Healthy 数量。来源和 Scope 保留原设备粒度；摘要的一行结果不代表新增了一个已获授权的数据粒度。它只在显式开启时注册，默认 21 项业务工具清单没有变化，也没有修改 Ready/Loop 内核或证据规则。

## 实际执行链与拒绝行为

统一演示通过 `assemble_agent → AgentRun → Ready / 两阶段 Fake Loop → Dispatcher → ToolBinding → Data Port` 执行。Ready 不调用模型选择工具；Loop 的第二次模型请求包含实际的 user、assistant tool_calls 和 tool 消息。输出来自实际 ToolResult，包含数据、来源、完整 Scope、脱敏错误和 Guard 计数。

演示使用固定服务端 analyst/demo Policy。注入的可信测试 principal 仅改变调用身份，不改变授权规则。角色不符、租户不符、预算为零、SQL 参数、未知工具及旧 `query_manufacturing_data` 均在两个路径上拒绝，来源调用和 Guard 有效调用数均为零。来源失败只调用一次，错误不泄露夹具中的私有路径，不隐式换来源。

## 查看效果

在仓库根目录使用对应平台的 Python 环境：

```bash
python -m app.bootstrap.tool_sources_demo --mode ready --tool get_fab_overview
python scripts/demo_tool_sources.py --mode loop --tool get_lot_identity
python scripts/demo_tool_sources.py --mode loop --summary --tool get_equipment_health_summary
```

输出明确包含 `profile` 和 `company_connected: false`。直接脚本支持绝对路径及无关工作目录；模块入口从包含 `app` 包的目录运行。失败返回非零退出码，CLI 不输出原始依赖异常。

`--profile local-fixture` 必须显式提供已有的 `--manufacturing-db`、`--equipment-db`、`--quality-db`；入口不建表、不 seed、不回退 Fake。实际查询所需表与字段由各 Port 的现有 SQLite Adapter 契约决定，文件存在不代表 Schema 已通过。可运行以下测试查看临时联合夹具的双路径结果：

```bash
python -W error::ResourceWarning -m unittest tests.test_tool_sources_runtime
python -m unittest tests.test_tool_sources_portable
```

## 独立验收与来源审计

`evaluations/mod_009_tool_sources_v1.json` 声明 **101 个真实源码文件**。隔离测试逐文件复制，保留原包锚点，以 `-I -S`、无关 cwd 和持续守卫执行 21 项工具加扩展工具的 Ready/Loop，共 44 条路径。WSL 子进程环境为空；Windows 只保留解释器/WinSock 启动所需的 OS 环境项，运行期间禁止业务环境变量读取和枚举。

守卫覆盖配置、存储、旧 service/compatibility 和默认装配导入，以及网络、DNS、SQLite、进程启动和系统命令；包含真实负向控制。Windows 仅允许标准库 asyncio 建立自身通知管道的精确 loopback 调用。实际业务链的网络/SQLite 审计均为零，应用模块来源均在复制目录内，默认 Registry 保持为空。该清单保留 Runtime 包锚点带入的 Coordinator/stages，不宣称旧协调器已退役。这是可运行源码切片，正式 Wheel 交付仍属于 P5。

| 主审验证 | 实际结果 |
| --- | --- |
| 起始 WSL 基线 | 79 项通过，6.363 秒 |
| WSL 新增专项 | 9/9 通过，1.561 秒；ResourceWarning 按错误处理 |
| 原生 Windows 新增专项 | 9/9 通过，1.475 秒；ResourceWarning 按错误处理 |
| 替换矩阵 | 21 项 × 两组来源 × Ready/Loop；17 项 SQLite 的独立字面量指标、日期/批次 Scope 和 grain 通过；企业数据/Scope 与知识引用另作对照 |
| 两端 CLI | 各 6 组通过：模块、直接脚本、无关 cwd、缺少本地库及旧 SQL 的 Ready/Loop 拒绝 |
| 隔离源码 | 两端 101 文件、44 条路径通过；无业务网络/SQLite/配置读取 |
| 静态与格式 | 新增 7 个 Python 文件 Ruff / format 通过 |
| 完整离线阶段门 | 退出码 0，480.3 秒；Python 1226 项（含 2 个平台跳过）、覆盖率 88%；Node 61/61、浏览器 17/17；RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7 |

本轮计划、初始状态、主审发现和结果保存在 `runtime/quality/mod-009-20261105-r1/`。主审修正了初版 Handler 直调、替代 Profile 仍使用 Fake Adapter、调用身份影响演示 Policy、关键字参数、模块入口、扩展工具选择条件和 SQLite 夹具释放等问题。CLI 的 Windows 验证显式启用 UTF-8 子进程输出，避免验证程序用 UTF-8 解码平台默认编码。

## 保留依赖与后续

新增三个应用源码文件，受管源码为 **275 文件：247 Python / 28 静态**。原有 272 个受管源码及 4 个 Skill 文本资产逐字节保留；默认 HTTP、21 项能力、历史 patch 身份及冻结制品未改变。本轮没有默认热路径变化，未重复正式 1000×2 性能比较，也未启用 Live。

边界仍为 **29 条依赖债务、25 个 DB 候选、13 个兼容入口 / 97 个静态消费者**；允许依赖、债务边和消费者清单未扩张。`manufacturing.reports` 的旧 API/Python 报表路径、`enterprise_data` 的身份依赖，以及演示 seed/启动组合继续保留。它们的剩余退出任务明确交给 MOD-015 的兼容消费者审查，没有删除债务或把模拟库当作公司来源前置条件。

下一项为 **MOD-012：完整模型客户端生命周期**，随后 MOD-015 统一收口 Runtime 类型、状态、事件及兼容路径。公司接入、Checkpoint 和整体交付仍按原计划分别验收。回退本项只需撤销可选装配、扩展和验收增量，不涉及持久化数据迁移。
