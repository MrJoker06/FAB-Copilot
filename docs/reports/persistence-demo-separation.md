# persistence 功能拆分与模拟数据分离

日期：2026-11-12。关联 GitHub Issue #2 第 2 项。源码起点 `7859df9`；实施前将已完成的 TODO 治理与 MOD-029 重审文档单独提交为 `251b612`，本项运行代码以该提交为执行基线。提交和同步以 Git 实际记录为准。

## 目标与范围

将通用 SQLite 连接及应用自有状态的 Schema/迁移留在 `app/persistence/`；制造演示表、模拟元数据、样例缺陷目录、演示库搬迁与校验归 `app/demo_data/`。默认本地应用继续是演示装配；独立应用状态切片不需要安装或导入模拟数据包。

本项不搬动已有数据库文件，不迁移到公司数据库，不实现运行 DB 与历史知识库 DB 的下一轮物理分离，也不接入 LDAP。业务工具名称、描述、输入 Schema 和默认集合保持不变。

## 实际结构与职责

```text
app/
├── persistence/
│   ├── connection.py           SQLite 连接、PRAGMA/数学函数、行转换
│   ├── department_schemas.py   知识与 Agent 应用状态 Schema/表归属
│   ├── migrations.py          会话、模型、执行记录、个人知识的增量迁移
│   ├── database.py            应用状态初始化、连接/会话与写表定位
│   └── execution_store.py     现有执行记录；本项未改实现
├── demo_data/
│   ├── schemas.py             制造/设备/质量演示 Schema、模拟元数据、旧单库布局
│   ├── database.py            五库演示组合、样例目录、旧库迁移、完整性/预测窗口校验
│   ├── seed.py                显式种子与模拟生成入口
│   └── ...                    原有 Fake 与模拟 Provider
└── bootstrap/
    └── storage_identity_assembly.py  默认演示存储的显式绑定
```

应用状态默认会话以内存连接作为挂载入口，分别挂载知识和 Agent 文件，保留 `knowledge.*`、`agent.*` 写入别名和无前缀读取视图。它不挂载或初始化制造、设备、质量库；显式 `path` 仍为独立 SQLite 连接。会话退出关闭连接，不隐式提交，异常或未提交写入回滚；不新增跨库原子提交保证。

演示组合显式调用应用状态初始化，再初始化三个演示业务库。旧单库布局仅作为演示/测试兼容数据形态留在 `demo_data.schemas`，不进入应用状态切片。模拟事实与参考资料仍由 `seed` 显式生成；应用状态初始化本身不插入演示行。

固定报表与旧 SQLite 知识 Adapter 通过已有 `StorageIdentityBindings` 取得会话和缺陷目录，避免把模拟包依赖放回业务查询或应用状态模块。新依赖守卫禁止 `persistence` 导入 `demo_data`、bootstrap 或业务 Tool，纯模块也不得导入拆出的连接/迁移模块；实际注入反例在两端被拒绝。

## 接口迁移与兼容说明

| 原调用/职责 | 本项后的归属 |
| --- | --- |
| `persistence.database.initialize/connect/db_session/department_paths` | 仅应用状态；不再代表五个演示库或完整模拟单库 |
| 五库演示初始化、完整会话、`ensure_department_databases`、`migrate_legacy_database`、`validate_department_databases`、缺陷目录读写 | `demo_data.database`；应用、脚本及测试中的真实消费者已迁移 |
| 模型/会话/个人知识迁移常量与私有迁移函数 | `persistence.migrations` |
| `MANUFACTURING_SCHEMA`、`EQUIPMENT_SCHEMA`、`QUALITY_SCHEMA`、演示表归属及旧 `SCHEMA` | `demo_data.schemas` |
| 通用连接与行转换 | `persistence.connection`；原 `database.rows_to_dicts` 保留同一函数导出 |

不为旧模拟 API 在 persistence 新增转发层。直接程序调用固定报表时需显式安装存储绑定，或注入已有绑定；默认应用已安装。默认组合的实时 patch 目标随实际所有者变为 `app.demo_data.database.db_session`，相关等价测试改为注入实际会话，不再 patch 已退出该链路的应用状态入口。

本项是职责拆分而非任意数据库访问的安全沙箱。显式 SQLite 路径仍须由可信调用方提供；旧状态 Schema 的演示身份默认值未在本项重做，登录身份和授权见 Issue #3。

## 独立交付

新增 `application_storage` Profile：10 个标准库 Python 文件、无外部依赖。Windows 与 WSL 在仓库外创建新 venv，使用真实 MOD-024 制品安装该 Profile；安装目标没有 `app/demo_data`，初始化和重连后仍可读写会话状态，业务表查询明确失败，导入来源位于目标 site-packages。

原 `tool_sources` 104 文件、`skill_release` 111 文件加 4 个资源、`model_transport` 5 文件不扩张。新 Profile 与它们共享 3 个文件，四 Profile 源码并集 160、含资源 164。当前受管源码 313（285 Python、28 静态），发布组 317 个源码/资源成员；DB 候选 33。新增文件拥有唯一制品归属。MOD-024 仍按完整版本组构建/校验，Profile 只决定安装成员；本项没有改成任意 ZIP 独立升级机制。

## 验证记录

以下保留实际失败和环境限制；定向通过不表示完整门全绿。原始日志及机器摘要在忽略的 `runtime/quality/`，不提交数据库副本、配置或凭据。

| 验证 | 结果 |
| --- | --- |
| 起点 Windows / WSL：`python -m unittest tests.test_persistence_module_boundaries tests.test_model_capabilities tests.test_sqlite_math_functions tests.test_simulation_profile` | 两端各 24 项通过 |
| Windows：上述存储/模拟/迁移测试、存储身份 Port、三组报表等价及知识来源测试 | 70 项通过；旧报表夹具仍有 SQLite ResourceWarning |
| Windows：`python -m unittest tests.test_persistence_separation tests.test_module_release` | 14 项通过（新增边界反例前）；边界反例随后单独 1 项通过 |
| WSL Python 3.11 venv：存储/来源/交付相关 11 模块 | 75 项，唯一错误为存储身份测试导入 PIL 缺失；其余通过 |
| WSL Conda Python 3.11.15：`tests.test_storage_identity_ports tests.test_persistence_separation` | 15 项通过（新增边界反例前）；实际仓库外安装包含在其中 |
| 工具清单逐字节对照 | `TOOLS`、`_NATIVE_CATALOG_JSON`、`_KNOWLEDGE_CATALOG_JSON` 与执行基线一致 |
| SQL 布局与默认目录对照 | 五个部门库及旧单库的 sqlite_master、迁移版本/描述、缺陷别名行均与基线一致，未比较时间戳等易变数据 |
| Windows 全量 unittest | 1472 项，12 失败/10 错误/3 跳过，457.605 秒；该轮发现时新增分离测试为 5 项，后追加的边界反例另跑 1 项通过，未为此重跑全量；不是全绿 |
| 基线失败复核 | 首次完整导出树缺少忽略的参考 DB，1391 项出现导入错误；只读备份补齐隔离参考夹具后重跑相关 15 模块共 207 项，13 失败/10 错误。当前全量的每个失败/错误标识都在该复核中出现，无新增失败标识；不把该复核称为一次完整基线全量通过 |
| Windows 与 WSL 真实服务启动 | 独立临时生成 1 天模拟数据，启动 uvicorn、访问 `/api/health` 和指定日期 `/api/reports/dashboard` 均通过，随后停止进程 |
| Linux Playwright：`npm run test:e2e` | 17/17，通过 |
| WSL Conda：`python scripts/run_quality_gate.py full` | Python 非系统阶段 1352 项，7 失败/4 错误/2 跳过，341.660 秒；四个导入错误均为缺 jsonschema，失败标识与旧记录及基线复核一致，门退出 1；后续质量门阶段未由该命令执行 |
| 仓库与边界 | `check_repository`、两个边界检查器通过；`files=313 errors=0` |

初轮接入发现并修复了报表行转换的遗漏引用、旧会话 patch 目标及测试侧显式绑定问题；交付测试最初将整组校验成员误当作选择安装成员，已改为核对实际 Profile 和安装目标。边界反例曾误选未登记为纯模块的 routing 文件，修正为已登记的 contracts 后，两端各 1 项（含两类反例）通过，未改变原纯模块分类。新增测试使用独立固定预期，不以被测函数生成自己的业务期望。

启动探测最初使用不存在的 `/api/overview`，Windows 返回 404；WSL 短窗口探测也曾超时，服务日志显示已经启动。修正为真实报表路径、禁用回环代理并使用诊断等待窗口后两端通过；未修改产品超时或冻结性能阈值，不抹去前次失败。

`check_default_tool_migration.py` 在 Conda 中无法导入已有 `_TOOL_REPLACEMENTS`，同一导出基线复现；原 Python 3.11 venv 还缺 PIL。本项没有顺带修改该旧脚本或将其报告为通过，工具清单另有独立逐字节对照。

Linux full 未通过；浏览器以独立命令执行并通过，不称为 full 全绿，未通过放宽阈值或安装依赖掩盖原始结果。Windows 环境缺 coverage，未声称有新的完整覆盖率。真实模型、Live、公司数据库/API、LDAP 和生产权限接入未运行。
