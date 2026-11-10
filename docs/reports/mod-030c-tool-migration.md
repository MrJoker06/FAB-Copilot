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

## 后续批次

c2～c7 尚未完成；后续批次继续追加本报告。完整交付物、应用启动、Windows 全量及与起点失败集合对照，留至 030d/030e，不以本批定向结果替代。
