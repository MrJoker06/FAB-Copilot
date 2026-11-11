# MOD-030e：迁移阶段验收

日期：2026-11-11。分支：`experiment/parallel-platform`。执行起点 `5239c04`，应用源码验收基线为 `0829d8c`（030d）；本阶段只修正测试夹具、历史参考元数据和文档，没有继续修改应用行为。

## 1. 结论与适用范围

MOD-030a～e 的标准化、业务 Tool 迁移和旧目录退出已完成。本次按用户明确允许既有失败的阶段方案收尾：双平台定向回归、行为对照、仓库外交付和实际启动通过，Linux 浏览器 17/17 通过；Windows 全量存在可在起点复现的失败，**full 质量门未通过**。不能将本报告解读为全仓库测试全绿、覆盖率达标或公司生产接入完成。

Windows 全量本轮为 1449 项、13 失败、10 错误、3 跳过；起点同环境为 1446 项、12 失败、10 错误、4 跳过。额外出现的一项代理环境测试在固定种子的起点/当前配对中同样失败；无尚未在起点复现的新失败。原始差异和修复前失败全部保留，没有更新行为 Golden、放宽阈值或重试后删除失败记录。

受管应用源码为 303 文件（275 Python、28 静态），依赖债务 9、兼容入口 7、静态消费记录 94、DB 候选文件 30。旧 `app/manufacturing`、`app/integrations` 和 `app/knowledge/search_tool` 目录均已删除；没有永久旧路径转发层。迁移细节见 [030c](mod-030c-tool-migration.md) 与 [030d](mod-030d-directory-exit.md)。

## 2. 环境与证据

| 环境 | 实际用途与限制 |
| --- | --- |
| 原生 Windows，`.venv-win/Scripts/python.exe`，Python 3.13.5 | 全量与定向 unittest、PIL、jsonschema、交付和启动；没有 coverage |
| WSL Ubuntu-24.04，`/mnt/d/modern_agents/agents/fab-insight-agent-refactor-v2-platform/.venv/bin/python`，Python 3.11.15 | 约定的单元/切片测试、jsonschema、ruff、边界检查和构建；没有 PIL |
| WSL，`/home/zackzhang/miniconda3/envs/fab-insight-agent/bin/python`，Python 3.11.15 | 已有完整运行依赖、PIL 和 coverage，用于真实应用、浏览器夹具、默认工具检查及 full 门；没有 jsonschema |
| Node | Windows 22.17.1；WSL 22.22.2，浏览器使用已有 Linux Chromium 1234 |

Git 全程通过 WSL，身份未改：`MrJoker06 <416373110@qq.com>`。离线运行使用隔离实例、模拟 Provider 和本地夹具；未调用真实模型或公司接口，未安装或升级依赖。

原始日志、基线导出、机器报告和临时制品位于被忽略的 `runtime/quality/mod030cde/`，不随提交交付。下文给出可复核命令和持久结论；本地证据文件名用于定位当次运行，不保证在另一台机器存在。

## 3. 逐项验收

### 3.1 每批定向、描述与拒绝路径

c1～c7 的两端定向及隔离切片结果逐批记录在 030c 报告。030d 公共集合两端各 63 项通过，Windows 额外 25 项通过，命令与模块清单见 030d 第 4 节；依赖 PIL 的额外集合没有在缺 PIL 的指定 WSL venv 中冒充通过。

每批都重新导出 `5239c04`，分别运行同一目录采集脚本，比较 `TOOLS`、`_NATIVE_CATALOG_JSON`、`_KNOWLEDGE_CATALOG_JSON` 和 Registry `model_tools`：c1～c7 及 d 全部逐字节一致。仍为默认 21 项具名业务工具加 `submit_analysis`；没有恢复 SQL Tool。证据为各批 `*-catalog-baseline.json` / `*-catalog-current.json`。

新增输出 Schema 用 jsonschema 校验实际处理器结果，覆盖拒绝输入、空结果及跨租户等场景；原有权限、范围与预算仍在实际执行路径生效。`python scripts/check_default_tool_migration.py` 在 Windows 与既有 WSL Conda 环境均通过。

### 3.2 报表和 Playbook 完整行为对照

使用相同临时 SQLite 数据库，在起点导出树与当前树的独立进程运行 9 个固定报表函数及看板组合，共 51 个完整结果场景；覆盖默认/部分/明确日期、日末和次日边界、空结果、筛选、未知实体、限额及非法日期错误。Windows 和 WSL 均完整对象相等，非仅比较行数或 HTTP 状态。7 个领域与 7 个命名 Playbook 的完整声明也分别相等。

本地复核入口为 `runtime/quality/mod030_behavior.py` 的 `fixture`、`baseline`、`current` 三步，结果为 `behavior-{baseline,current}.json` 与对应 `-wsl.json`。脚本只作独立比较，不重录冻结期望值。

### 3.3 光刻实际命令

两平台分别运行以下四种组合（共 8 次）：

```bash
python -m app.bootstrap.litho_cpk_demo --mode ready
python -m app.bootstrap.litho_cpk_demo --mode loop
python -m app.bootstrap.litho_cpk_demo --mode ready --role viewer
python -m app.bootstrap.litho_cpk_demo --mode loop --role viewer
```

分析者均 5 个工具成功、`evidence_status=checked`、`evidence_sufficient=true`；viewer 均 5 个 blocked、来源调用全为 0、证据不足，按设计退出码 2。独立结果为 `demo-<平台>-<模式>-<角色>.json`。

### 3.4 MOD-024 制品仓库外实跑

Windows 与 WSL 各执行一次，使用对应平台解释器和全新仓库外目录：

```bash
python scripts/build_module_release.py --output <临时交付目录> --build-id mod030-check
python -I <临时交付目录>/verify_module_release.py --delivery <临时交付目录> --work-dir <全新仓库外目录> --report <结果.json>
```

两端构建、验收退出码均为 0；`tool_sources+skill_release` 均 PASS：44 个工具案例、2 个 Cpk 模式、Skill 禁用验证成功、guard_events=0。隔离导入来自交付物，不依赖源码工作树。共 5 个唯一所有者 ZIP、307 个源码/资源成员；tool_sources 104 源码，skill_release 107 源码加 4 资源，model_transport 5 源码，三者并集 149 源码/153 成员。

未提供 wheelhouse，因此本次 `model_transport` 明确为 NOTRUN，不沿用历史 PASS 代替本次验证。命令和报告为 `delivery-commands.json`、`release-win-acceptance.json`、`release-wsl-acceptance.json`。

### 3.5 两平台实际启动

Windows 使用 `run.bat --source-mode worktree --seed-days 1 --port <空闲端口>`；WSL 使用 `bash run.sh` 的相同参数。显式指定各平台 `FAB_PYTHON` 和临时 `FAB_INSTANCE_ROOT`，禁用项目/工作区配置读取并清空模型密钥，使用模拟 Provider。

两端首页 HTTP 200（25460 字节）、`/api/health` 状态 ok，分别约 18.12 秒和 16.27 秒完成验证，随后仅停止本次应用进程。Windows `CTRL_BREAK` 关闭；WSL 以独立进程组关闭。没有将 health 成功当作真实模型可用。证据为 `startup-results.json`（Windows）及 `startup-results-r2.json`（WSL）。

WSL 首次启动采集器因 `setsid` 父进程提前返回而误判，日志保留为 `startup-wsl-r1.log`；改用 `setsid --wait` 后观察到实际服务，应用源码未修改。

## 4. Windows 全量与基线差异

基线用 `git archive 5239c04` 导出到全新目录，按任务方案复制本地 `data/departments` 供系统测试使用；与当前树使用同一 Windows venv、相同 UTF-8 设置：

```text
PYTHONUTF8=1 .venv-win/Scripts/python.exe -m unittest discover -s tests -t .
```

上式的环境变量在 Windows 通过进程环境设置，不是要求 cmd 接受 POSIX 赋值语法。

| 运行 | 项数 | failures / errors / skipped | 测试耗时 |
| --- | ---: | --- | ---: |
| 起点 5239c04 | 1446 | 12 / 10 / 4 | 330.843 秒 |
| 当前首轮 | 1449 | 20 / 12 / 3 | 保留原日志，不作为最终结果 |
| 当前修复夹具后 | 1449 | 13 / 10 / 3 | 332.172 秒 |

最终 22 条失败/错误标题与起点全量一致，涉及冻结 OpenAPI/DOM、Thinking 测试替身、冻结行为/时钟、宿主代理、系统数据、版本契约及 Windows SQLite 文件占用等方案列出的既有类别。额外一项为 `tests.test_modularization_baseline.ModularizationBaselineTests.test_fixture_proxy_environment_is_hidden_and_restored`：Windows 环境变量名不区分大小写，而测试按 frozenset 顺序写入不同大小写的代理哨兵值，受 Python hash seed 影响。

为区分偶发既有失败与回归，按同一 venv、同一测试、相同 `PYTHONHASHSEED` 配对：seed 0 起点/当前均通过，预定 seed 1、2、3 起点/当前均以相同哨兵差异失败。未改代理测试或应用行为；原始全量集合确实为 22 对 23，不能写成两次全量完全一致。配对证据证明额外失败在起点存在，归于方案已列的代理环境类别，无未复现的新失败。

证据：`full-baseline-win.log`、`full-current-win-r1.log`、`full-current-win.log`、`full-failure-comparison-r1.json`、`full-failure-comparison.json`、`proxy-seed-matrix.json` 及 8 份配对日志。计划曾写 13 跳过，本次实测为 4/3，以上表为准。

## 5. 本阶段修正与冻结参考例外

首轮新增机械失败分别修正如下，没有改变业务数据、工具输入或结果：

- `tests/test_startup_script.py`：路径组件形式的旧 seed 夹具同步到 demo_data，覆盖 snapshot/worktree 与导出过滤。
- `tests/test_dispatcher_bundle_install.py`：负向导入控制改为阻断整个 `app.api`，避免隔离包先因缺父包而抛 ModuleNotFoundError；拒绝检查没有被删除。
- `tests/test_modularization_boundaries.py`：同步领域依赖期望，允许原样 Playbook 声明使用已迁入 orchestration 的共同结构，未拓宽权限或运行时授权。
- `evaluations/mod_002_reference_v4.json` 与 `scripts/build_modularization_reference.py`：恢复为 **5239c04 原字节**。此前机械改名把历史 v4 ZIP 的成员标识改成当前目录，造成元数据与未变更的批准 ZIP 不匹配。恢复其历史身份，不重建 ZIP、不刷新 Golden，也不增加内容哈希门。

最后一项是明确的扫描例外：这两个**冻结历史参考文件**继续含旧 namespace；它们记录/构建历史参考，不是当前应用或当前交付清单的导入依赖。若重建 v4，必须使用对应历史审查基线，不能拿当前拆分源码生成同名历史制品。当前运行源码、测试消费者、可移植/组合交付清单无旧目录依赖。030d 当时的字面扫描结论须结合本节后续恢复修正理解，不能据此宣称整个仓库所有文本均无旧字符串。

修正后 Windows 定向 77 项通过：

```bash
python -m unittest tests.test_startup_script tests.test_dispatcher_bundle_install tests.test_modularization_boundaries tests.test_modularization_reference tests.test_modularization_paired_runner
```

Windows 设置 `PYTHONUTF8=1`；未设置时测试临时 Git Unicode 文件名的 GBK 解码曾导致夹具误判，诊断保留，不修改应用启动器来规避。

## 6. 浏览器与完整质量门

跨模块阶段结束触发浏览器与 full 门，已实际尝试：

| 命令/平台 | 实际结果 |
| --- | --- |
| Windows `npm.cmd run test:e2e -- --reporter=line` | 缺 Windows Playwright 命令 shim，未运行测试 |
| Windows `node node_modules/@playwright/test/cli.js test --reporter=line` | 应用夹具启动，但缺 Windows Chromium 1234；17 项均在浏览器启动前失败，未验证页面断言 |
| WSL 同一 Playwright JS CLI，使用既有 Node/Conda/Chromium | **17/17 通过，52.3 秒**；未更新截图，Live specs 仍按配置排除 |
| Windows `python scripts/run_quality_gate.py full` | 发现 1449 项后在 `coverage erase` 因缺 coverage 退出 1 |
| WSL Conda `python scripts/run_quality_gate.py full` | 首段 1333 项，7 失败、4 错误、2 跳过，285.495 秒，退出 1 |

WSL full 的 7 失败来自既有 Thinking 上下文、OpenAPI/DOM、冻结行为/时钟、代理及上传版本契约。4 个导入错误为该 Conda 环境缺 jsonschema，涉及 `test_capability_trend_tool`、`test_equipment_health_tool`、`test_skill_standard`、`test_tool_output_schemas`；相关测试在有 jsonschema 的指定单元环境通过，但不能因此将此轮 full 写为通过。

full 按设计提前停止，后续系统段、合并覆盖率门、Node/RAG/OCR/Playbook/性能等步骤没有完整执行；没有本次有效完整覆盖率百分比。Linux 独立浏览器成功与 full 失败分别记录。未安装依赖、删测试、放宽阈值或自动访问 Live 来获得绿色结果。日志为 `e2e-win.log`、`e2e-win-direct.log`、`e2e-wsl.log`、`full-quality-win.log`、`full-quality-wsl.log`。

最终在指定 WSL 单元环境执行 `python scripts/check_repository.py`、`python scripts/check_module_boundaries.py`、`python scripts/check_modularization_boundaries.py` 和 `git diff --check`，全部退出 0，303 文件、0 边界错误。`python -m ruff check app scripts tests --output-format json` 与起点按规则/消息计数比较，242 → 240 项，无新增问题；ruff 本身因既有问题退出 1，不能写成 lint 全绿。15 份收尾文本 UTF-8/LF/单一末尾换行及 146 个相对文档链接检查通过。

## 7. 迁移影响、交接与提交

业务能力在 `app/tools/<能力组>/`，Fake、模拟 Provider 和 seed 在 `app/demo_data/`；来源选择在 bootstrap。旧 Python 内部路径退出，需要更新本仓库消费者，不提供永久转发；当前唯一归属的交付包必须按同一版本组合，不能混装新旧包。固定报表仍通过实际注册的 Tool 函数复用原存储生命周期；API 与遗留兼容装配尚不能宣称全部独立，剩余债务继续由 MOD-027 等既有任务承担。

给 MOD-031：原样规则在 `app/planning_runtime/builtin_playbooks.py`，通用结构在 `playbook_contracts.py`，选择/提示在 `playbooks.py`，具名映射在 `named_playbooks.py`。7+7 声明对照一致，未修改证据规则语义或他人维护的 `docs/validator-responsibility-plan.md`。

本轮本地提交：c1 `f238cab`、c2 `1a9bcc3`、c3 `75a06ab`、c4 `fcfdeaf`、c5 `69db86e`、c6 `7343495`、c7 `fb2da8d`、d `0829d8c`；e 为包含本报告的提交。全程不推送、不改 Git 身份。e 提交后删除被忽略的临时交接方案，保留本报告和台账作为长期结论。

回退使用独立 checkout 返回 `5239c04` 或按依赖逆序回退本轮提交，不重写现有历史；本任务无数据库 Schema/业务数据迁移。真实模型、公司接口、生产 ACL/SSO、远程 runner、Live、本次 model_transport 和 Windows 浏览器断言均未验证。既有失败与环境补齐不在本次迁移中扩大修复；无需用户新增业务决定即可完成本轮本地交付。
