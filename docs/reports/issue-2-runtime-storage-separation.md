# Issue #2 第 4 项：运行状态与历史知识分离

实施基线：`feat/pe-ee-duty-workspace`，源码起点 `0dbbcf6`。范围按用户确认的“完整分离”执行；MOD-025 草稿保留，未实施。本报告不代表任何公司环境已经迁移。

## 目标与结果

历史 SOP/case 不再承载个人上传的文档、分块、全文索引和处理任务。运行状态、个人上传与大结果默认归运行目录，原始文件的 `storage_key` 和实际存放位置不变，避免破坏已有下载与处理引用。

| 所有者 | 直接启动 app 的默认位置 | 隔离启动器位置 |
| --- | --- | --- |
| 历史 SOP/case | `data/departments/process_knowledge.db` | `<instance>/data/departments/process_knowledge.db` |
| 会话、消息、模型目录、执行记录 | `runtime/local/state/ai_operations.db` | `<instance>/state/ai_operations.db` |
| 个人上传元数据、分块、FTS、处理任务 | `runtime/local/state/personal_knowledge.db` | `<instance>/state/personal_knowledge.db` |
| Session 工具结果及引用 | `runtime/local/state/tool_results.db` | `<instance>/state/tool_results.db` |
| 模拟制造、设备、良率数据 | 原有三个部门库 | `<instance>/data/departments/` |

共享 SOP&历史case 上传仍使用既有 `runtime/local/shared_documents/`（元数据和文件），报表目录仍用既有运行配置文件；本项不更改其可见性或模型配置。没有迁移或改写公司电脑上的 Qwen 配置，也没有遍历、重写本机其他运行实例。

`FAB_RUNTIME_DATABASE_DIR` 设置默认运行目录；显式的 `FAB_AGENT_DATABASE_PATH`、`FAB_PERSONAL_DATABASE_PATH`、`FAB_TOOL_RESULT_DATABASE_PATH` 优先。若只指定 agent 文件，个人库和结果库默认与其同目录。历史路径仍由 `FAB_DATABASE_DIR` / `FAB_KNOWLEDGE_DATABASE_PATH` 控制。显式覆盖仍可使用部署指定的其他目录，但各角色不能指向同一个物理文件。

## 实际实现

- `app/persistence/department_schemas.py` 拆出 `PERSONAL_SCHEMA`，版本 17；历史 Schema 不再创建个人表。个人表归 `personal` 别名，读视图名称及公开 API 不变。
- `app/persistence/database.py` 管理三个应用存储角色，拒绝路径冲突、待恢复迁移和未处理的旧混合数据；`initialize(path)` 的显式单文件夹具能力保留。
- `personal_knowledge_runtime` 的上传、任务、重试、编辑、删除、FTS 写入改用个人库。知识 Tool 分别只读挂载历史库或个人库，保留现有 owner / tenant 规则、预算和错误传播，不回退读取旧混合库。
- `run.py`、配置及结果库冲突校验同步更新。`--check` 仍不创建运行数据；新增 `--migrate-storage` 在实例锁内执行维护并退出，不启动服务。普通启动不会静默搬数据或创建替代模型配置。
- 数据管理命令提供显式维护迁移；既有旧单库演示迁移也覆盖新的个人目标库及索引。CI、系统、浏览器夹具改为隔离快照，兼容旧参考集和新的历史/运行分离参考集。
- DB 候选台账只更新实际 SQL 调用及 `knowledge.personal_*` → `personal.personal_*` 的归属，候选数量仍为 37，未放宽边界规则；未更新无关的 DOM/OpenAPI Golden。

## 运维迁移与保留

先停下该来源的所有服务、后台处理器和写入脚本；SQLite 的写锁用于拒绝活跃写者，不等于能够暂停旧版本的全部进程。

```bash
# 默认 dry run，不创建目录、不写源库
python -m scripts.manage_databases separate-runtime \
  --knowledge data/departments/process_knowledge.db \
  --agent data/departments/ai_operations.db \
  --destination runtime/local/state

# 核对来源后，在相同命令后追加 --apply
# 非默认结果文件还须显式传 --results /path/to/tool_results.db
```

未传 `--results` 时，自动纳入原 agent 同目录已存在的 `tool_results.db`；自定义结果路径必须显式指定。迁移不是全机扫描，不自动猜测其他目录中的结果库、凭据或运行实例。

已有启动实例需显式保持原 `FAB_INSTANCE_ROOT`，再运行 `python run.py --migrate-storage`；开发工作树加 `--source-mode worktree`，正式 snapshot 必须包含本项代码。随后用同一实例启动，不能随意切换实例根并将空实例误认为原数据已迁移。

维护步骤：

1. 校验源文件、重复物理路径、目标占用和未完成标记。已有目标拒绝覆盖；同一成功迁移重复执行返回 `already_migrated`，不重放覆盖新运行数据。
2. 为所有来源取得写入保留锁，使用 SQLite backup 创建一致备份于目标父目录的 `storage-backup-<id>/`，保留原始 history / agent / 可选 results。
3. 在独占临时目录准备目标。运行库与结果库原样备份复制，不在迁移中顺带改模型能力字段；个人库按已知 Schema 复制个人记录和 FTS rowid，不带入历史表或未知公司表。
4. 逐表对照个人原始记录及索引内容，执行 `quick_check`、`foreign_key_check`。旧 tags_source 缺失时沿用既有迁移规则推断，原有用户标签保留；没有新增 SHA-256 校验门。
5. 独占发布目标，再在源历史库事务中删除个人表及其 FTS。历史资料和历史 FTS 留在原处；原 agent / results 文件保留但不再是新默认写入目标。记录来源、备份和完成状态的 `storage-separation.json`。

### 失败与恢复界限

历史删除提交前失败：源事务回滚，清理本次发布的目标及待完成标记；保留维护备份用于排查。来源缺失、目标已存在、活跃写锁和记录/完整性不符都会报错，不伪装为成功。

历史删除提交后若完成记录发布失败：保留 `<destination-parent>/.<destination-name>.separating` 与 pending receipt，新版本的连接/初始化拒绝继续运行。三个物理文件与旧历史库无法宣称具有跨文件系统的单事务提交；该状态要求人工维护恢复，不自动清除标记后启动。

恢复时保持停服，核对标记和 receipt 指向同一备份；先用 SQLite backup 保存当前目标及历史库以便审计，再从该次 `history.db` 备份通过 SQLite backup 恢复原历史文件，检查 `quick_check` 和原个人记录。仅在确认维护后没有新写入、原 agent/results 仍保留且恢复正确后，把本次目标目录改名留存并移除该次 pending 标记，重新执行迁移。不能直接复制有 WAL 的主文件或删除仍在使用的目标库。本项测试覆盖中断保留/阻断，没有自动恢复器的验收主张。

## 验证

环境：WSL `.venv-linux` Python 3.11.15；原生 Windows `.venv-win` Python 3.13.5；Linux Node 22.22.2。原始日志和审计摘要放在忽略的 `runtime/quality/issue2-4-*`，不提交数据库、日志或配置副本。

| 项目 | 命令 / 方法 | 实际结果 |
| --- | --- | --- |
| 修改前存储/配置基线 | 两平台 `python -m unittest tests.test_persistence_separation tests.test_settings_env_precedence` | 各 11 项通过 |
| 迁移、存储与相关定向 | WSL：`python -m unittest tests.test_runtime_storage_separation tests.test_persistence_separation tests.test_simulation_profile tests.test_live_e2e tests.test_startup_script tests.test_browser_test_server tests.test_runtime_search_sources tests.test_personal_knowledge tests.test_system_fixture tests.test_settings_env_precedence tests.test_prepare_ci_data tests.test_database_manager` | 113 项通过；随后新布局参考集反例增加 1 项，由下行覆盖 |
| 最后补齐的快照兼容 | 两平台 `python -m unittest tests.test_browser_test_server tests.test_system_fixture tests.test_live_e2e` | 各 37 项通过；包括移走旧 agent 文件后的新布局参考集、只读备份及隔离配置；`test_live_e2e` 是离线脚本契约，不发 Live 请求 |
| Windows 定向 | 上述 12 个定向模块 | 当轮 111 项通过；之后增加的 2 个迁移反例已纳入最终全量，最后增加的新布局参考反例由 37 项补测覆盖 |
| Windows 全量 | 隔离审计器中 `unittest discover`，SQLite backup 与独立子进程、临时上传/日志、禁用外部凭据 | 1549 项，13 失败 / 10 错误 / 3 跳过，358.919 秒；与 `0dbbcf6` 留存的 1539 项审计相比，对应失败、错误、跳过完整 ID 集合完全一致；不是全绿。全量发现后补充的 1 个新布局反例另测，未将其混算入 1549 |
| 浏览器完整回归 | WSL `PLAYWRIGHT_PORT=27991 npm run test:e2e` | 27/27；快照兼容收尾后用 27993 端口复核亦 27/27 |
| Node | WSL `node --test tests/*.test.js` | 65/65 |
| 仓库与边界 | WSL `python scripts/check_repository.py`（包含两个边界检查器） | 通过；受管源码 324、DB 候选 37、边界 errors=0 |
| 静态审阅 | `python -m ruff check --output-format json app tests` 与起点同口径多重集比较 | 430 → 428，无新增诊断；仍有既有问题，不宣称 Ruff 全绿 |
| 仓库外存储交付 | `tests.test_persistence_separation` 的真实制品构建、安装、新 venv 和进程重启 | 两平台通过；历史/agent/个人三存储实际创建，业务表不可访问、导入来自安装目标 |
| 双平台实际启动 | 原生 Windows / WSL 各以临时实例生成 1 天模拟数据，经 `run.py --source-mode worktree` 启动真实 uvicorn，读取 `/api/health` 与指定日期报表 | 两端 health=ok、报表返回实际字段，三个运行库存在、历史库个人表为 0；随后停止本次进程 |

### 首次失败与修正

首轮定向发现交付测试仍期待 2 库、mock 的备份没有产生供新迁移读取的文件，以及检索测试依赖不完整，已修正为实际存储与真实夹具。新增配置逐行对照还发现迁移若调用 agent 旧升级器会补写模型能力字段，已删除该操作并验证模型目录、会话完整记录原样复制。

首次 Windows 全量为 1546 项、17 失败 / 11 错误 / 3 跳过。与基线相比，新增差异是旧的库数量断言、个人路径环境隔离遗漏、Schema 16 的旧预期和 Live 脚本 mock 未覆盖新快照维护。逐项核对后修正，未重录无关 Golden；最终 1549 项的失败集合回到基线。中间 WSL 定向也揭示旧版本预期和配置补写，原始日志保留，没有把最终结果替换为“首次全绿”。

Windows 启动首次因一次性诊断脚本的模块路径缺失未启动；修正后接口检查成功，但诊断脚本仅停止父进程导致清理时文件占用，已停止本次持有端口的子进程，并调整诊断清理为结束本次进程树后复核成功。Linux 启动及清理成功；这些诊断脚本没有进入产品代码。

没有重跑整个 `run_quality_gate.py full`，本次按阶段规则单独执行完整 Python 和浏览器；没有运行性能门、覆盖率或真实模型。远程 CI 未验证，不能由本地结果推断 CI 通过。

本次全部实际数据验证使用临时库、快照和合成内容。正常目录的历史库、模型目录、其他运行实例及公司资料未由测试改写；部署时仍需按上节选择实例执行真实维护迁移。

## 未验证范围

未调用真实模型、公司只读账号、报表接口、LDAP、Live 或生产环境；未运行新的性能门及完整覆盖率。公司数据实际维护、定制路径和自定义外部存储仍需在目标环境验收，不能由本地 SQLite 测试代替。
