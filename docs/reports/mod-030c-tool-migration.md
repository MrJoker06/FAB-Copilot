# MOD-030c：业务 Tool 与数据来源迁移

执行起点：`5239c04`。状态：分批实施中；未推送。MOD-030d/030e 的目录退出和阶段验收尚未完成。

本报告记录实际完成的批次，不以目录改名代替业务验收。遵循 [总方案](../skill-tool-standardization-plan.md)，Playbook 证据语义留给 MOD-031，本轮不改变。

## 环境与验收方式

- Windows：`.venv-win/Scripts/python.exe`，Python 3.13.5。
- WSL Ubuntu-24.04：`/mnt/d/modern_agents/agents/fab-insight-agent-refactor-v2-platform/.venv/bin/python`，Python 3.11.15；`PYTHONPATH=.`。
- Git 使用 WSL。`check_repository.py` 也在 WSL 运行：本工作树 Git 元数据含 POSIX 路径，Windows 原生 Git 无法解析；不改写 `.git`。
- 日志及独立导出树位于忽略目录 `runtime/quality/mod030cde/`。每批从 `git archive 5239c04` 导出，分别采集 `TOOLS`、`_NATIVE_CATALOG_JSON`、`_KNOWLEDGE_CATALOG_JSON` 和对 21 个定义执行 `register_native` 的注册视图，使用同一输出逻辑比较完整 JSON 字节，无新增哈希门禁。
- 输出 Schema 描述处理器成功返回的 data；拒绝不伪装为成功 data，保留既有错误/拒绝语义。

## c1：equipment_health

### 文件与消费者

| 旧位置 | 新位置/处理 |
| --- | --- |
| `manufacturing/equipment_health/{__init__,binding,contracts,handler,summary}.py` | `app/tools/equipment_health/`，保留现有职责拆分 |
| `integrations/manufacturing/sqlite_equipment_health.py` | `app/tools/equipment_health/data_source.py` |
| `integrations/manufacturing/fake_equipment_health.py` | `app/demo_data/tool_sources/equipment_health.py` |
| 新包锚点 | `app/demo_data/__init__.py`、`app/demo_data/tool_sources/__init__.py` |

消费者按实际扫描更新：默认装配、定义集合、显式来源装配、Agent/Ready/Loop/Dispatcher 演示、设备演示 CLI，以及对应测试导入、patch 目标与复制切片。与 030a 清单相比，030b 已存在的 `app/tools/__init__.py` 需加入使用设备工具的切片；未发现须保留旧 Python 导入的仓库外消费者。

补充设备健康及可选健康汇总的 title/output_schema；不修改模型工具名、描述、输入 Schema 或查询/排序/权限语义。新增 Schema 测试执行真实处理器，覆盖成功、空结果、非法日期与异租户拒绝；现有 SQLite 对照、只读、生命周期和范围检查继续执行。

### 清单变更及原因

- MOD-003 唯一归属、DB 候选与数据库台账中的路径跟随迁移；DB 候选按扫描顺序重排，查询内容未变。新增两个真实包锚点归 simulation/simulation_fixtures。
- MOD-005、MOD-007、MOD-009、MOD-024 的源码路径和必需包锚点同步；测试内显式切片同步。不是重录业务期望值。
- MOD-024 成员 300 → 302；tool_sources 源码 105 → 108；skill_release 107 不变；组合源码并集 149 → 151，加四份 Skill 资源为 155。数字仅用于与实际清单对照。
- `module_boundaries_v1.json` 的路径引用随迁移更新；当前结构文档更新已迁设备能力的位置。历史报告不改。

### 验收

两平台命令：

```text
python -m unittest tests.test_tool_output_schemas tests.test_equipment_health_tool tests.test_equipment_health_equivalence tests.test_equipment_health_lifecycle tests.test_equipment_health_dispatch tests.test_equipment_health_portable tests.test_tool_registry_portable tests.test_tool_sources_portable
python scripts/check_module_boundaries.py
python scripts/check_modularization_boundaries.py
```

最终两端各 34 项通过；模块边界通过，MOD-003 为 298 文件/0 错误。WSL `python scripts/check_repository.py` 和 `git diff --check` 通过。已迁设备组在 app/scripts/tests/evaluations/run.py 中无旧路径残留。新旧四类目录逐字节一致（`c1-catalog-{baseline,current}.json`）。

过程问题保留：首次边界检查发现 DB 候选排序漂移，修正路径排序后通过；新增非法日期测试最初误以为 parse 阶段完成日期解析，改为调用真实处理器验证既有 resolve 行为后通过，未修改业务实现。Windows 资源回收警告保留于日志，测试无失败。

## c2：process_diagnostics 与趋势 Fake

- `manufacturing/process_diagnostics/{__init__,binding,contracts,handler}.py` → `app/tools/process_diagnostics/`；SQLite 来源 → 组内 `data_source.py`。
- `fake_process_diagnostics.py` → `app/demo_data/tool_sources/process_diagnostics.py`；趋势 `fake_source.py` → `app/demo_data/tool_sources/capability_trend.py`。趋势工具继续独立，不并入诊断组。
- 更新定义/装配、默认装配、光刻 Workflow 演示、趋势测试和来源切片等实际消费者；已迁组扫描无旧路径。Fake 所在位置变化不改变生产依赖方向。
- 传感器摘要增加 title/output_schema，Cpk 沿用 030b 的权威 Schema；不改输入或输出计算。新增与现有 Schema 一同在真实处理器结果上校验。
- MOD-003/007/009/024 归属与切片路径更新，光刻切片补两个真实 demo_data 锚点；诊断便携切片为 69 个唯一文件。MOD-024 skill_release 源码 107 → 109，成员 302、tool_sources 108、组合并集 151 不变。均为路径/必需包锚点变化，不重录业务期望。

两平台各 49 项通过，命令：

```text
python -m unittest tests.test_tool_output_schemas tests.test_process_diagnostics tests.test_process_diagnostics_adapters tests.test_process_diagnostics_runtime tests.test_process_diagnostics_portable tests.test_capability_trend_tool tests.test_skill_standard tests.test_litho_cpk_skill tests.test_litho_cpk_portable tests.test_tool_sources_portable
```

WSL repository、两端 module/modularization 边界及 WSL diff 检查通过，298 文件/0 错误；从起点重新导出后四类工具目录字节一致（`c2-catalog-*`）。过程中的切片计数失败来自重复添加包锚点，修正为实际唯一文件清单后通过，无业务行为修复。Playbook 证据规则不改。

## c3：production_reports

- `manufacturing/production_reports/{__init__,binding,contracts,handler}.py` → `app/tools/production_reports/`；SQLite 来源 → `data_source.py`；Fake → `app/demo_data/tool_sources/production_reports.py`。
- 更新生产报表演示、默认/显式装配、定义集合、SQLite 对照测试与所有显式切片。原生处理器与查询原样迁移；新增总览、周良率、制程通过率的 title/output_schema，保留空统计的 NULL 语义。
- 归属/切片清单仅更新路径；生产便携切片因 c1 包锚点净增变为 76 个唯一文件，未重录业务期望。MOD-024 本批成员与 Profile 数量不变。

两平台各 27 项通过，命令：

```text
python -m unittest tests.test_tool_output_schemas tests.test_production_reports tests.test_production_reports_adapters tests.test_production_reports_runtime tests.test_production_reports_portable tests.test_tool_sources_portable
```

WSL repository、两端 module/modularization 边界及 diff 检查通过，298 文件/0 错误。已迁生产组旧路径扫描无残留；重新导出起点，四类目录字节一致（`c3-catalog-*`）。完整报表拆分对照仍留至 030d。

## c4：operational_reports

- `manufacturing/operational_reports/{__init__,binding,contracts,handler}.py` → `app/tools/operational_reports/`；SQLite 来源 → `data_source.py`；Fake → `app/demo_data/tool_sources/operational_reports.py`。
- 更新演示、定义/装配、默认来源、输入/输出与来源测试、所有显式切片及 MOD-003/009/024 和边界路径清单。
- 设备效率、缺陷 Pareto、最近异常补 title/output_schema，沿用既有数值、NULL、排序与限额语义；真实处理器输出由 JSON Schema 校验。运营报表便携切片为 83 个唯一文件，其余制品数量不变。

两端各 21 项通过：

```text
python -m unittest tests.test_tool_output_schemas tests.test_operational_reports tests.test_operational_reports_adapters tests.test_operational_reports_portable tests.test_tool_sources_portable
```

WSL repository、两端 module/modularization 边界及 diff 检查通过，298 文件/0 错误。已迁运营组扫描无旧路径，重新导出起点的四类目录字节一致（`c4-catalog-*`）。含已知 Windows 临时 SQLite 文件占用问题的 runtime 模块留到全量阶段记录，不将本批定向通过表述为该模块全绿。

## c5：named_queries

- `manufacturing/named_queries/{__init__,binding,contracts,handler}.py` → `app/tools/named_queries/`；SQLite 来源 → `data_source.py`；Fake → `app/demo_data/tool_sources/named_queries.py`。
- 更新具名查询演示、定义/装配、默认来源、规划运行测试、收口测试、所有显式切片与 MOD-003/009/024 和边界路径清单；没有保留旧路径转发。
- 八项查询补 title/output_schema，Schema 复用契约的字段集合，保持批次全历史、分页限额、数值与 NULL 语义。Schema 测试另验证所有已声明工具的未知参数、异租户拒绝，拒绝不成为成功数据。
- 具名查询便携切片因包锚点变为 69 个唯一文件；本批制品成员与 Profile 数量不变。清单只改路径/必需锚点与对应计数，不重录业务期望。

两平台各 22 项通过：

```text
python -m unittest tests.test_tool_output_schemas tests.test_named_queries tests.test_named_queries_adapters tests.test_named_queries_runtime tests.test_named_queries_portable tests.test_tool_sources_portable
```

WSL repository、两端 module/modularization 边界及 diff 检查通过，298 文件/0 错误；迁移组扫描无旧路径。重新导出起点的四类目录字节一致（`c5-catalog-*`）。中断前测试已有完整 OK 日志，恢复后补齐检查；未使用中断的全量基线日志作为阶段门结论。

## 后续批次

c6～c7 尚未完成；后续批次继续追加本报告。完整交付物、应用启动、Windows 全量及与起点失败集合对照，留至 030d/030e，不以本批定向结果替代。
