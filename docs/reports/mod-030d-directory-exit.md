# MOD-030d：混合职责拆分与旧目录退出

日期：2026-11-11。执行起点 `5239c04`，承接 c1～c7；本批结构与定向验收完成，030e 阶段门单独记录，未推送。

## 1. 实际变更

| 原文件/职责 | 实际归属 | 保持的行为 |
| --- | --- | --- |
| processes.py | `app/core/manufacturing_terms.py` | 纯词表及匹配规则原样迁移 |
| seed.py | `app/demo_data/seed.py` | 合成/初始化命令及参数不变；run.py、API、CI/RAG 脚本同步 |
| enterprise_data.py 的模拟数据与游标 | `app/demo_data/synthetic_fab.py` | 模拟计算、租户、日期和游标语义不变；已有 HMAC 游标实现未重做 |
| enterprise_data.py 的注册/选择 | `app/bootstrap/enterprise_data_assembly.py` | 显式来源选择；配置失败不回退模拟 Provider；只在选择 synthetic 时导入模拟实现 |
| Provider 协议及公开错误 | `app/tools/enterprise_data/provider_contracts.py` | 纯契约与错误身份只有一个实现 |
| 三项企业读取操作 | `app/tools/enterprise_data/operations.py` | 显式 Provider/主体输入；HTTP 与旧工具上下文装配共用，分页 cursor 和过滤未丢弃 |
| reports.py 的九项固定报表 | 四组 Tool 的 `reports.py` | 原 SQL、聚合、日期默认值、过滤、限额、空值和错误语义不变；是实际注册的旧 Tool 读取函数，不是旧目录转发 |
| reports.py 的 report_bundle | `app/api/report_service.py` | 看板直接组合五项已注册固定 Tool 操作，不经过模型，不含 SQL |
| reports.py 的日期函数 | `app/core/report_dates.py` | 默认范围、部分日期、包含结束日和 730 天边界不变 |
| playbooks.py 的通用结构 | `app/planning_runtime/playbook_contracts.py` | 原数据结构，消费者导向实际所有者 |
| playbooks.py 的七套声明 | `app/planning_runtime/builtin_playbooks.py` | 原证据、问题、限制及版本不变；不提前实施 MOD-031 |
| playbooks.py 的选择/提示 | `app/planning_runtime/playbooks.py` | 保留选择、澄清与提示行为 |
| named_playbooks.py | `app/planning_runtime/named_playbooks.py` | 具名映射和证据语义不变，迁移检查器继续使用 |
| 四个旧父包锚点 | 删除 | 无旧目录转发或空包残留 |

企业 HTTP/系统目录读取改用 Tool 的公开读取函数，来源仍由 bootstrap 选择。应用自有状态与系统统计的其他数据库操作不在本批扩展范围。固定报表仍保留既有 db_session 生命周期和兼容门面的真实消费者；没有借迁移宣称整个应用都不再依赖全局存储。MOD-027 保留职责不变。

## 2. 51 文件核销与消费者

030a 起点的 51 文件均已处理：43 个迁移/归位（六组业务工具及来源、Provider 协议、三个知识来源、词表与 seed），四个混合文件按上表拆分，四个父包锚点删除。c7 另迁移知识 Tool 原有四文件，c2 另迁移 030b 新增的趋势 Fake；均不冒充旧 51 文件成员。

应用、脚本、测试、配置字符串、启动命令和交付清单已同步。父包模块别名、动态 getattr、TYPE_CHECKING、独立测试夹具的字面目录均逐项核对，不能只靠整段字符串替换。`app/`、`scripts/`、`tests/`、`evaluations/`、`run.py` 扫描旧路径无残留；历史报告和隔离的起点导出树保留原版本路径。

当前受管应用 303 文件（275 Python + 28 静态）；303 + 4 Skill 资源 = 307 个制品成员。tool_sources 104、skill_release 107、model_transport 5 个源码；源码并集 149，加资源 153。退出四个父包、增加拆分文件与必要资源闭包，是所有清单/固定计数变化的原因，不重录业务答案。

MOD-003 将 Fake/模拟源码归 simulation_fixtures，Tool 保留实际来源唯一归属。原报表/Provider 的两条旧存储/身份债务退出；兼容门面原报表债务改挂两个实际 Tool 目标，词表边归纯 core 后不再是跨层债务。最终 9 条债务、7 个兼容入口、94 条兼容消费；DB 候选 27 → 30，是一个报表文件拆成四个 DB 来源文件，未新增数据访问业务。

## 3. 完整行为对照

每个平台使用相同解释器分别加载 `git archive 5239c04` 导出树和新树；同一临时 SQLite 使用实际制造/设备/质量 Schema，包含开始日、结束日最后时刻及下一日排除行。

对九个报表及看板共 51 个场景完整对象比较，包括默认和显式日期、空窗口、无匹配设备/产品、上下界、limit 裁剪和非法范围错误。不是只比较行数或部分字段。两端结果完全一致。

同时比较七套 DOMAIN_PLAYBOOKS 与七套 NAMED_DOMAIN_PLAYBOOKS 的完整 to_dict 序列化，两端均完全相等。四类默认工具目录也从起点重新导出逐字节比较：TOOLS、原生目录 JSON、知识目录 JSON、实际 register_native 视图均一致，21 项默认业务工具不变。

复现逻辑和机器结果保存在忽略目录 `runtime/quality/mod030cde/`：`mod030_behavior.py` 位于其父目录 quality，结果为 `behavior-{baseline,current}[-wsl].json`；目录结果为 `d-catalog-{baseline,current}.json`。临时脚本未作为运行依赖或新校验平台交付。

## 4. 定向与隔离验证

共同集合两端各 63 项通过：

```text
python -m unittest tests.test_tool_output_schemas tests.test_equipment_health_equivalence tests.test_process_diagnostics_adapters tests.test_production_reports_adapters tests.test_operational_reports_adapters tests.test_enterprise_tools_adapters tests.test_enterprise_provider_boundary tests.test_equipment_health_portable tests.test_process_diagnostics_portable tests.test_production_reports_portable tests.test_operational_reports_portable tests.test_enterprise_tools_portable tests.test_named_queries_portable tests.test_knowledge_search_portable tests.test_tool_sources_portable tests.test_litho_cpk_portable tests.test_skill_releases_portable tests.test_portable_units
```

Windows 另 25 项通过：

```text
python -m unittest tests.test_manufacturing_module_boundaries tests.test_module_release tests.test_domain_playbooks tests.test_default_performance_fixture
```

PIL 相关模块按任务约定在 Windows 运行；指定 WSL venv 的初次 domain_playbooks 导入错误保留记录，不计为通过。WSL 额外使用既有依赖齐全的 Conda Python 3.11.15 执行 `scripts/check_default_tool_migration.py` 通过，Windows 同检查通过；未安装或升级依赖。

两平台 `python -m app.bootstrap.litho_cpk_demo --mode ready|loop [--role viewer]`：分析者每次 5 项 ok、checked、evidence_sufficient=true；viewer 每次 5 项 blocked、来源调用全为 0、evidence_sufficient=false，CLI 按设计退出 2。

WSL `check_repository.py`、两端 `check_module_boundaries.py` / `check_modularization_boundaries.py` 及 `git diff --check` 通过；303 文件、0 边界错误。ruff 与起点同参数核对为 242 → 240，按规则/消息无新增；修复了真实动态引用遗漏，分拆后的脚本导入保留原有初始化顺序，兼容门面显式标明公共导出。

## 5. 退出条件与限制

| 总方案第 6 节条件 | 结论 |
| --- | --- |
| 起点文件逐项处理、唯一所有者 | 51 文件核销，清单检查 0 错误 |
| 实际源码/命令/配置/交付消费者迁完 | 扫描与隔离切片通过；当前文档同步 |
| 程序调用固定 Tool、范围/错误/数据口径可比较 | 51 场景完整对照及既有负向测试通过，不调用模型 |
| Skill/共享 Tool 新环境真实执行 | 两端便携切片通过；组合制品仓库外验收在 030e 另记 |
| 旧发布版本与真实兼容义务 | 不改历史制品；未发现需要保留旧 Python 路径的仓库外消费者 |
| 旧目录与锚点删除 | manufacturing/integrations 及原 knowledge/search_tool 均不存在，无永久转发 |

阶段 Windows 全量及与起点失败集合对照、完整应用启动、组合制品、浏览器/full 门由 030e 报告记录，不能由本报告定向通过推定。真实模型、公司数据、外部宿主和 Live 均未运行。

给 MOD-031：证据声明现位于 builtin_playbooks，结构在 playbook_contracts，选择在 playbooks；Skill 证据四态与原检查器语义未改。没有修改、提交或删除他人维护的 MOD-031 文档。

回退：用既有版本/隔离 checkout 回到 `5239c04` 验证旧实现，或按依赖逆序回退本地批次提交；不重写历史、不混装新旧源码制品。本批不迁移业务数据库或更改数据库 Schema。
