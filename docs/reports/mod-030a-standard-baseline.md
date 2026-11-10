# MOD-030a：标准映射、模板与执行起点清单

状态：030a 交付物，待需求方审核。本文不修改源码、目录、依赖、工具清单或运行配置；030b 起的改造需另行授权。

- 执行起点：`experiment/parallel-platform` 本地提交 `a9fa662`（父 `8705c79`），核对日期 2026-11-10。
- 上游方案：[MOD-030 计划](../skill-tool-standardization-plan.md)。本文只落实其第 7 节 030a 行，不改变方案的标准与验收要求。
- 机器扫描结果（消费者明细）保存在被忽略的 `runtime/quality/mod030a_consumers.json`，可按附录 C 的方法重新生成；本文结论以下列表格为准。

## 1. 规范核对结果

2026-11-10 实际读取了以下页面，记录与本项目相关的条款。“级别”区分规范强制（MUST/必需）、规范建议（SHOULD/推荐）与本项目扩展。

### 1.1 Agent Skills

来源：[规范](https://agentskills.io/specification)、[接入指南](https://agentskills.io/client-implementation/adding-skills-support)。

| 条款 | 级别 | 本项目采用方式 |
| --- | --- | --- |
| Skill 是目录，至少含 `SKILL.md` | 必需 | 采用 |
| `SKILL.md` = YAML frontmatter + Markdown 正文 | 必需 | 采用；正文格式不限 |
| `name`：1–64 字符，仅 `a-z0-9-`，不以 `-` 开头或结尾，无 `--`，与父目录名一致 | 必需 | 采用；现有 `cpk_diagnostic` 目录名含下划线，不合规 |
| `description`：1–1024 字符，说明做什么、何时使用 | 必需 | 采用；写作要素见第 3 节 |
| `license`、`compatibility`（≤500 字符）、`metadata`（字符串到字符串的映射） | 可选 | `compatibility` 仅在有环境要求时写；版本等项目信息可放 `metadata`，但项目执行依赖仍由 `manifest.json` 承担 |
| `allowed-tools` | 可选，实验字段 | 不用于授权；真实权限在执行端检查 |
| `scripts/`、`references/`、`assets/` 及其他目录 | 推荐约定 | 有内容才创建 |
| 渐进加载：元信息 → 正文（建议 <5000 token、<500 行）→ 资源按需 | 推荐 | 现有 Catalog/Loader 已分层加载，保留 |
| 资源以 Skill 根为基准的相对路径引用，引用深度一层 | 推荐 | 采用 |
| `skills-ref validate` 校验 frontmatter | 推荐工具 | 验收若使用须显式准备依赖，不自动下载 |
| 扫描 `.agents/skills/`、项目级优先、同名冲突确定性处理、项目级技能需信任判断 | 接入指南建议 | 本项目技能随应用制品交付，不扫描用户目录；冲突与信任规则在 030b 设计时确认 |

### 1.2 MCP Tools（2026-07-28）

来源：[Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)、[Schema 参考](https://modelcontextprotocol.io/specification/2026-07-28/schema)。

| 条款 | 级别 | 本项目映射 |
| --- | --- | --- |
| Tool 字段 `name`、`description`、`inputSchema`；可选 `title`、`icons`、`outputSchema`、`annotations` | `inputSchema` 必须为非 null 的 JSON Schema 对象 | 现有 `ToolDefinition` 有 name/description/输入 Schema；缺 title、outputSchema、annotations |
| 无 `$schema` 时按 JSON Schema 2020-12 解释 | 规范默认 | 现有输入 Schema 未声明 `$schema`，按 2020-12 解释，需在 030b 用 2020-12 校验器确认 |
| 无参数工具推荐 `{"type":"object","additionalProperties":false}` | 推荐 | 现有 `_schema({})` 已满足 |
| 名称 1–128 字符，`A-Za-z0-9_-.`，区分大小写，服务内唯一 | SHOULD | 现有 21 个名称全部满足；不为外观批量改名 |
| `annotations`：`readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`、`title`；客户端须视为不可信 | 可选提示 | `ToolDefinition.read_only` 可映射为 `readOnlyHint`；提示不替代权限 |
| 结果 `content[]`（text/image/audio/resource_link/resource） | 协议结构 | 由项目 `ToolResult` 转换生成 |
| `structuredContent` 可为任意 JSON 值；有 `outputSchema` 时服务端 MUST 符合，客户端 SHOULD 校验；为兼容 SHOULD 同时给出 TextContent | MUST/SHOULD | 现有只有 Python 输出校验函数，无机器可读输出 Schema |
| 协议错误（未知工具、请求结构错误、服务器错误）走 JSON-RPC error；执行错误（API 失败、输入校验、业务规则）走 `isError: true` | 规范分类 | 见第 2.3 节映射；注意规范把“输入取值校验失败”归为执行错误 |
| 状态句柄：不透明、每次校验授权、声明生命周期、过期返回执行错误 | 非规范指引 | 供 MOD-029 结果引用设计参考，本项不实现 |
| `tools/list` 可按请求授权返回不同集合，SHOULD 顺序确定 | MUST/SHOULD | 与现有“按 Run 授权暴露工具”一致；导出视图须保持确定顺序 |
| 请求须带 `_meta` 协议版本等字段、`resultType`、`InputRequiredResult`、`x-mcp-header` | 完整协议要求 | 本项首期不实现 MCP 服务端，只做描述与结果映射；不得据此宣称已实现完整 MCP |

### 1.3 JSON Schema Draft 2020-12

来源：[2020-12](https://json-schema.org/draft/2020-12)。输入、输出 Schema 都按 2020-12 解释。模型 Function Calling 端的实际支持范围（如 `oneOf`、`$ref`、`format`）因提供方而异，导出时只使用目标客户端已验证支持的关键字；不支持的约束须在执行端校验，不能只靠 Schema 表达。

## 2. 现状差距与映射

### 2.1 Skill

| 项目 | 现状（`a9fa662`） | 差距 | 030b 处理方向 |
| --- | --- | --- | --- |
| 目录名 | `app/skills/lithography/cpk_diagnostic` | 含下划线，不能作为合规 `name` | 新版本使用合规目录，如 `litho-cpk-diagnostic`，与现有 `skill_id` 一致 |
| `SKILL.md` | 无 frontmatter，只有正文 | 缺必需的 `name`、`description` | 补 frontmatter；正文按第 3 节模板 |
| `manifest.json` | `app/skills/manifest.py` 要求 13 个字段全部存在且不得多余，含 `workflow`、`evidence_policy` | 标准最小 Skill 会被判为格式非法；`title`/`description` 与 SKILL.md 重复维护 | 解析分两步：先按标准解析 SKILL.md；`manifest.json` 只承担项目执行扩展，字段按需，缺失时报告“不可执行”而非“格式非法”；重复字段检查一致 |
| 发现/加载 | `catalog.py`、`discovery.py`、`loader.py` 已只读元信息、按声明加载资源、不执行脚本 | 发现依赖 manifest 的 `process_steps` 等扩展字段 | 保留只读与资源预算；标准元信息与扩展筛选条件分开报告 |
| 授权 | `DiscoveryResult` 与 `SkillSnapshot` 的 `execution_authorized` 恒为 False，执行依赖显式装配 | 无 | 保留；不引入 `allowed-tools` 授权 |
| 发布 | `releases.py` 不可变版本与 Run 快照 | 无 | 新结构以新版本发布，旧版本按原快照读取 |
| 交付 | `scripts/module_release.py` 只接受 `app/` 成员，Skill 资源根硬编码为 `app/skills/lithography/cpk_diagnostic` | 新目录或仓库根 `skills/` 无法入包 | 030d 改为从清单读取 Skill 根，不开放任意路径 |

旧 ID/路径的真实消费者：`skill_id` `litho-cpk-diagnostic` 出现在 6 个测试、`scripts/verify_module_release.py`、`app/bootstrap/litho_cpk_demo.py`；目录路径出现在 `scripts/module_release.py`、`scripts/verify_module_release.py`、`evaluations/mod_024_release_v1.json`、`tests/test_litho_cpk_portable.py` 与两份当前文档。`skill_id` 保持不变即可避免改动前一组消费者。

### 2.2 Tool 描述

| 项目 | 现状 | 差距 | 处理方向 |
| --- | --- | --- | --- |
| 定义源 | `app/agent_runtime/tools/definition.py` 的 `ToolDefinition`：name、version、description、input_model（含 `json_schema()`）、output_validator、read_only | 无 title、outputSchema、annotations | 在同一定义上补可选字段，不新建平行描述文件 |
| 默认工具集合 | `app/bootstrap/tool_definitions.py` 汇总 21 个定义（12 个报表/企业数据、`search_knowledge`、8 个具名查询），导入时检查唯一 | 无 | 保留为唯一汇总点 |
| 模型视图投影 | `tool_catalog._native_projection` 与 `default_tool_assembly._NATIVE_CATALOG_JSON` 各写了一遍同样的投影 | 两处手写投影 | 收敛为一个投影函数，模型/MCP 视图都从它派生 |
| 手写旧 Schema | `tool_catalog.LEGACY_TOOLS`（14 项，含任意 SQL 的 `query_manufacturing_data`） | 与定义源平行维护 | 仅剩 `scripts/refactor_contracts.py`、`scripts/modularization_baseline.py`、`tests/test_agent_preparation_boundaries.py` 作为冻结基线使用；保留为基线夹具，不再进入运行视图，退出由 030c 与基线负责人确认 |
| 输出契约 | 每组 `contracts.py` 中的 `validate_*_output` Python 函数 | 无机器可读 Schema；与未来 outputSchema 有双份维护风险 | 030b 试点工具补 outputSchema，并用同一 Schema 在测试中校验真实输出；Python 校验函数保留到能由 Schema 覆盖为止 |
| 描述文本 | 中文短句，含范围与行数上限 | 未统一“选择条件/不适用/输出含义/副作用” | 按第 4 节模板逐个补写，不改名称 |

### 2.3 结果与错误映射（建议，030b 验证）

| 项目内部 | MCP 视图 |
| --- | --- |
| 未知工具名、参数不是对象、调用结构非法 | JSON-RPC 协议错误（如 `-32602`） |
| `ToolErrorKind.PARSING` / `VALIDATION`（参数值越界、日期格式错） | `isError: true`，文本给出可改正的信息 |
| 数据源失败、超时、业务规则拒绝 | `isError: true`；`retryable`、错误码作为项目扩展放 `_meta`，不冒充协议字段 |
| 权限不足 | `isError: true` 或按装配直接不暴露该工具；不泄露内部连接信息 |
| 成功 `ToolResult.data` | `structuredContent` = data；同时给出序列化 JSON 的 TextContent |
| `ToolResult.sources` | 项目扩展，放 `_meta` 或 `resource_link`，030b 选择其一并记录 |

## 3. 标准 Skill 模板

```markdown
---
name: <与目录名一致，小写字母、数字和单个连字符>
description: <做什么>；适用于<场景>；不用于<排除场景>。
metadata:
  fab-agent-version: "<语义化版本>"
---

# <业务名称>

## 适用与不适用
## 必需信息
<范围、时间窗口、对象标识；缺失时如何追问>

## 操作流程
<按步骤说明调用哪些具名工具及其用途>

## 结果解释
<关键指标含义、阈值依据，详见 references/...>

## 证据不足时
<如何说明缺口，不得编造或给出自动生产变更>

## 资源
- references/<口径或 SOP>.md
```

`manifest.json`（项目扩展，可选；缺失时 Skill 可被发现和加载，但报告“无项目执行依赖、不可受控执行”）：

```json
{
  "schema_version": "2.0.0",
  "version": "<语义化版本>",
  "status": "draft | published",
  "tools": [{"name": "<工具名>", "version": "<版本约束>"}],
  "execution_modes": ["ready", "loop"],
  "workflow": {"component_id": "<可选>", "version": "<版本>"},
  "resources": [{"path": "references/<文件>", "kind": "reference"}]
}
```

规则：`name`、`description` 只在 SKILL.md 维护；迁移期 manifest 若仍保留 `skill_id`/`description`，加载时必须与 frontmatter 一致，否则报错。`evidence_policy`、`process_steps`、`required_inputs` 等改为可选扩展，是否保留由 030b 与 Validator 评审决定。字段集合与 `schema_version` 值为建议，030b 实现时确认。

## 4. Tool 描述模板

一个工具只在定义处写一次，以下为逻辑字段（Python 写法由实现决定）：

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `name` | 是 | 稳定名称；新工具用小写下划线，现有名称不改 |
| `title` | 否 | 中文显示名 |
| `description` | 是 | 按下表五要素，建议 1–3 句 |
| `inputSchema` | 是 | JSON Schema 2020-12 对象；`additionalProperties: false`；字段写类型、必需、枚举、范围、默认值和单位 |
| `outputSchema` | 试点起 | 与真实返回一致；返回结构未覆盖前不声明 |
| `annotations` | 否 | `readOnlyHint` 由 `read_only` 派生；不作为授权依据 |
| 版本、超时、预算、调用主体 | 宿主管理 | 不放入模型参数，不冒充协议字段 |

description 五要素示例（基于现有 `get_process_capability`，仅为写法示例，实际文本在 030b 审定）：

> 读取指定制程站点在时间窗口内的规格范围、Cpk 和样本数（只读）。用于判断制程能力是否异常；不用于设备故障根因或良率归因。输入：`process_step` 可选，`start`/`end` 为 YYYY-MM-DD，默认最近 90 天。输出：按参数汇总的 Cpk 行，空结果表示窗口内无量测而非能力正常。

## 5. 执行起点清单（51 个文件）

以下逐文件给出决定。“去向”沿用上游方案附录 A 的候选路径，030c/030d 可按消费者核对结果调整，但须更新本表。“应用消费者”只列 `app/` 内直接导入者；测试、脚本、`evaluations/` 清单的引用见第 6 节。

结论代码：迁移（整体换位置）、拆分（按职责分到多处）、合并（并入同能力组其他文件）、删除（消费者迁完后移除）。

### 5.1 `app/manufacturing`（33 个）

| 文件 | 行数 | 职责 | 应用消费者 | 结论与去向 |
| --- | ---: | --- | --- | --- |
| `__init__.py` | 1 | 包锚点 | 无 | 删除 |
| `equipment_health/__init__.py` | 1 | 包锚点 | 无 | 迁移为 `app/tools/equipment_health/__init__.py` |
| `equipment_health/binding.py` | 65 | 定义与绑定 | bootstrap 7 处 | 迁移，可与 handler 合并为 `tool.py` |
| `equipment_health/contracts.py` | 230 | 输入/端口/输出契约 | bootstrap 3 处 | 迁移 |
| `equipment_health/handler.py` | 96 | 纯处理器 | 包内 | 合并入 `tool.py` |
| `equipment_health/summary.py` | 83 | 可选聚合工具 | `tool_sources.py` | 迁移，留在同能力组 |
| `process_diagnostics/__init__.py` | 1 | 包锚点 | 无 | 迁移 |
| `process_diagnostics/binding.py` | 97 | 定义与绑定 | bootstrap 5 处 | 迁移，可与 handler 合并 |
| `process_diagnostics/contracts.py` | 381 | 契约 | bootstrap 3 处 | 迁移 |
| `process_diagnostics/handler.py` | 96 | 纯处理器 | 包内 | 合并 |
| `production_reports/__init__.py` | 1 | 包锚点 | 无 | 迁移 |
| `production_reports/binding.py` | 105 | 定义与绑定 | bootstrap 4 处 | 迁移，可与 handler 合并 |
| `production_reports/contracts.py` | 409 | 契约 | bootstrap 2 处 | 迁移 |
| `production_reports/handler.py` | 141 | 纯处理器 | 包内 | 合并 |
| `operational_reports/__init__.py` | 1 | 包锚点 | 无 | 迁移 |
| `operational_reports/binding.py` | 139 | 定义与绑定 | bootstrap 5 处 | 迁移，可与 handler 合并 |
| `operational_reports/contracts.py` | 490 | 契约 | bootstrap 3 处 | 迁移 |
| `operational_reports/handler.py` | 177 | 纯处理器 | 包内 | 合并 |
| `named_queries/__init__.py` | 44 | 包导出 | 无 | 迁移 |
| `named_queries/binding.py` | 87 | 8 个具名查询定义 | bootstrap 4 处 | 迁移，可与 handler 合并 |
| `named_queries/contracts.py` | 608 | 契约 | bootstrap 2 处 | 迁移 |
| `named_queries/handler.py` | 141 | 纯处理器 | 包内 | 合并 |
| `enterprise_tools/__init__.py` | 13 | 包导出 | 无 | 迁移为 `app/tools/enterprise_data/__init__.py` |
| `enterprise_tools/binding.py` | 94 | 定义与绑定 | bootstrap 4 处 | 迁移，可与 handler 合并 |
| `enterprise_tools/contracts.py` | 873 | 契约 | bootstrap 4 处 | 迁移 |
| `enterprise_tools/handler.py` | 199 | 纯处理器 | 包内 | 合并 |
| `data_contracts.py` | 33 | 企业数据 Provider 协议 | 仅旧目录内 2 处 | 合并入 `app/tools/enterprise_data` |
| `enterprise_data.py` | 510 | 混合：`SyntheticFabProvider`（约 360 行）、Provider 注册与选择、三个对外读取函数 | `api/runtime_dependencies.py`、`bootstrap/default_tool_assembly.py`、`bootstrap/tool_bindings.py` | 拆分：模拟 Provider → `app/demo_data`；注册/选择 → bootstrap 装配；读取函数 → `app/tools/enterprise_data`，随旧注册退出 |
| `reports.py` | 356 | 混合：日期范围工具、9 个旧报表函数、`report_bundle`（看板）、`safe_select`（任意 SELECT） | `agent_runtime/compatibility.py`、`api/runtime_dependencies.py`、`bootstrap/tool_bindings.py` | 拆分：报表口径并入对应 `app/tools` 能力组并与原结果对照；看板改为在应用服务层调用 Tool；`safe_select` 按第 7 节单独决定 |
| `playbooks.py` | 677 | 混合：通用结构（`EvidenceRequirement`、`DomainPlaybook` 等）、7 个领域 Playbook 声明、选择与提示拼装 | `agent_runtime` 4 处、`planning_runtime` 4 处、`bootstrap` 2 处 | 拆分：通用结构与选择留在规划内核；各 Playbook 的说明部分转为对应 Skill 的 `references/`；具体证据策略待 Validator 评审 |
| `named_playbooks.py` | 123 | 具名查询版 Playbook 选择 | `default_coordinator_assembly.py`、`litho_cpk_workflow.py`、`planning_runtime/named_planner.py` | 拆分：随 Skill 迁移；`scripts/check_default_tool_migration.py` 是否仍需旧映射在 030c 确认 |
| `processes.py` | 61 | 制程站点与分析范围词表 | 15 个应用文件（api、intent、knowledge、personal_knowledge、planning、bootstrap） | 迁移为 `app/core/manufacturing_terms.py`，内容不变 |
| `seed.py` | 742 | 模拟数据库生成与维护命令 | `api/runtime_dependencies.py`；`run.py`、`scripts/prepare_ci_data.py`、`scripts/evaluate_rag.py` | 迁移到 `app/demo_data`；`run.py` 与两个脚本同步更新，保持 Windows/Linux 启动 |

### 5.2 `app/integrations`（18 个）

| 文件 | 行数 | 职责 | 应用消费者 | 结论与去向 |
| --- | ---: | --- | --- | --- |
| `__init__.py` | 1 | 包锚点 | 无 | 删除 |
| `manufacturing/__init__.py` | 1 | 包锚点 | 无 | 删除 |
| `knowledge/__init__.py` | 1 | 包锚点 | 无 | 删除 |
| `manufacturing/sqlite_equipment_health.py` | 161 | 只读 SQLite 来源 | bootstrap 6 处；`scripts/demo_equipment_health.py` | 迁移为 `app/tools/equipment_health/data_source.py` |
| `manufacturing/sqlite_process_diagnostics.py` | 203 | 只读 SQLite 来源 | bootstrap 3 处 | 迁移到 `process_diagnostics/data_source.py` |
| `manufacturing/sqlite_production_reports.py` | 160 | 只读 SQLite 来源 | bootstrap 3 处 | 迁移到 `production_reports/data_source.py` |
| `manufacturing/sqlite_operational_reports.py` | 231 | 只读 SQLite 来源 | bootstrap 3 处 | 迁移到 `operational_reports/data_source.py` |
| `manufacturing/sqlite_named_queries.py` | 229 | 只读 SQLite 来源 | bootstrap 3 处 | 迁移到 `named_queries/data_source.py` |
| `manufacturing/provider_enterprise_tools.py` | 103 | 旧 Provider 协议适配 | `default_tool_assembly.py`、`enterprise_tools_demo.py` | 迁移到 `enterprise_data/data_source.py`，保留 Provider 接缝 |
| `knowledge/backend_search.py` | 186 | 工厂/个人知识检索适配 | `knowledge_search_demo.py`；`runtime_search.py` | 迁移到 `app/tools/knowledge_search/`，同时把 `app/knowledge/search_tool/` 的定义与处理器归位；检索引擎、OCR、知识存储不搬 |
| `knowledge/runtime_search.py` | 221 | 默认装配用的延迟检索来源 | `default_tool_assembly.py` | 同上 |
| `manufacturing/fake_equipment_health.py` | 71 | 测试/演示夹具 | `dispatcher_demo.py`、`tool_sources_demo.py`；脚本 1 个 | 迁移到 `app/demo_data/tool_sources/` |
| `manufacturing/fake_process_diagnostics.py` | 51 | 夹具 | 2 个 demo | 同上 |
| `manufacturing/fake_production_reports.py` | 57 | 夹具 | 1 个 demo | 同上 |
| `manufacturing/fake_operational_reports.py` | 51 | 夹具 | 2 个 demo | 同上 |
| `manufacturing/fake_named_queries.py` | 49 | 夹具 | 1 个 demo | 同上 |
| `manufacturing/fake_enterprise_tools.py` | 50 | 夹具 | 1 个 demo | 同上 |
| `knowledge/fake_search.py` | 72 | 夹具 | 2 个 demo | 同上 |

合计 51 个文件：删除 4（包锚点）、拆分 4（`enterprise_data.py`、`reports.py`、`playbooks.py`、`named_playbooks.py`）、迁移或合并 43。后者中 8 个进入 `app/demo_data`（7 个 Fake 与 `seed.py`），7 个合并到同组文件（6 个 handler 与 `data_contracts.py`）。最终文件数随合并方式变化，不作为验收值。

## 6. 非应用代码消费者（迁移必须同步）

| 类别 | 文件 | 引用方式 |
| --- | --- | --- |
| 启动与脚本 | `run.py`；`scripts/prepare_ci_data.py`、`scripts/evaluate_rag.py`、`scripts/demo_equipment_health.py`、`scripts/mod_008_default_performance.py`、`scripts/evaluate_playbooks.py`、`scripts/evaluate_ready_execution.py`、`scripts/evaluate_trace_replay.py`、`scripts/check_default_tool_migration.py` | 导入或模块路径字符串 |
| 交付与边界 | `scripts/module_release.py`、`scripts/verify_module_release.py`、`scripts/build_portable_unit.py`、`scripts/build_modularization_reference.py`、`scripts/modularization_baseline.py`、`scripts/check_modularization_boundaries.py` | 路径清单、硬编码 Skill 根、`app/` 前缀限制 |
| 冻结清单 | `evaluations/mod_001_portable_baseline_v1.json`、`mod_002_reference_v4.json`、`mod_003_boundaries_v1.json`、`mod_005_equipment_health_source_v1.json`、`mod_007_dispatcher_bundle_v1.json`、`mod_009_tool_sources_v1.json`、`mod_024_release_v1.json`、`module_boundaries_v1.json`、`portable_units_v1.json` | 文件路径；属于冻结契约，更新须单独说明原因并独立审阅 |
| 测试 | 75 个受跟踪测试模块包含旧模块名或旧路径（`git ls-files tests` 中的 `.py` 按 `app.manufacturing`/`app.integrations` 及对应路径搜索） | 导入、patch 目标与路径断言 |
| 当前文档 | `docs/current-project-structure.md`、`docs/architecture-modularization-master-plan.md`、`docs/module-portability.md` 等 | 现行入口说明；`docs/reports/` 为历史记录不改 |

## 7. 需要审核决定的事项

1. **`safe_select` / `query_manufacturing_data`**：运行视图已不暴露任意 SQL 工具（模型工具由 21 个定义生成），但 `reports.safe_select` 仍被 `bootstrap/tool_bindings.py` 导出、`agent_runtime/tools/registry.py` 导入，`LEGACY_TOOLS` 基线也保留该 Schema。建议：030c 删除运行代码中的 `safe_select` 导出；基线夹具是否保留由冻结契约负责人决定。
2. **Skill 包放置位置**：仓库根 `skills/` 还是 `app/skills/<name>/`。放根目录需要同时改 `module_release.py` 的成员规则；放 `app/` 下对交付改动最小。建议试点先放 `app/skills/litho-cpk-diagnostic/`，Skill 加载器内核（`app/skills/*.py`）不动。
3. **试点范围**：建议 030b 以光刻 Cpk 为试点（唯一已发布 Skill，引用 4 个共享工具：`get_process_capability`、`get_recent_excursions`、`get_sensor_summary`、`search_knowledge`），无需新造工具；`get_process_capability` 作为首个补 outputSchema 与 MCP 视图的工具。
4. **manifest 字段**：`evidence_policy`、`process_steps`、`required_inputs` 改为可选，需与 Validator 评审结论一起确认。
5. **`LEGACY_TOOLS`** 退出运行模块：迁到测试/基线夹具位置还是保留在 `tool_catalog.py`。

## 8. 验证记录

- 规范：2026-11-10 读取 Agent Skills 规范与接入指南、MCP 2026-07-28 Tools 页与 Schema 中的 ToolAnnotations，条款摘录见第 1 节。
- 清单：WSL `python3` 用 AST 解析全部受跟踪 `.py` 的导入（含相对导入），并在受跟踪 `.py` 字符串常量、`json/toml/yaml/sh/ps1/bat` 和非报告 Markdown 中按模块名与路径搜索；`app/manufacturing` 33 个、`app/integrations` 18 个，共 51 个，与上游方案附录 A 一致。
- 未做：未运行应用测试（纯文档）；未用 2020-12 校验器验证现有输入 Schema；未运行 `skills-ref`；字符串搜索可能漏掉运行时拼接的模块名，030c 迁移时需以测试与导入检查兜底。

## 附录 C：重新生成扫描结果

扫描脚本未入库。复现方法：对 `git ls-files` 中的 `.py` 用 `ast` 收集 `Import`/`ImportFrom`（相对导入按包路径展开）与字符串常量，对目标模块名（如 `app.manufacturing.reports`）和路径（如 `app/manufacturing/reports.py`）做匹配；非 Python 文本只做字符串匹配。输出每个文件的应用、旧目录内部、脚本、`evaluations`、测试消费者和文档引用。
