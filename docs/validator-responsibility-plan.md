# MOD-031：验证职责与业务证据策略改造确定版

版本：v1.0；日期：2026-11-11。状态：**已按本版实施并完成基线对照验收；保留既有失败/full 门未通过；本版纳入 MOD-031 提交，远程状态以 Git 为准。** 实施起点 638f772，结果及必要附加字段见 [实施报告](reports/mod-031-validator.md)。本版替代 v0.1；下文基线表及附录保留定稿时事实，不当作当前结构快照。

源码核对基线：`1651242`；GitHub 默认分支为 `experiment/parallel-platform`，本次文档工作区为 `feat/local-qwen3-runbook`，两者在基线时同指该提交。MOD-030 已完成，迁移结果及未通过的完整质量门见 [030e 报告](reports/mod-030e-acceptance.md)。实施前重新核对分支、工作树和后续提交，不能把本文候选路径当成已经存在的代码。

## 1. 已确定的设计决定

1. 保留必要验证，拆开工具执行契约、业务证据检查、编排决策、答案支持检查与展示。保留通用 evidence 内核，移出其中的制造业务字段、阈值和按工具名分支，不再建设新的全局 Validator 平台。
2. Tool 保证它执行的操作、输入、权限、范围和结果契约；Skill/可信业务流程定义“这项分析需要什么证据、允许作出什么判断”。单个 Tool 成功不代表整个诊断通过。
3. `workflow` 与 `evidence_policy` 在标准/v2 Skill 中继续独立可选；MOD-030 已实现的能力不重复开发。受控生产诊断所要求的策略由宿主可信装配强制绑定，删除清单字段不能绕过。
4. 业务检查产生事实性报告，不自行调用 Tool、模型、数据库或修改 LoopGuard；编排根据报告和现有预算决定继续收集、询问或受限总结。
5. “可以停止取数”与“证据足以支持诊断”分别表达。存在冲突可以结束无意义的取数，但不得将冲突包装成通过；检查失败也必须允许返回故障说明，而不能无限循环。
6. 默认 Ready、默认 Loop、显式 Skill Ready/Loop、离线降级采用同一个结果语义；模型文本、`submit_analysis` 和流式返回均不能绕过服务端的最终约束。
7. 只新增确定性判断，不新增模型裁判、规则 DSL、动态脚本加载器、插件市场、通用工作流引擎或数据库查询能力。量化小模型只接收结论边界和缺口，不编写 SQL 或判断自身是否合格。
8. 第一批完整切片沿用现有光刻 Cpk；默认其他六类诊断也必须接入通用报告与决定，不因“试点通过”就遗漏默认应用。七类原始规则保持单一来源，按真实共用关系抽取。

以上是本方案的实施选择，不是 Agent Skills 或 MCP 强制规定。设计确定不等于实现完成、用户已经批准执行或生产环境已验收。

## 2. 真实起点与初稿修正

| 当前事实（1651242） | 本项处理 |
| --- | --- |
| v2 `SkillManifest` 已允许 workflow/policy 缺省，v1 仍要求两者；标准最小包可读取 | 保持版本语义；不把“改成可选”再次列为待开发 |
| `SkillBinding.check_evidence` 返回 not_configured / checked / check_failed，显式非法策略在装配失败 | 统一进入实际应用链，并补足原因与异常结果校验；不是重新做一套四态 |
| 当前受控装配只有光刻 Workflow；缺 workflow 报 no_workflow | 保持受控执行器的明确范围；最小 Skill 可发现/加载不等于已有通用 Skill 执行器，本项不暗中增加后者 |
| 默认 Ready 与 Loop 通过依赖回调直接调用 `validate_evidence(plan, playbook, observations)` | 改由可信装配固定策略并调用统一评估入口，不再由通用引擎解析 Playbook 类型或业务工具名称 |
| Loop 必需证据全部 covered 即 enter_synthesis | 由编排的收集决定解释覆盖、缺口及可补充性；结论许可仍由评估报告约束 |
| 旧 `validated` 仅表示运行了检查；`SkillEvidenceOutcome` 以“不在不足集合”推导 sufficient | 改为显式允许值，未知强度、非法返回和 checked-but-not-applicable 不能被误判为通过 |
| 字段覆盖使用任意行存在某字段；样本小于 30、字段列表与规格冲突规则放在全局 validator | 等价抽取后，按版本推进到明确逐行规则；30 只保留为已有规则，不解释为普适统计标准 |
| answer_contract 是否 required 目前与 validated 绑定；多种展示模式及逐声明支持逻辑已经存在 | 保留已有效的逐声明判断，拆开适用性与模板选择，不重写整个答案综合器 |
| 7 个领域声明在 builtin_playbooks，具名规则由 named_playbooks 提供；030d 仅迁移位置 | 本项处理规则所有权和消费者，不声称 MOD-030 已消灭 Playbook 或完成证据语义重构 |
| 手写 LEGACY_TOOLS 已冻结到 evaluations；safe_select 已删除 | 不再实施一次“退出”，不恢复任意 SQL；只保留历史测试必需的读取 |

基线代码中的自然语言 acceptance_criteria 不等于已经有对应的可执行规则。正式来源、规格生效性和样本统计充分性只能按真实可用数据判断，不能从文案推断已经得到证明。

## 3. 标准与职责边界

继续使用 [MOD-030 标准依据](skill-tool-standardization-plan.md#2-标准依据与适用范围)。本次复核 [Agent Skills 规范](https://agentskills.io/specification) 与 [MCP Tools 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)，不升级协议版本。

Agent Skills 的必要文件是带元数据的 SKILL.md，scripts/references/assets 是可选资源约定；manifest、evidence_policy、结论强度及受控发布是项目扩展。MCP 的 Schema 描述输入/输出结构，不提供制造诊断成立、权限有效或自然语言正确的保证。本项不改变 MCP 视图，也不把本地描述投影称为完整 MCP 服务。

| 边界 | 必须负责 | 明确不负责 |
| --- | --- | --- |
| Tool / Dispatcher 的真实执行边界 | 原有参数、权限、范围、预算、超时、错误及结果契约；拒绝场景仍拒绝 | 跨工具诊断、根因成立、报告章节 |
| 业务策略 | 需要哪些证据、字段完整性、范围/口径可比较性、样本和来源限制、可支持结论 | 直接查库、发起工具、改变权限、强制重试 |
| 通用 evidence 内核 | 按已解析策略评估实际观测；引用关联、规则结果和纯结果序列化 | 以技能名/工具名选择业务，加载 Skill、发现数据源、写全局阈值 |
| Runtime 编排 | 现有生命周期、预算内继续/停止收集、澄清与总结；处理取消和异常 | 用“已停止”代替“业务合格”，用策略绕过执行拒绝 |
| 答案处理 | 真实引用、直接事实与推断支持、结论限制、结构化输出协议及故障披露 | 证明任意自然语言为真，替代 Tool 授权 |
| 展示 | 既有简短/表格/报告等模式和必要说明 | 以缺少某标题判定数据或诊断错误 |

output_schema 的运行时检查继续按现有实际执行契约承担；本项不夹带“给所有工具增加通用 JSON Schema 执行器”的工程。某个诊断需要逐行完整，不表示所有工具所有输出都要重复全量扫描。

## 4. 规则所有权与目标结构

### 4.1 唯一归属

- 单个工具的字段类型、范围及固有计算约束保留在该 Tool 的 contracts/handler/data_source。
- 专属于某 Skill 的证据要求与焦点匹配归该 Skill 的业务实现和资源；读取 SKILL.md 不执行这些实现。
- 默认能力诊断和光刻共用的能力规则，以及七类既有诊断真正共用的规则，保留一个共享业务实现。确定首期放在 `app/skills/policies/`；这是可信 Python 业务库，不是第二套 Skill Catalog，也不是额外标准技能包，不为它伪造 SKILL.md。
- `app/evidence/` 只保留通用契约、纯评估、语义和答案支持逻辑。共享业务规则的版本/引用在现有可信装配中固定，不新增自动发现或 Registry 平台。

共享策略库是必要的：默认非 Skill 诊断与光刻 Skill 都是真实消费者，不能让 CMP/ETCH 的能力诊断依赖“光刻私有规则”，也不能在全局 Validator 和 Skill 各写一份阈值。未来某规则只有一个 Skill 使用时，可以归入该包，无需维持公共层。

### 4.2 目标目录示意

```text
app/
├── tools/<能力组>/                # 执行契约、数据来源；本项不重迁目录
├── skills/
│   ├── contracts.py、manifest.py…  # 已有格式、依赖、加载和发布
│   ├── policies/                  # 现有业务的共享规则，无自动发现
│   │   ├── manufacturing.py       # 七类原始策略声明的唯一来源
│   │   └── capability.py          # 默认能力/光刻共用检查与版本配置
│   └── litho-cpk-diagnostic/
│       ├── SKILL.md
│       ├── manifest.json          # 引用精确策略版本
│       └── references/…           # 说明已发布规则，不另抄阈值
├── evidence/
│   ├── contracts.py               # 纯策略输入、评估结果；复用可用旧类型
│   ├── validator.py               # 纯评估入口；无制造工具名称分派
│   ├── semantics.py               # 通用可比较性/支持关系
│   └── answer_synthesizer.py      # 引用和声明支持、必要受限输出
├── planning_runtime/
│   ├── playbook_contracts.py      # 规划消费者仍可保留 Playbook 结构
│   └── builtin_playbooks.py…      # 规划/说明视图；证据规则来自同一声明
├── agent_runtime/…                # 收集决定及 Ready/Loop 消费
└── bootstrap/…                    # 固定策略、版本、宿主要求与可信实现
```

这是实施目标，不是完成快照。不要求每项拆成独立文件：相邻的小契约可合并；禁止为凑层次增加无人使用的 Coordinator、Port 或转发模块。现有 `app/evidence/skill_policy.py` 的知识焦点匹配迁到业务策略实现，真实消费者直接改用新实现，无消费者后删除。

### 4.3 Playbook 的确切处理

1. 七类 evidence_requirements 的权威声明移入共享业务策略库；原 evidence_id、必需性及版本映射逐项保留，不重编编号。
2. Planner 仍实际消费的步骤、问答说明和选择结构可以保留。`DomainPlaybook.evidence_requirements` 在有真实规划/外部响应消费者期间，只是由权威声明构造的视图，不再手写第二份规则。
3. 通用 Validator 改收已固定的策略与必要运行事实，不因 Plan 非 ready 或 Playbook 为 None 就自动把“必须检查的诊断”降级为不适用。
4. 默认七类诊断与 Skill 按能力显式绑定，未知能力拒绝隐式认领；不能用某目录名或技能名在评估器中分派。
5. 不为本项创建七个空 Skill，也不删除仍有消费者的所有 Playbook。保留的视图逐个记录消费者和后续退出条件，兼容退出衔接 MOD-027；不能把本项叫作“Playbook 全部退役”。

## 5. 策略绑定与不可绕过要求

### 5.1 缺省、非法与必需的处理

| 情形 | 确定行为 |
| --- | --- |
| 标准最小 Skill，没有 workflow/policy | 可发现与加载；仅作说明/上下文时不要求诊断策略；受控 Workflow 执行器仍可明确返回 no_workflow |
| v2 有 Workflow，无 policy；宿主不要求专项检查 | 可进入已授权的执行能力，报告 not_configured，不能显示“验证通过” |
| v2 声明 policy，但无 Workflow | 格式可以合法、依赖照常解析；说明读取不执行策略，没有受控执行绑定时不冒充可运行诊断 |
| 显式 policy 格式错、找不到版本或不可信 | 装配失败；报告具体依赖/配置原因，业务来源调用为 0，不降级成 not_configured |
| 宿主把该受控诊断标为必须检查，但清单省略/删除 policy | 激活失败，理由 required_policy_missing；业务来源调用为 0 |
| 策略引用与宿主允许的精确版本不符 | 激活失败，理由 required_policy_mismatch；不自动改绑 latest |
| 用户删掉 Skill 引用，仍请求默认生产诊断 | 默认诊断的宿主绑定要求继续有效；不能靠改变入口规避 |

宿主要求以现有可信 Workflow/能力绑定上的可选精确策略引用表达；不是又一套按技能名配置的全局 allowlist。现有生产诊断绑定所需策略，独立查询 Tool 和说明型 Skill 不被强制变成诊断流程。v1 manifest 的已有格式保持，不将本轮放宽 retroactively 应用于旧版。

### 5.2 版本与发布

先等价抽取当前规则，保持当前策略版本结果；再将更严格的逐行判断、统一适用性等行为作为新策略版本上线。光刻现有 `capability-evidence@1.3.0` 不原地改语义，新规则采用 `2.0.0`；引用它的 Skill/Workflow 同步按实际兼容性升版。

旧已发布引用如仍有真实消费者，必须能解析到其旧规则配置和实现；只保留被引用版本，复用共同评估代码，不复制整套执行链。不能只固定 manifest 文本却把所有版本指向当前最新 callable。旧版本的读取与回退也受当前宿主允许版本约束；被撤销版本明确不可激活，不静默换版或关闭检查。

本项不增加持久发布库：沿用当前进程内发布机制，跨进程重新装配所需源码、资源和版本表随同一批交付物提供。发布/禁用、资源固定、取消和失败后的状态隔离均继续验收。

## 6. 统一评估结果与语义

### 6.1 状态不是合格判定

四种生命周期结果固定如下；第四类配置错误通常在 Run 前结束，不要求每次运行伪造一个 invalid 报告。

| 结果 | 含义 | evidence_sufficient |
| --- | --- | --- |
| not_configured | 无可选策略，且宿主允许这样运行 | null |
| invalid（装配错误） | 声明或必需依赖不合法/不满足，未进入业务执行 | null |
| checked | 已配置策略完成评估并返回合法报告，适用性仍须单独判断 | 仅按下述正向条件判断 |
| check_failed | 评估异常、错误返回类型/字段或不支持的结果版本 | null |

`checked` 时：有必需证据、全部 covered、无阻断性冲突/风险、结论强度为 `supported` 或 `supported_with_limits` 才为 true；证据不足/不满足时为 false。有策略但当前没有适用必需证据时为 null，另报 not_applicable 原因；宿主要求必需诊断却得到这种结果，按 check_failed（policy_not_applicable）处理。不得用“不是 insufficient/hypothesis_only 就算 true”这样的黑名单判断。

结论强度沿用 `not_applicable / insufficient / hypothesis_only / supported_with_limits / supported`，不引入新评分体系。`supported_with_limits` 必须披露限制；所有现有诊断继续默认 `causal_claims_allowed=false`。未知强度不是新的一档，属于非法报告。

报告至少复用并明确表达：策略 id/版本、状态/原因、适用性、必需覆盖、逐项检查、风险/冲突、实际来源、结论强度、因果许可和可追溯引用。报告与运行中的 full observations 关联，不拿模型摘要重新计算；检查器不能写入观测或消耗工具预算。

没有分母时的新报告覆盖率为 null，不能写 100%。对仍需保持旧字段形状的兼容序列化，可保留旧数值 0，但须有明确的新状态及适用性字段，内部决定不得再读这个占位百分比。

### 6.2 校验检查器自己的输出

只在固定边界检查一次：已知结果类型/版本、枚举和值域、required_covered 不大于 required_total、来源属于该次实际观测、true 与强度/覆盖/阻断结果一致。非法结果按 check_failed，禁止带着未知枚举继续综合。错误只暴露稳定原因码及安全说明，不回显连接串、原始异常或内部数据。

同步检查器只接收内存中的已授权证据，不做 I/O，也不另开线程伪装成可取消。检查前后尊重现有 Run 截止时间，扫描量以本次已取得的数据为界；如需抢占式超时，应另提有实际资源生命周期证据的方案，不在此引入进程执行平台。正常取消必须继续传播，不捕获为 checked 或成功结果。

## 7. 规则语义与批准的变化

| 项目 | 等价抽取阶段 | 新策略版本行为 |
| --- | --- | --- |
| 字段覆盖 | 精确保留原 any-row 覆盖，供版本对照 | 必须声明 dataset_presence 或 each_row；不能用多个不完整行拼出完整记录。CAP-01 能力行、CAP-02 事件行采用 each_row；其他规则按实际记录语义逐项登记，未注明不能默认加严全部工具 |
| 小样本 | 原字段集合与小于 30 规则结果保持 | 阈值与适用字段由对应策略配置；沿用现有值，不新增“公司统一标准”。0、负数、布尔值、非数及缺值不作为充分样本；按契约错误或诊断不足分别处理 |
| 空结果 | 保留原诊断的不足判定 | Tool 可以合法返回空集合；本项诊断不足。某个工具的“无异常”是否可作为证据要有该能力的明确契约，不把空集合一律变为失败或健康 |
| 范围与检索焦点 | 保留普通路径/光刻的现有差异 | 焦点规则属于所选策略/来源适配，验证实际返回范围与输入口径；缺失必要焦点元数据不能靠工具名推断一致 |
| 规格/单位/时间冲突 | 现有 key 和规则按旧版本保留 | 按实体、指标、可用单位/版本/生效窗判断可比较性。不同合法版本/时间不能直接视为同一事实冲突；缺元信息不得宣称版本一致，也不能用缺信息放行已有矛盾 |
| 知识来源 | 原置信度与引用约束保留 | 可验证 knowledge/case 等真实来源类型及焦点；仅有 knowledge 类型或引用编号，不能证明“正式批准且生效的 SOP”。实际缺少状态/生效元数据时明确说明未验证，不造字段或新增查询 |
| 截断与分页 | 记录现有达到 limit 的风险 | 区分来源本身不完整与仅模型视图裁剪；后者不使 full observations 丢失证据。limit 命中只是可能截断，不能伪造确定的总量 |
| 自然语言 acceptance_criteria | 不把文案自动编译成代码 | 对机器可证部分逐项实现；需工程审批或外部数据的部分标为未验证/人工判断，不生成虚假通过 |

只批准上述有证据的语义修正；不在本项新设 Cpk 门槛、不重新计算各报表指标、不引入因果推断，也不把历史工厂模拟数据当作公司制度。规则变更记录输入、旧判断、新判断、原因和版本；新期望不能由被测实现自己生成。

## 8. 编排、答案与流式处理

### 8.1 收集决定

决定由 Runtime 形成，复用现有 LoopGuard/预算，不由评估器写 Guard。首期不新增自动补查规划器；“可以继续”只允许现有计划/Loop 在授权及预算内继续，不能擅自加步骤、扩查询或重复同参调用。

| 条件 | 收集决定与最终输出 |
| --- | --- |
| 必需证据齐全、策略满足 | 可结束收集，按实际强度综合；仍不允许把相关性说成因果 |
| 覆盖齐全但有不可消除的冲突 | 可结束并受限总结；披露冲突，不将“收集结束”写为通过 |
| 有可补充缺口，尚有允许的未完成调用 | 允许已有收集路径继续；Ready 本身不额外发起未声明工具 |
| 缺口不可补、预算耗尽或无进展 | 停止收集并给受限结果或澄清；不无限重试，不补造证据 |
| 必需策略检查失败 | 不继续依赖该检查的自动诊断；输出安全故障说明及可独立确认的事实，不调用模型假装补上验证 |
| 无策略且宿主允许 | 通用回答或已授权工具观测；无“已验证诊断”标识，不强制诊断章节 |
| 取消 | 保持取消语义并释放资源，不包装为一次成功的受限总结 |

必须保留已存在的 stop_reason 优先级，后到的评估结果不能覆盖取消、预算耗尽或权限拒绝。各入口在相同证据/策略下给出相同结论许可，但不要求 Ready 与 Loop 产生完全相同的工具调用顺序。

### 8.2 答案与外部兼容

- 复用现有直接事实、推断、引用范围及语义支持检查；本项不对任意文本给出真实性保证。任务级证据不足时，可保留经逐声明支持的直接观测。
- 是否启用证据支持检查不再由旧 status==validated 单独决定；宿主要求和实际策略结果持续有效。展示模式仍按已有用户请求/Skill 说明选择，缺少某章节不等于数据失败。
- 必需检查失败时使用确定性安全降级；模型知识只能作明确标注的通用补充，不能替代生产证据。无策略普通回答不标注“已通过业务校验”。
- 首期保留 HTTP/SSE 外层键、既有 event 名、工具描述和 submit_analysis 输入；在 evidence_validation 内增加四个明确字段：`assessment_status` 为本节状态值，`assessment_reason` 为稳定原因码或 null，`policy_ref` 为 component_id/version 对象或 null，`evidence_sufficient` 为 boolean 或 null。既有覆盖/风险/强度字段继续可读。checked 的旧 status 仍为 validated，其他旧视图可为 not_applicable，但**所有新决定只读规范化结果**，不能据旧字段放行。
- 旧 EvidenceValidation 只作为有消费者的序列化视图，从同一次规范化评估派生，不做两套检查。历史持久化记录按原样读取，缺少新字段表示当时未记录，不能重跑后补写或回填“通过”。
- 新增字段或 schema 版本的确切 diff 在 031a 固定，031d 按该 diff 验收；若发现真正外部消费者要求非加法变更，先报告影响，不擅自删除现有响应字段。

### 8.3 流式不成为旁路

受控诊断在完成适用检查/答案支持处理前，不向用户发送将被后续否决的生产结论。必须检查模型纯文本返回、submit_analysis、Ready fallback、Loop 迭代上限和异常降级所有出口；必要时缓冲最终答案，工具进度仍可正常流式发送。通用无策略聊天不因此统一关闭流式。

验收直接检查用户实际接收的 SSE、最终响应和持久会话内容，而不是只断言最终字符串已修复。取消后不能补发成功答案；断开/重放不得泄漏缓冲的未验证文本。不承诺与旧行为相同的首字延迟，是否增加延迟在报告中说明，不降低现有性能阈值。

## 9. 可独立执行的分段计划

| 分段 | 具体工作 | 完成证据与边界 |
| --- | --- | --- |
| 031a 契约与基线 | 盘点所有验证入口、七类规则、外部/持久化消费者与版本；固定统一报告和兼容字段 diff、宿主要求和版本映射 | 写 `docs/reports/mod-031-validator.md` 基线章节；用既有样例固定旧判断，新行为表使用独立手写期望；未切换运行链 |
| 031b 等价归属 | 提取业务声明/规则与通用评估；移动 skill_policy；默认和光刻复用单一来源，原版本结果保持 | 同一完整 observations 的旧/新报告深比较；默认七类及光刻焦点反例；无旧目录恢复、无永久空转发；此步不夹带语义改变 |
| 031c 统一执行 | 固定新版本策略和宿主要求，接 Ready/Loop/Skill/离线入口；落实状态、非法返回拒绝、收集决定及第 7 节逐项修正 | 真实执行链的成功/不足/冲突/配置删除/检查异常/预算/取消；来源调用与最终结果均有断言；旧发布版本保持其明确规则 |
| 031d 答案与兼容 | 所有答案出口使用规范化结果；展示解耦；加法响应、历史读取、SSE 缓冲与持久结果一致 | 确认未支持的强结论未出现在任何流式片段/最终答案/持久记录；普通 Skill 不被强制报告模板；旧历史可读 |
| 031e 阶段验收 | 更新边界、可移植切片和 MOD-024 唯一归属/Profile，实际仓库外交付、跨平台验证与文档收口 | 版本固定/回退、外部目录实跑与来源隔离；必要全量和浏览器审计；准确区分 PASS、既有失败、环境缺项与未验证 |

每批一个有界提交；没有本轮明确提交/推送授权时，交付为可审阅工作树。执行者先读 AGENTS，再核对本方案附录符号和真实消费者。允许调整局部类名和文件拆法，但不能默默改变本版行为表、放宽拒绝或增加额外平台。

## 10. 验收矩阵与运行范围

| 必须场景 | 必须观察到的结果 |
| --- | --- |
| 最小 Skill / workflow-only / policy-only | 发现与加载符合现有格式；生产执行资格独立判断；没有伪造通过 |
| 删除受控诊断的可选 policy 字段 | 宿主要求仍生效，激活失败、来源调用 0；不是只检查 manifest 解析 |
| 非法声明、错版本、不可信实现 | 失败原因可解释，未执行业务来源；不静默换成缺省 |
| 满足证据、部分覆盖、空结果 | Ready/Loop 许可一致；合法空 Tool 结果与诊断不足分别表达 |
| 两个不完整行拼齐字段 | each_row 策略不判为完整；旧版结果仍按旧规则验证 |
| 零必需项、未知强度、非法报告结构 | 不产生 sufficient=true；必需诊断不得以不适用逃过检查 |
| 样本不足/零/非数、低置信度、可比较性不明 | 无伪造统计充分性；限制与涉及来源可追溯 |
| 同一事实冲突 / 合法不同生效窗 | 前者限制结论；后者不被粗糙 key 误判；缺元数据不会被当成已确认一致 |
| 检查异常、取消、截止时间、预算耗尽 | 区分原因，释放资源；没有追加越权调用或吞掉取消 |
| 无策略 Tool/普通说明 | 权限/范围/契约仍执行，普通答案不强制诊断章节 |
| 纯文本/submit/降级/上限出口 | 同一限制全部生效；SSE/返回值/持久记录均没有被否决的强结论 |
| 当前与旧策略版本、发布禁用/回退 | 精确解析自己的规则；不偷用 latest，不关闭宿主要求，不跨 Run 污染 |
| 模型视图截断与重复引用 | 用完整授权证据判断；同一调用/回读不重复计入独立证据 |
| 独立交付 | 检查从实际制品导入，允许/拒绝场景真实运行；无 settings/DB/网络隐式访问，无重复源码所有者 |

实现从直接相关集合开始，当前可复用命令如下；新增场景加到真实责任所在的现有测试，不为每行制造一个新文件：

```bash
python -m unittest tests.test_evidence_validator tests.test_evidence_semantics tests.test_evidence_serialization tests.test_skill_evidence_policy tests.test_skill_standard tests.test_answer_synthesizer tests.test_evidence_truncation
python -m unittest tests.test_ready_plan_execution tests.test_ready_result_policy tests.test_agent_loop_split tests.test_runtime_convergence_acceptance tests.test_skill_agent_assembly tests.test_skill_release_assembly tests.test_skill_releases tests.test_litho_cpk_skill
python -m unittest tests.test_litho_cpk_portable tests.test_skill_releases_portable tests.test_module_release tests.test_module_release_install
python scripts/check_repository.py
python scripts/check_module_boundaries.py
python scripts/check_modularization_boundaries.py
git diff --check
```

WSL 与 Windows 各用平台解释器；涉及 PIL/jsonschema 的集合必须先核对依赖，不把另一个环境的通过冒充本环境全量。新增 shared policies 按唯一文件归属加入实际需要的 Profile，不因源码入包就声称可执行。

031e 必须按 [测试策略](testing-strategy.md) 运行完整 Python 审计、`python scripts/run_quality_gate.py full` 和 `npm run test:e2e`；涉及流式/持久化使用实际 HTTP/SSE 与会话读取链。两平台构建 MOD-024 制品并在仓库外验收 tool_sources+skill_release；没有 wheelhouse 的 model_transport 如实 NOTRUN。纯评估/拒绝场景无需 Live 或真实公司接口；不自动安装/升级依赖或连接模型。

起点 030e 的 Windows 全量有既有失败、full 门未过，不能用“历史已通过”掩盖。实施者须在同一可用环境对当前执行起点重跑相关基线，列出本次失败差异；新增功能失败必须修复。既有失败、缺依赖、未运行项分别登记，完整门未通过不得写全绿或自动推送/发布。性能按实际影响及既有门触发，不引入新阈值或重复 1000 次性能采样作为纯抽取的固定成本。

## 11. 非目标、回退与停止条件

不实现 MOD-029 卸载、不改数据源接入方式、不增加生产写操作、不实现自动通用 Skill Runner/动态策略执行器，不升级数据库/框架。工具名、描述、输入 Schema、默认 21 项工具加 submit_analysis 保持；规则/回答的批准变化单独版本化，不能假称完全无行为变化。

回退以完整代码/策略/Skill 版本组合为单位，保持旧记录可读；不能只回退 manifest 或关掉验证。受控策略缺失/不可用时回退到可用且仍获宿主允许的版本，否则明确不可执行。无业务数据库 Schema 迁移，不重写历史会话。

下列情况先报告候选方案及影响，再等待决定：必须新增公司业务阈值或字段来源；发现真实外部消费者要求破坏性 API/持久化迁移；必须开放自动代码执行/新的查询能力；遇到新失败且修复超出本版批准语义。文件拆分、纯内部命名和测试归并由执行者自行决定，不重复索取已有授权。

完成标准：五批验收证据齐备，现有执行入口都实际消费统一语义，旧业务硬编码与无消费者适配退出，剩余兼容项有消费者/归属/退出条件，报告不夸大检查能力；未满足时保持未完成。交付报告、必要结构/台账、规则版本变化和未验证范围统一维护，不另造平行任务清单。

## 附录 A：1651242 的实际符号与消费者

| 位置 | 当前符号/职责及实施动作 |
| --- | --- |
| app/evidence/validator.py | EvidenceObservation / EvidenceValidation / validate_evidence；_sample_and_source_risks、_fact_conflicts、_step_matches 的业务分支分类迁出，保留纯入口和通用匹配能力 |
| app/evidence/skill_policy.py | skill_step_matcher / validate_skill_evidence；实际消费者为光刻 Workflow/测试，迁入业务策略后更新并退出旧文件 |
| app/evidence/semantics.py | descriptor_for_tool 含 _TOOL_SEMANTICS 与旧 query 识别；通用支持关系保留，业务描述映射由真实所有者提供，历史消费先核对再删 |
| app/planning_runtime/builtin_playbooks.py、named_playbooks.py、playbook_contracts.py | 七类规则和命名投影；提取唯一权威证据声明，保留真实规划消费者需要的视图 |
| app/skills/contracts.py、manifest.py、discovery.py、loader.py、releases.py | v2 可选性已有；复核按需解析、固定资源、错误发现、发布与回退，保持 v1 读取 |
| app/bootstrap/skill_assembly.py | SkillEvidenceOutcome / SkillBinding.check_evidence / resolve_skill_binding；宿主必需约束、报告合法性及统一结果桥接 |
| app/bootstrap/litho_cpk_workflow.py、litho_cpk_demo.py | capability-evidence@1.3.0 的绑定及试点；光刻 5 Tool 中趋势当前非必需，不擅自升为必需 |
| app/agent_runtime/stages/ready.py、execution/loop_round_validation.py | 直接验证、答案契约及 enter_synthesis 条件；共享解释报告，分离收集决定 |
| app/agent_runtime/synthesis/fallback.py、execution/loop_answer.py | 离线、文本、submit、迭代/异常出口，防止路径漏接 |
| app/evidence/answer_synthesizer.py、agent_runtime/synthesis/result.py、service.py | 逐声明检查、答案契约、序列化和审计；核对外部/历史读取，复用已有呈现模式 |
| app/api/services/chat_stream.py、model_gateway/streaming.py、conversation/sessions.py | 实际流式传送与持久化链；确定缓冲所在最小边界，不因新增业务策略重写 Gateway |
| evaluations/mod_003_boundaries_v1.json、mod_024_release_v1.json 及受影响切片 | 路径归属、依赖、Profile 和资源清单同步；不机械放宽整个 skills/ 的边界 |

定稿时只核对源码、链接、事实和 UTF-8/LF/diff；用户随后明确授权实施。实际源码、冻结期望的有界变更和测试结果以 [实施报告](reports/mod-031-validator.md) 为准。附录为 1651242 的交接基线，不是当前完成快照。
