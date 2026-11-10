# MOD-030b：光刻 Cpk 标准 Skill 试点与 Tool 单一描述源

- 状态：本地实施完成，待审核；未推送。030c～e 未实施。
- 执行起点：`87b26bb`（030a 报告提交）。上游方案：[MOD-030 计划](../skill-tool-standardization-plan.md)；起点清单与决定项：[030a 报告](mod-030a-standard-baseline.md)。
- 规范依据：Agent Skills 规范与接入指南、MCP Tools 2026-07-28、JSON Schema Draft 2020-12（核对日期 2026-11-10，条款摘录见 030a 第 1 节）。

## 1. 已确认的决定

030a 第 7 节五项决定由需求方于 2026-11-10 确认：

| 编号 | 决定 | 落实 |
| --- | --- | --- |
| 1 | 删除 `safe_select` | 删除 `app/manufacturing/reports.py:safe_select` 及 `bootstrap/tool_bindings.py`、`agent_runtime/tools/registry.py` 的导出/导入；旧 SQL 工具不重新暴露 |
| 2 | Skill 包放在 `app/` 下 | 光刻包改为 `app/skills/litho-cpk-diagnostic/`，目录名与 `name` 一致；仓库根不新建 `skills/` |
| 3 | 光刻 Cpk 试点并新增共享工具 `get_capability_trend` | 共享实现位于 `app/tools/capability_trend/`，加入光刻计划；默认 21 项模型工具集合不变 |
| 4 | 证据策略四态 | 未声明不注入；已声明必须完整解析并执行；“未配置/解析失败/已检查/证据不足”可区分；基础执行校验不受影响 |
| 5 | `LEGACY_TOOLS` 移出运行包 | 冻结为 `evaluations/legacy_tool_catalog_v1.json`（15 项，与原列表深度相等），由 `scripts/refactor_contracts.py:load_legacy_tools` 读取；`tool_catalog` 不再导出 |

`jsonschema` 加入 `requirements-test.txt`（`>=4.26,<5`），仅用于测试中按 2020-12 校验声明的 Schema，不进入运行依赖。

## 2. Skill 标准形式

| 项 | 规范要求 | 项目扩展 / 实现 |
| --- | --- | --- |
| `SKILL.md` 头部 | `name`、`description` 必需；可选 `license`、`compatibility`、`metadata`、`allowed-tools` | `app/skills/frontmatter.py` 只接受规范所需的 YAML 子集（顶层字符串标量与一层 `metadata` 映射），歧义写法（未加引号的布尔/数字、`: `、制表符、重复键、未知字段）明确拒绝；不新增 YAML 运行依赖 |
| 名称与目录 | `name` 与目录名一致 | `manifest.read_skill_document` 在实际读取边界检查 |
| 最小包 | 只有 `SKILL.md` 即为合法 | `app/skills/standard.py:inspect_skill` 报告 `no_execution_extension`，不导入代码、不授予执行 |
| 执行扩展 | 规范未定义 | `manifest.json` 新增 `schema_version: 2.0.0`：身份与描述取自 `SKILL.md`，manifest 只保留版本、状态、工具依赖、执行模式、可选 workflow/evidence_policy 与资源；1.0.0 格式继续可读 |
| 激活上下文 | 激活加载正文 | 2.0.0 包只把去掉头部的正文作为模型上下文；资源仍按声明渐进加载 |

`allowed-tools` 只解析不授权；实际工具授权仍由应用定义、服务端能力和执行期策略决定。

## 3. 证据策略四态

| 状态 | 触发 | 可观察结果 |
| --- | --- | --- |
| 未配置 `not_configured` | manifest 未声明 `evidence_policy` | 绑定元数据 `evidence_policy_status=not_configured`；`check_evidence` 不调用校验器，`evidence_sufficient=None`，不视为通过 |
| 声明无效 | 声明存在但结构不完整 | 解析报 `invalid_evidence_policy`，装配失败（`SkillAssemblyError.reason`），不访问数据源 |
| 声明不可解析到可信实现 | 版本/标识与可信 Workflow 不匹配 | 依赖错误（`incompatible_dependency`/`missing_dependency`）或 `workflow_unavailable`，装配失败 |
| 已检查 `checked` | 声明有效且校验器执行完成 | 返回校验结果；`evidence_sufficient` 由 `validated` 且结论强度不为 `insufficient`/`hypothesis_only` 决定 |
| 检查失败 `check_failed` | 校验器执行异常 | 与“证据不足”区分，`validation=None`、`evidence_sufficient=None` |

基础执行校验（参数解析、输出校验、范围、预算、权限）仍在 Tool 执行路径上，与证据策略无关。

## 4. Tool 单一描述源与协议视图

- `ToolDefinition` 新增可选 `title`、`output_schema`（创建时校验为对象），描述、输入 Schema 与输出 Schema 只在定义处维护。
- `app/agent_runtime/tools/projection.py` 由定义生成：`model_function_view`（模型函数清单，与原输出逐字节一致）、`mcp_tool_view`（`name/title/description/inputSchema/outputSchema/annotations.readOnlyHint`；数组输出包装为 `{"rows": [...]}` 对象以满足 MCP 对结构化内容的要求）、`mcp_call_result`（成功映射 `content` + `structuredContent`，失败映射 `isError: true` 与公开错误文本，不抛异常）。
- `default_tool_assembly`、`tool_registry.register_native`、`tool_catalog` 均改用 `model_function_view`。对 `a9fa662` 导出的 `TOOLS`、原生/知识目录 JSON 与注册视图逐字节比较：一致。
- `readOnlyHint` 只是提示，不替代授权。未实现 MCP 服务端或传输层，不声称完整 MCP 兼容。

## 5. 新共享工具 `get_capability_trend`

| 项 | 内容 |
| --- | --- |
| 位置 | `app/tools/capability_trend/`：`contracts.py`（输入/输出/范围/Schema）、`tool.py`（定义、处理器、绑定）、`sqlite_source.py`（只读固定参数化查询）、`fake_source.py`（显式夹具） |
| 输入 | `start`、`end`（最长 182 天，默认按当天回溯）、`process_step`、可选 `equipment_id`；未知字段拒绝 |
| 输出 | 每设备每周一行，13 个字段（`week_start`、`period_start/end`、`samples`、`mean_value`、`sigma`、`cpk`、规格限等）；`OUTPUT_SCHEMA` 声明，处理器校验结果与查询范围一致 |
| 范围 | `ToolScope.grain=equipment_week`；异租户、来源异常、范围不一致明确失败，不伪装为空结果 |
| 归属 | `business_tools/manufacturing_capability`；两个来源实现归 `integrations/enterprise_adapters`（`evaluations/mod_003_boundaries_v1.json`） |
| 消费者 | 光刻 Skill 1.1.0 计划；未加入默认 21 项模型工具 |

`get_process_capability` 同步补充 `title` 与 `PROCESS_CAPABILITY_OUTPUT_SCHEMA`，成为第二个声明输出 Schema 的工具。

## 6. 光刻 Skill 1.1.0 与 Workflow 2.1.0

- 包内容：`SKILL.md` 新增头部（`name`、`description`、`metadata.domain/process_step`）并说明周趋势用法；manifest 2.0.0、版本 1.1.0，工具依赖增加 `get_capability_trend ==1.0.0`；`scenarios/acceptance.json` 同步。旧 1.0.0 内容不再随仓库提供，已发布到进程内发布库的旧版本仍按其冻结快照读取。
- `LithoCpkWorkflow` 升级为 2.1.0：在既有具名计划后追加 S05（依赖 S01，`evidence_ids` 为空、非必需），计划 ID 加后缀 `-litho-trend`，预算 +1，单工具上限 2。必需证据 CAP-01～04 及其校验不变。
- 演示 `python -m app.bootstrap.litho_cpk_demo`：ready/loop 均为 5 个工具成功、`evidence_status=checked`、`evidence_sufficient=true`、必需覆盖 3/3；viewer 角色 5 个工具全部 `blocked`、来源调用 0、`evidence_sufficient=false`。

## 7. 交付与冻结契约更新

| 文件 | 更新原因 |
| --- | --- |
| `evaluations/legacy_tool_catalog_v1.json` | 新增：原 `LEGACY_TOOLS` 原样冻结 |
| `evaluations/mod_003_boundaries_v1.json` | 新增 9 个源码归属；`safe_select` 退出记录 |
| `evaluations/mod_007_dispatcher_bundle_v1.json`、`mod_009_tool_sources_v1.json` | 注册视图依赖 `projection.py`，切片 +1 文件 |
| `evaluations/mod_008_default_capabilities_v2.json` | 旧 SQL 能力描述改为“已删除” |
| `evaluations/mod_024_release_v1.json` | Skill 资源新路径；`skill_release` 加入头部解析、投影与趋势工具；`tool_sources` 加入投影 |

MOD-024 制品成员 291 → 300（新增 `projection.py`、`frontmatter.py`、`standard.py` 与 `app/tools` 6 个文件）；`tool_sources` 104 → 105、`skill_release` 100 → 107 个源码。`standard.py` 与 `sqlite_source.py` 有唯一归属但不在任何 Profile 中（当前 Profile 的演示链路不使用）。相关可移植测试的切片数量按此同步。

## 8. 验证

见第 10 节命令清单。结果摘要（2026-11-10）：

| 检查 | 环境 | 结果 |
| --- | --- | --- |
| 新增 `tests.test_skill_standard`（15 项：头部解析、最小包、v2 manifest、证据四态、协议视图）与 `tests.test_capability_trend_tool`（周统计与独立计算对照、只读、异租户、Schema） | Windows / WSL | 通过 |
| Skill、Tool、交付相关 24 个测试模块（含 11 个可移植切片、MOD-024 制品） | WSL | 82 项通过 |
| `tests.test_runtime_convergence_acceptance`、`tests.test_module_release` 等依赖 PIL 的模块 | Windows | 通过（WSL venv 无 PIL，未在 WSL 运行） |
| 模型工具目录（`TOOLS`、原生/知识目录 JSON、注册视图）与 `a9fa662` 逐字节比较 | WSL | 一致 |
| `python -m app.bootstrap.litho_cpk_demo` ready / loop / viewer | Windows | 见第 6 节 |
| `scripts/check_repository.py`、`check_module_boundaries.py`、`check_modularization_boundaries.py`（296 文件，0 错误）、`git diff --check` | WSL | 通过 |
| `scripts/check_default_tool_migration.py` | Windows | 通过 |
| MOD-024 构建 + 仓库外 `verify_module_release.py`（300 成员；44 路工具、Cpk 双路径、发布禁用） | Windows / WSL | 通过；未提供 wheelhouse，`model_transport` 为 NOTRUN |
| ruff 全仓库 | WSL | 242 项，均为既有问题（基线 245，本批减少 3 项 E402，无新增） |
| 全量 `unittest discover` | Windows | 1446 项：12 失败、10 错误、13 跳过；全部失败均在 `a9fa662` 基线导出上同样出现（见下） |

既有失败（与本批无关，在 `a9fa662` 基线导出上以同一 Windows venv 复现）：`test_refactor_contracts` 的 OpenAPI/DOM 两项和 `test_modularization_baseline`/`test_modularization_fixture_clock` 行为基线三项（思考强度功能已改变 API 与页面，冻结契约未更新）；`tests.system.test_sessions_streaming` 7 项（测试替身不接受 `thinking_effort` 参数）；`tests.system.test_data_reports` 4 项（依赖本地 `data/` 合成数据及 WSL 路径判断）；`test_context_resolver`、`test_version_contract` 各 1 项；`test_agent_assembly` 演示、`test_operational_reports_runtime` 2 项、`test_personal_job_sse` 1 项为 Windows 下 SQLite 临时文件被占用无法删除。

## 9. 给 MOD-031 的交接

按 Validator 职责方案初稿（`docs/validator-responsibility-plan.md`，另一执行者维护，未随本提交入库）第 6.2 节要求说明：

- **Playbook 职责**：本批未迁移或删除 Playbook 规则。光刻 Workflow 仍调用 `select_named_playbook`/`create_named_execution_plan`，PB-CAPABILITY-001 的证据定义（CAP-01～04）原样保留；趋势步骤是 Workflow 追加的非必需步骤，不进入证据清单。`manufacturing/playbooks.py` 与 `named_playbooks.py` 的拆分留给 030c/030d。
- **扩展缺省与依赖错误**：见第 3 节；缺省不注入、不判通过，显式声明错误在装配阶段失败，不静默降级。
- **现有诊断路径**：Skill 路径通过 `SkillBinding.check_evidence` 调用 `LithoCpkWorkflow.evidence_validator`（仍为 `validate_skill_evidence`）；默认非 Skill 路径未改。没有新增兼容适配。
- **策略所有者与版本**：策略标识 `capability-evidence@1.3.0` 由可信 Workflow 固定，manifest 只能引用；随包发布的仅为声明文本，发布库的资源固定与回退机制未改变。
- **来源映射**：工具结果的 `sources/scope/row_count` 未改；MCP 视图只增加结构化映射，不丢弃范围信息。
- **留给 MOD-031**：“证据不足”与“结论强度”的语义统一、无策略 Skill 的回答约束、`check_failed` 是否需要对用户可见的提示、以及默认路径是否采用同一四态。

## 10. 命令与环境

- Windows：`.venv-win\Scripts\python.exe`（Python 3.13.5），已安装 `jsonschema 4.26.0`。
- WSL Ubuntu 24.04：`fab-insight-agent-refactor-v2-platform/.venv/bin/python`（Python 3.11.15，`jsonschema 4.26.0`，无 PIL）。

```text
python -m unittest tests.test_skill_standard tests.test_capability_trend_tool ...
python -m unittest discover -s tests -t .
python -m app.bootstrap.litho_cpk_demo --mode ready|loop [--role viewer]
python scripts/check_repository.py
python scripts/check_default_tool_migration.py
python scripts/build_module_release.py --output <临时目录> --build-id mod030b-check
python -I <临时目录>/verify_module_release.py --delivery <临时目录> --work-dir <全新目录> --report <报告.json>
git diff --check
```

## 11. 未完成与限制

- 030c～e 未开始：`app/manufacturing`、`app/integrations` 仍在，`get_process_capability` 等既有工具未迁入 `app/tools/`。
- 只在离线 Fake/临时 SQLite 上验证；未运行真实模型、公司接口、外部 Agent 宿主或 `skills-ref`。
- 未实现 MCP 服务端；`mcp_tool_view`/`mcp_call_result` 只验证了结构与 JSON Schema。
