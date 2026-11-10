# MOD-030：Skill 业务交付包与 Tool 标准化

状态：设计草案、待审核，未实施。规范依据核对日期：2026-11-10。

本任务说明可供任何开发者或执行 Agent 独立使用，不依赖原讨论参与者、特定模型或本次聊天记录。正文规定目标、标准和验收；附录记录某次仓库核对的事实与候选映射，不能替代实施前核对。

需求来源：GitHub Issue #1 的工具与流程职责、Tool/Skill 形式统一、业务与接入目录归属三项议题。设计目标：**Skill 作为业务交付包，Tool 作为包内或共享的执行能力。**

当前授权范围为方案评审与文档修订。收到实施授权后，方可修改源码、目录、依赖、工具清单或运行配置并执行验收。证据校验职责另行评审，其结论用于后续 MOD-029 设计；本任务不以全面重构 Validator 为隐含前置条件。

## 1. 排期与范围

工作顺序为：评审本任务标准并确定实施范围；单独确认 Validator 职责；依据这些决定修订 MOD-029。其他工作包保持既有依赖，具体排期以执行计划为准。标准评审通过与开始代码实施分别记录，不依据文档存在自动开始开发。

任务状态、数量和优先级以 [模块化追踪](todos/modularization.md) 与 [执行计划](todos/execution-plan.md) 为准。实施前核对仓库工作树、最新提交、适用 AGENTS.md 与相关消费者；不得将本文件附录的历史数量作为固定验收值。

目标是统一可识别的技能包和工具接口，并让每项业务能力具有唯一归属、明确依赖和可独立验收的交付物。功能、数据口径、有效权限和批准保留的公开契约需要兼容；内部目录、类名和装配方式可以调整。

## 2. 标准依据与适用范围

| 层次 | 采用依据 | 本项目如何使用 |
| --- | --- | --- |
| Skill 可移植格式 | [Agent Skills 规范](https://agentskills.io/specification) | 采用 SKILL.md、YAML 元数据与可选资源目录；完整格式约束以原规范为准 |
| Skill 接入 | [官方接入指南](https://agentskills.io/client-implementation/adding-skills-support) | 元信息发现、按需激活、资源渐进加载；宿主负责信任与执行安排 |
| Tool 公共描述及协议语义 | [MCP Tools 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) | 对齐标准工具字段、调用和结果映射；固定参考版本，不依赖会漂移的 latest |
| 参数与结果结构 | [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12) | 统一机器可读契约，依据实际客户端支持做显式适配 |

区分规范要求、可选约定与本项目扩展。MCP 不规定 Python 类或代码目录；Agent Skills 也不定义本项目的 Tool 注册、生产权限和版本发布体系。对齐格式不代表无需适配就兼容所有 Agent/SDK。

本项先完成标准描述及适配验证，不要求把每个本地 Tool 变成独立 MCP 服务，也不自动部署网络服务或安装第三方技能。

## 3. Skill 标准形式

标准包至少有 SKILL.md，内容为 YAML frontmatter 加 Markdown；name、description 为必需元信息，name 按规范与所在目录一致。可选 scripts、references、assets 分别承载代码、参考资料和资源，其他目录也允许存在；没有内容的目录不创建。[格式依据](https://agentskills.io/specification)

候选交付结构如下；skills/tools 根目录为项目组织示意，非规范强制：

```text
skills/
└── <skill-name>/
    ├── SKILL.md
    ├── references/           # 可选：业务口径、SOP、分析示例
    ├── assets/               # 可选：模板、数据字典等资源
    ├── scripts/              # 可选：确实属于本 Skill 的专用实现
    └── manifest.json         # 项目扩展，按实际执行需要使用

app/tools/                   # 共享业务 Tool，项目约定，不是标准强制路径
└── <shared-capability>/      # 跨场景共享能力只维护一份
```

最小 SKILL.md 示例（示例目录名应为 process-capability-analysis；不是当前已发布包的内容）：

```markdown
---
name: process-capability-analysis
description: 分析指定范围和时间窗口的制程能力；适用于能力异常诊断，不用于生产放行或配方修改。
---

# 制程能力分析

确认范围和口径后，调用可用的具名工具获取证据；说明发现、依据和限制。
详细口径见 references/cpk-context.md。
```

SKILL 正文建议说明适用/不适用场景、必需信息、操作流程、如何解释结果、证据不足时的处理和资源入口。这些章节是本项目写作约定，不是增加一套必需的技能解析字段。

manifest.json 如继续使用，只负责项目执行扩展，例如工具依赖版本、受控入口、发布状态或可选 Workflow 引用。标准 Skill 不能因缺少项目扩展而被误判为格式非法；发现/加载成功与具备本项目生产执行依赖分别报告。同一名称或描述不在 YAML 与 JSON 中独立维护两份，迁移期重复字段必须检查一致性。

allowed-tools 在 Agent Skills 中仍是实验字段，不能作为跨宿主通用授权机制；本项目的真实权限必须在执行端检查。版本和依赖规则属于本项目发布约定，不将它们宣称为技能格式的通用必需项。[字段依据](https://agentskills.io/specification)

## 4. Tool 的标准形式

### 4.1 统一公共描述

公共描述围绕 name、description、inputSchema，以及按需使用的 title、outputSchema、annotations；输入按对象参数建模，输出结构显式声明。描述和 Schema 由一个权威定义源产生，本地调用、模型 Function Calling 和 MCP 导出不能各自手写一套。[协议依据](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)

采用何种 Python 类、装饰器或描述文件是实现选择，不要求保留 ToolDefinition/Binding，也不预建新的通用框架。没有标准要求每个 Tool 必须占一个目录；简单工具允许一个文件完成。

本项目对新业务工具建议采用稳定的小写下划线名称，现有合法名称不为统一外观而批量改名。这是本项目命名约定，不是 MCP 只允许该风格。工具版本、调用主体、执行身份、超时、预算和内部来源元信息由宿主管理，不把所有字段都塞进模型参数，也不将它们冒充协议必需字段。

description 采用统一、简短的业务说明：

| 要素 | 要回答的问题 |
| --- | --- |
| 操作 | 实际读取或计算什么 |
| 选择条件 | 什么问题应调用，哪些问题不适用 |
| 输入 | 范围、时间边界、默认值、单位及必要限制 |
| 输出 | 返回粒度、重要字段、空结果与来源含义 |
| 副作用 | 是否只读，是否需要额外授权 |

Schema 描述字段类型、必需性、枚举和边界；业务口径和复杂步骤放入相应 Skill 资源。不得向模型暴露任意 SQL、凭据或内部连接参数。

### 4.2 结果、错误与跨协议适配

结果映射到 MCP 的 content/structuredContent；协议错误与工具执行错误分别处理，执行失败通过 isError 语义表达。提示类 annotations 不替代权限。项目自己的错误码、来源和重试信息如保留，需标明扩展映射。[结果与错误依据](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)

不强制把所有现有业务返回值改成一种自定义 success/data/error 包装，更不把这种包装称为通用标准。已有 ToolResult 可以作为内部实现，只需明确可验证的对外转换。输入与输出使用一致的 Schema 来源；不支持的结构要明确拒绝或转换，不能静默丢掉约束。

参考的 2026-07-28 版与旧版客户端存在差异，不能用旧版假设覆盖新规范。首期选择本项目真实需要的保守结构，并为目标宿主记录兼容范围；完整 MCP 接入仍需要验证版本、能力及请求/响应，不能只导出几个字段就宣称实现了完整协议。

Tool 正常返回的结构与模型上下文视图也需区分；本项不顺带实现 MOD-029 的裁剪或卸载，不能声明完整输出 Schema 却直接用不匹配的摘要替换它。

## 5. Skill、Tool、Playbook 和目录归属

1. Skill 是业务能力的说明与交付入口；Tool 是实际执行单元。Skill 可包含专用 Tool，也可引用共享 Tool；Tool 仍可供程序或确定性流程直接调用，不要求模型参与。
2. 生产数据读取统一走受控的具名 Tool。连接、固定查询或报表访问可与其归属工具放在一起；实际被多个工具使用的客户端或基础设施只维护一份。凭据留在部署配置，不打进 Skill 包。
3. 共享业务能力不能仅因首次被某个 Skill 使用就归其私有。归属以真实消费者和业务语义决定，避免在多个 Skill 中复制相同实现。
4. Playbook 的说明部分可以成为 Skill 的流程资源；需要确定性的步骤可引用可信 Workflow。简单 Skill 不强制拥有 Playbook、Planner 或证据策略；不能将权限控制仅移动到说明文本。
5. 整治并退出重复承载业务能力的旧目录：专用能力归属其 Skill，共享 Tool 与实际共享的基础设施各自保留唯一实现。对本仓库，退出范围包括 app/manufacturing 与 app/integrations；按实际职责迁移并更新消费者，满足退出条件后删除，不保留永久空壳。附录提供候选映射，不能将混合职责文件整体改名后视为完成。
6. Validator 的必要性、校验层次和启用条件另行评审。本项不直接删除校验，也不要求每个标准 Skill 都具有项目自定义的 evidence_policy 字段。

只读取 SKILL.md 不能触发任意 Python 导入、数据库连接或脚本执行。包含代码的生产技能必须经过可信装配和执行路径；通用格式允许脚本，不等于本项目已经提供任意脚本执行器。

## 6. 迁移与兼容要求

按能力组逐批迁移：先建立唯一的新实现和公开调用方式，再更新直接调用者、bootstrap、Skill 引用、演示、测试、命令和交付清单，验收后移除旧路径。不得先删除两个目录再修所有导入，也不得同时维护两份实现。

退出两个旧目录必须同时满足：

- 对执行起点清单内的全部文件逐项登记保留、拆分、合并、迁移或删除结论；新增/合并后的源码具有唯一所有者，不以某次历史文件总数作为完成证明。
- 源码、配置字符串、脚本命令、当前文档及制品清单不再依赖旧路径；历史报告可以保留当时路径，但不作为现行入口。
- API/看板/任务调用使用受控业务 Tool，业务结果、范围、权限与错误语义通过对照；不需要为了读取数据启动模型。
- Skill 包与共享工具在新环境可实际执行，开发演示按显式配置保留；不能因移动 seed/Fake 代码破坏原生 Windows 或 Linux 启动。
- 旧发布制品保留其版本；是否继续兼容旧 Python 导入按真实外部消费者决定。必要过渡有明确退出条件，不无条件永久保留旧包。
- 无剩余必需消费者或批准的兼容义务后，删除 app/manufacturing、app/integrations 的空目录和包锚点。若仍有阻塞，明确记录，不能把本项的目录退出标为完成。

未获实施授权时不移动或删除目录。获准实施后，允许根据核实的消费者调整目标路径，但必须保留完整映射及验收证据；如果实际兼容义务阻止旧目录退出，应明确登记阻塞，不能隐瞒未完成项。

## 7. 审核通过后的分段

| 分段 | 工作与产物 | 通过条件 |
| --- | --- | --- |
| 030a | 标准映射表、Tool 描述模板、Skill 模板及执行起点清单 | 标明规范、建议与项目扩展；需求方确认范围，获得实施授权前不改造 |
| 030b | 选择一个现有、具有代表性的业务 Skill 试点并引用真实共享工具；确有专用能力时才验证包内实现 | 标准发现/加载、依赖解析、受控执行可验证；试点由实际消费者选择，不指定必须为某个制程或制造新 Tool |
| 030c | 按实际消费者分批迁移业务 Tool 与来源代码 | 输入输出、数据口径、权限和与本任务无关的既有功能兼容；程序调用无需经过模型 |
| 030d | 更新加载/装配与离线交付，按执行起点清单完成旧目录迁移，并满足第 6 节退出条件 | 支持平台的新环境可运行；无重复源码所有者；旧目录不再必需，否则记录未完成及原因 |
| 030e | 回归与验收报告 | 新旧行为对照、负向案例和迁移说明齐备；不将标准识别成功当成完整生产接入 |

执行者根据仓库核对结果定位技能发现/加载/发布、工具描述与执行、应用装配、业务调用者及交付清单等实际入口。附录中的现有路径仅用于定位；不得绕过消费者核对批量移动目录，也不得绑定特定模型或代理分工。

## 8. 验收标准

- 标准最小 Skill 可发现和加载；可选目录不必存在，错误元数据明确报告，读取不会执行脚本。
- 对本项目自有包按引用规范校验 frontmatter；若使用外部 skills-ref 工具，显式准备依赖，不在验收中自动下载。
- 同一描述源生成本地/模型/MCP 适配视图；合法参数结果可按 JSON Schema 验证，非法输入、未知工具与业务失败的语义不混淆。
- 共享工具由至少两个独立消费者复用，只有一个实现；专用实现随技能包交付，授权不足或依赖缺失明确不可执行。
- Skill 不被当前用户/Agent 授权时，即使文本声明工具可用也不能执行；工具内部查询受控，不开放任意 SQL 或连接信息。
- 在项目实际支持的执行模式及程序调用中验证必要路径；旧发布、取消、失败和多 Run 隔离不因迁移损坏，保留原数据口径及其他未授权改变的功能。
- 真实试点连同完整依赖从仓库外交付物在约定目标平台验收（本项目支持 Windows、Linux/WSL）；标准目录、资源链接与文件归属一致，测试只访问隔离数据和配置。
- 跨宿主验证分别记录“格式可识别”“描述/协议兼容”“实际可执行”的证据；未运行外部宿主、真实模型或公司接口时不得宣称已通过。

方案评审阶段仅检查文档；上述要求在实施授权后验证。遵循项目已明确的约束，不新增自建 SHA-256 校验门，不预建无实际消费者的插件市场、多后端平台或兼容层。

## 9. 交付物与任务交接

执行者交付以下可独立审阅的结果：

1. 标准符合性说明：引用规范及版本，区分必需字段、推荐约定和项目扩展；记录不支持的格式或协议能力。
2. 单一来源的 Tool 描述模板、标准 Skill 模板及必要的扩展说明，不要求某种 Python 类或目录生成方式。
3. 迁移决策清单：原职责、实际消费者、新归属、兼容策略、删除条件与对应证据；包含旧目录范围内所有实际文件。
4. 经批准的试点及分批迁移产物；每批给出行为对照和隔离执行证据，不以文件移动数量代替完成。
5. 验证记录：实际命令、环境、通过/失败/跳过、未验证能力，以及受影响的兼容和发布说明。
6. 交接说明：仓库和分支、执行起点提交、保留的既有工作区修改、已完成/未完成范围、后续入口和回退步骤。下一位执行者应能仅凭这些材料继续，不依赖聊天记忆。

需确认的实现选择包括标准扩展边界、共享工具归属、包放置位置和试点范围。具体文件名或类体系允许调整，前提是遵守标准、满足已批准需求，并保留可核对的迁移与验证依据。任务报告不得将仅完成格式、仅完成试点或环境未验证写成全部完成。

## 附录 A：仓库快照与候选迁移映射（非通用规范）

参考快照：8705c79，核对日期 2026-11-10。该快照下 app/manufacturing 有 33 个 Python 文件，app/integrations 有 18 个（包含包锚点），合计 51 个。这些数量和路径用于定位现状，执行者必须重新核对；新增、删除或合并均以实际消费者和批准范围决定，不固定最终文件数。

以下路径只是候选映射，允许提出有依据的调整；目录退出目标与行为验收不能因调整路径而省略。候选结构：

```text
skills/
└── <标准 Skill 名称>/
    ├── SKILL.md
    ├── references/               # 该业务的说明与 Playbook 内容
    ├── assets/                   # 有需要才放声明式配置/模板
    └── scripts/                  # 有真正专用实现才创建

app/
├── tools/                        # 多场景共享的业务 Tool
│   ├── equipment_health/
│   │   ├── tool.py               # 工具定义与业务执行；可按复杂度分文件
│   │   └── data_source.py        # 该能力的固定查询、报表或 Provider 访问
│   ├── process_diagnostics/
│   ├── production_reports/
│   ├── operational_reports/
│   ├── named_queries/
│   ├── enterprise_data/
│   └── knowledge_search/
├── demo_data/                    # 本地演示和模拟来源，不作为生产依赖
└── core/manufacturing_terms.py   # 多模块共用的纯词表/范围定义
```

以上是待审核的项目路径，不是 Agent Skills 或 MCP 对 Python 工程的强制目录。能力组可以包含多个 Tool，不要求一个 Tool 一个目录；简单能力可以使用单文件。框架的通用工具执行器和 Skill 加载器不混进业务包，也不在本项中顺手重命名所有内核目录。

### A.1 当前职责的候选去向

| 原位置 | 计划去向 | 处理要求 |
| --- | --- | --- |
| manufacturing/equipment_health、process_diagnostics、production_reports、operational_reports、named_queries | app/tools 下相应共享能力组 | Tool 定义、业务规则、参数/结果契约共同归属；按实际复杂度合并文件，不复制到每个 Skill |
| manufacturing/enterprise_tools 与 data_contracts.py | app/tools/enterprise_data | 企业数据的具名操作与消费契约放一起，仍可替换来源 |
| integrations/manufacturing/sqlite_equipment_health、sqlite_process_diagnostics、sqlite_production_reports、sqlite_operational_reports、sqlite_named_queries | 对应 app/tools 能力组中的 data_source 实现 | 数据读取成为所属 Tool 的内部实现；确有多个实现时才拆子模块，不保留平行 integrations 树 |
| integrations/manufacturing/provider_enterprise_tools | app/tools/enterprise_data 的来源实现 | 保留 Provider 接缝，不自动接公司系统 |
| integrations/knowledge/backend_search、runtime_search | app/tools/knowledge_search 的来源实现 | 现有 knowledge/search_tool 中的 Tool 定义/处理器一并归位；检索引擎、OCR 与知识存储不整体搬进 Tool |
| 两个 integrations 子目录中的 fake_*.py | app/demo_data/tool_sources | 只用于演示和隔离验收；生产 Tool 不反向依赖 Fake，装配时选择来源 |
| manufacturing/playbooks.py | 对应 Skill 的 references/assets/scripts；必要的通用结构留在技能/规划内核 | 业务说明、声明和受控执行代码分别归属；不是把整个大文件改名放进某个 Skill，具体证据策略结合第 8 条评审确认 |
| manufacturing/named_playbooks.py | 对应 Skill 的具名工具引用；确有旧消费者时保留有期限的兼容映射 | 新业务包使用当前具名能力；旧 SQL 到具名工具的过渡映射不成为永久业务目录 |
| manufacturing/processes.py | 暂定 app/core/manufacturing_terms.py | 仅放被工具、路由、知识元数据共同使用的纯词表，不塞查询、连接或业务执行逻辑 |
| manufacturing/enterprise_data.py 的对外读取操作 | app/tools/enterprise_data | 归并到相应具名 Tool，不再保留绕过工具的另一套生产读取入口 |
| manufacturing/enterprise_data.py 的来源选择/配置装配 | 现有 bootstrap 装配入口 | 不把环境发现、全局注册和业务数据操作继续混在一个大文件中，也不新造无需求的 Provider 平台 |
| manufacturing/enterprise_data.py 的 SyntheticFabProvider 与 seed.py | app/demo_data；显式维护命令仍由 scripts 入口调用 | 保留本地演示/启动所需能力，不搬数据文件，不触发公司库初始化或迁移 |
| manufacturing/reports.py 的既有报表操作与 report_bundle | 对应 app/tools 能力组；看板组合在应用服务/装配层调用 Tool | 更新 API、看板和任务等消费者，程序调用不经过模型；统计口径与原结果对照验收 |
| manufacturing/reports.py 的 safe_select 等遗留 SQL 能力 | 按真实消费者退出，必要兼容仅限批准范围与过渡期 | 不包装成新模型 Tool，不重新开放任意 SQL；旧记录可读与继续执行旧 SQL 分开评估 |
| 两个目录的 __init__.py 与失去消费者的转发 | 消费者迁移完后删除 | 不为保留旧目录名继续加空壳 |

未来新增仅供某个 Skill 使用的 Tool，可放在该 Skill 的 scripts 中；现有跨场景的生产与知识工具优先共享，不因某个 Skill 是首个试点而全部归其私有。实际共享的连接/客户端才提取公共实现，不把整个 integrations 原样改名为 shared。


## 附录 B：同一快照下的差距核对（实施前复核）

| 当前实现 | 拟解决的问题 |
| --- | --- |
| 光刻 SKILL.md 没有 YAML frontmatter，目录为 cpk_diagnostic、项目 ID 为 litho-cpk-diagnostic | 形成标准名称和目录；评估旧 ID/路径的真实消费者，提供明确迁移，不复制两份独立包 |
| 自定义 manifest 严格要求整套字段，包括 workflow/evidence_policy | 支持标准最小 Skill；项目执行扩展按需解释，依赖缺失与格式非法分开 |
| Tool 有输入模型和输出验证函数，未统一机器可读输出 Schema | 补足标准描述及映射，保留有价值的执行校验，避免同一契约多份维护 |
| 业务规则、适配实现、Skill 和默认装配分布在多处 | 给每项能力确定唯一源码 Owner 和交付依赖；共享工具不重复注册或复制 |
| MOD-024 安装器当前只允许 app 路径 | 为标准技能包与真实代码依赖更新明确的安全交付根和成员映射，不为方便搬迁而开放任意路径 |
| 已发布 Skill 有不可变版本与 Run 快照语义 | 新结构以新版本试点，旧发布按实际兼容承诺读取，不直接覆盖原已发布内容 |

格式统一不替代迁移验证。标准技能包可以被其他宿主识别，也不代表其内部生产工具在其他宿主上无需配置即可执行。
