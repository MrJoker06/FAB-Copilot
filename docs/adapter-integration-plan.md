# MOD-025：值班助手模块接入与替换验收方案

v1.0 编制于 2026-11-18，源码基线为 `0dbbcf6`。2026-11-21 在 `feat/pe-ee-duty-workspace` 的 `cc52529` 上实施。当前交付和验收见[实施报告](reports/mod-025-adapter-integration.md)，实际接入入口见附录 B。

## 1. 目标与完成后的使用方式

后续产品优化优先服务 PE / EE 值班工程师。本任务把现有能力整理为可逐块接入、替换和验收的边界，使内网实施者能回答：这一块负责什么、需要公司提供什么、在哪里绑定、怎样验证，以及接入失败会怎样表现。

按业务顺序覆盖基础报表、SOP&历史case、值班数据查询，再覆盖会话/结果/上传状态、模型目录与健康。保留现有 Tool、Skill 与 Runtime 能力，复用已完成的接口和验收，修复实际阻碍模块替换的耦合。

完成 MOD-025 表示接入契约、离线替换证据和明确范围内的依赖修正完成，不表示真实公司接口、完整独立 HTTP 应用、可信生产认证或故障恢复已完成。公司接口没有确定，不阻塞契约与离线验证；相应生产能力必须继续标记“未接入”。

## 2. 依据、约束和非目标

### 2.1 依据的性质

| 性质 | 依据 | 本任务如何使用 |
| --- | --- | --- |
| 项目必须遵守 | [AGENTS.md](../AGENTS.md)、用户确认的值班助手优先级、Windows/Linux 支持和禁止模型任意 SQL | 决定范围、数据边界、平台验证及交付方式 |
| 既有任务定义 | [总方案 P5](architecture-modularization-master-plan.md#p5模块交付与内网集成)、[模块化追踪](todos/modularization.md)、[执行计划](todos/execution-plan.md) | MOD-025 负责逐块接入说明与 Fake 验证；026/027/028 分别负责演示、完整组合、版本发布评审 |
| 已有项目契约 | [Tool/Skill 规范](skill-tool-standardization-plan.md)、[错误码参考](error-code-reference.md)、[结果卸载方案](tool-result-offloading-plan.md)、[模块搬迁说明](module-portability.md) | 保留具名操作、来源、错误语义、Session 生命周期和制品归属，不另起一套机制 |
| 推荐实施约定 | 按消费者注入来源、以同一组语义用例验证不同实现、显式配置和失败关闭 | 是可调整的工程方法，不声称是外部强制标准，不固定某种 Port/Repository/目录结构 |

### 2.2 必须保持

1. 不让模型生成或执行任意 SQL，不恢复旧 SQL 工具。数据库访问只能由服务端受控实现执行固定查询或具名操作；报表/API 同样校验参数与授权。
2. 默认 21 项业务工具及 `submit_analysis` 协议的名称、描述、输入 Schema 不因接入整理改变。若实际接口要求破坏性调整，先列出影响并征求用户决定。
3. 保留公司 Qwen 及其他模型的配置、凭据引用、Thinking 档位/方言、发布检查和健康处理；不得以重新初始化方式抹掉配置。
4. 权限、范围、预算在实际调用路径执行。来源不可用、参数无效、身份拒绝与成功但空结果必须可区分；不得静默切换模拟来源。
5. 模拟数据和测试响应不含公司资料或真实凭据。`display_mock_data/` 继续只承担页面合成展示，不成为生产 Tool、RAG 或状态存储的隐式数据源。
6. 不破坏共享资料“处理完成后共享、管理员管理”及个人知识归属语义；不以公共展示目录替代上传存储。现有身份机制不是可信生产认证，不能因此宣称已完成生产 ACL。
7. 使用 UTF-8/LF；支持 Windows 与 Linux/WSL；不新增自建 SHA-256 校验门，不改 Git 身份，不输出/提交配置秘密或状态数据库。

### 2.3 本任务不实施

公司真实数据库/报表接入、LDAP/SSO 与完整 Guardrail、意图/证据策略重设计、任意插件自动发现、通用 Adapter 管理平台、微服务化、自动执行 Autosystem 操作，以及 MOD-020～023 的 Checkpoint/恢复能力。Autosystem 保持当前占位状态。生产接入另按企业任务启用。

## 3. 接入边界与资料要求

### 3.1 五组能力

| 组 | 边界与当前消费场景 | 替换/迁移所需资料 | MOD-025 最小验收 |
| --- | --- | --- | --- |
| A 基础报表 | 报表目录管理名称、文件夹、链接、排序和启停；助手查询报表数据走具名 Tool，两者分别接入 | 目录维护权限、链接规则；数据查询另需指标口径、参数、时间与返回字段 | 目录在显式临时路径读写且不改模型状态；数据 Tool 使用显式来源，坏参数/拒绝/来源故障真实可见 |
| B SOP&历史case | 分开核对工厂知识/案例后端、共享上传资料、个人知识；检索、目录与详情须能关联同一原文 | 文档/案例 ID、版本、状态、来源地址、访问主体、更新/停用规则，以及检索/详情接口 | 受控假后端替换检索与目录/详情，来源及引用一致；不同归属不混淆，缺详情/错误 ID/停用资料不伪装命中 |
| C 值班数据查询 | 设备健康、异常、传感器、趋势/统计等现有具名操作；按现有能力逐组说明，不新造全厂分析任务 | 只读账号或报表/API 选择、业务口径、设备范围、单位、时间区间/时区、刷新频率和权限 | 同一 Tool 绑定可替换来源；查询条件原样受控映射，空结果与故障区分，Ready/Loop 的范围和来源兼容 |
| D 应用自有状态 | Session/消息、独立结果库、模型状态、报表目录、共享上传元数据及原文、个人知识元数据/原文/索引 | 实际存储位置、初始化条件、主体标识、依赖关系、维护窗口和回滚要求 | 在隔离临时存储中保存后重开可读；不接演示业务库也可验证已声明状态切片；删除/撤销与引用不可越过归属 |
| E 模型接入 | 模型协议、目录/选择/凭据引用、发布检查、健康状态与 Context 专用能力校验分别明确归属 | 协议能力、上下文限制、Thinking 选项、连接配置来源、目录/健康存储及失败策略 | MockTransport 验证协议；目录/健康用隔离状态保存；应用发布仍包含 Context 校验，网关可无 Memory 独立导入运行 |

A 组的“打开公司报表链接”不等于后台读取报表数据。不能把已有目录链接推断为存在查询 API，也不强迫普通导航经过模型 Tool。

B 组先记录当前共享上传和检索是否真正连通。没有真实消费者的连接不在本任务悄悄补成“全部上传自动进入 RAG”；如需新增索引、共享范围或检索行为，列为独立需求确认。

D 组属于应用状态管理，不要求模型通过 Tool 读写自身会话、模型目录或维护数据库。维持受控服务/存储调用即可；任何新后端须依据真实替换需要，而非为了统一名称改写全部存储。

### 3.2 公司接口尚未确定时

每个接入说明写明：现有契约、候选来源、已确认事项、缺失资料和对应企业任务。只读 DB 与报表/API 均可保留候选，不编造表名、SQL、URL、认证流程或“已支持”的厂商 Adapter。

接口定型前只实现能由当前消费者证明必要的接缝。没有真实资料，不新增 Oracle/SQL Server 驱动、HTTP 客户端或仅返回假数据的生产 Adapter 类。Fake 作为离线验收依赖显式注入，报告必须标明它验证了什么、没有验证什么。

### 3.3 每组说明的固定内容

接入材料集中维护在本文件附录及 [module-portability.md](module-portability.md)，验收结果集中在一份 MOD-025 报告；不再创建一份平行手工状态清单。每组填写：

- 能力、真实消费者、输入输出契约和版本；当前实现、来源类型、配置位置与装配入口。
- 数据所有者、访问主体、允许操作和范围；单位、时间边界、排序/分页、新鲜度和空结果含义。
- 来源与查询时间/范围的表示；错误分类、取消/超时状态，以及是否允许重试的实际条件。
- 连接/客户端所有者、创建和释放时机；导入、初始化、读取和迁移分别会产生什么副作用。
- 可用的固定输入、人工可读预期、命令、返回结果、拒绝反例和仓库外运行证据。
- 公司尚需提供的资料、未实现项和后续任务；不得用“可替换”掩盖仍依赖全应用初始化的事实。

## 4. 总体技术方案

### 4.1 来源装配

延续已存在的消费者契约与显式装配：业务 Tool/检索/状态服务使用已绑定来源；宿主负责选择实际实现及配置。复用现有 `ToolSources`、工厂搜索后端注册、存储身份绑定和模型网关，不为接入说明新建统一 Registry、Connection Manager 或永久转发目录。

对已有能力做一次替换验证：把实现 A 换成受控实现 B，不修改 Runtime/Skill 的业务执行逻辑。两种实现运行同一组语义断言，允许其来源标识和实际数据不同，不要求用同一被测算法生成两份“相等结果”自证正确。

如发现某组只能依靠全局环境、跨模块具体函数或隐藏演示初始化才能运行，先定位真实消费者，再实施该组所需的最小修正；不顺手清理其他 MOD 的兼容层。

### 4.2 应用状态迁移

先验证已有存储注入及 `application_storage` 切片，不预设所有存储都迁移到同一新数据库。隔离测试须覆盖初始化显式触发、保存后重开、不同主体隔离，以及缺失/不可写存储。

Session 主状态和独立结果库迁移必须配套，保留原主体及 Session 标识；删除/撤销遵循已有生命周期。共享上传的元数据与原文、个人知识原文与索引、报表目录配置分别写明是否需要一起迁移。不能只复制主库就声称原结果引用或文档可读，也不能用普通查询隐式触发生产迁移/模拟生成。

本任务不编写通用跨数据库迁移器，不执行用户现存数据迁移。现有备份脚本未覆盖的成员明确列为缺口；需要新增实际备份/恢复功能时，单独定义其操作范围和授权。

### 4.3 模型探针与 Context 的依赖收敛

当前问题：网关的兼容性检查直接导入 Context 的消息构建与 JSON 响应校验，导致仅搬模型能力也携带 Memory 业务依赖。以下是选定的实现方向，而不是仅删除两条 import：

1. 网关维护通用传输、SSE/工具调用解析、通用模型检查、Thinking 参数、时间/事件/字节限制和客户端生命周期，不依赖 Memory 或应用状态实现。
2. Context 保留具体上下文消息和响应协议的唯一来源，提供现有业务探针所需的构建/校验能力；不复制 prompt，不把业务协议搬入 `core`。
3. 在 bootstrap 的应用发布检查入口组合二者。原“完整应用兼容性检查”的编排归应用装配，网关接受可信宿主提供的一个有界检查回调或等价直接组合；不建设插件发现或探针注册平台。
4. Context 检查通过网关拥有的受控发送能力使用同一会话和限制；不另开客户端，不绕过超时/取消预算。Context 校验失败由应用组合映射到既有公开错误，不能被通用 JSON 检查代替。
5. HTTP 路由、`app.main.check_model_compatibility` 的应用入口、管理端 patch 接缝、返回检查项与失败阻断语义保留；已有内部 Python 消费者改为从实际所有者导入。原网关中的完整编排可迁出，不留下反向导入的永久转发层。
6. `ModelCompatibilityError` 和通用 Provider 选项仍归模型协议层。仅传输检查的结果明确标注范围，不能当作完整应用检查来发布模型。

目标调用关系：

```text
管理端完整兼容性检查
  → 应用发布检查装配
      → 网关通用检查、受控发送与客户端生命周期
      → Context 消息构建/响应验证（通过上述受控发送执行）
  → 管理端存储完整检查的成功或失败报告

独立模型协议验收 → 网关 + MockTransport（无需导入 Memory 或初始化状态库）
```

模型声明入口可创建状态为已发布、兼容性为未验证的记录。完整检查由管理员显式触发，成功时更新兼容性报告，失败时保存公开错误。检查与声明沿用各自的现有状态行为。纯传输报告不能写成完整应用检查通过。

必须保留连接流式、工具参数、上下文负载、结构化 Context，以及已声明 Thinking 的答案/工具往返检查。保持原阶段顺序与失败后停止行为，除非另有必要且已审阅的协议变更。若发现已承诺的外部调用方必须继续使用原网关导入路径，先提出明确迁移/兼容选择，不擅自破坏该承诺。

## 5. 分批实施与验收

按 a → b → c → d → e 执行。各批次及其验收归入同一工作包。

### MOD-025a：接入基线与消费者核对

- 阅读适用指令和本文依据；记录实际源码起点、工作树修改、当前制品 Profile 与相关既有失败。
- 逐组核对第 3 节全部边界；特别区分导航链接/数据查询、共享上传/个人知识/工厂检索、应用状态/公司业务库。
- 在本文附录和搬迁说明补齐真实装配符号、已有切片范围及缺口；列出需要实际代码调整的最小集合，并核对探针所有消费者。
- 执行最小相关基线测试；记录环境缺项和失败，不把历史报告当成本轮结果。
- 交付：经源码核对的接入说明、最小改动清单、基线证据索引。没有形成代码缺口也可以交付，不为批次强造重构。

验收：五组均可找到输入/输出、装配点、来源/状态归属、离线验收入口与生产资料缺口；新增机制能说明真实消费者。公司 DB/API 选择仍可明确待定。

### MOD-025b：值班数据与知识来源替换验证

- 优先复用现有设备/报表/检索/具名查询契约和 Fake；逐组给出小型固定输入、可读输出及反例。
- 选设备范围查询、一个异常/趋势查询、SOP/案例的检索加目录/详情链作为代表性实际验证；其余已有业务组引用可复现的既有契约测试，不扩展新业务功能。
- 如发现隐藏来源选择或全局初始化，修正该消费者的最小装配接缝；目录与详情必须属于同一选定后端，配置错误不得回落到 SQLite/Fake。
- 验证缺参/未知设备或范围、错误日期、拒绝、超时、空数据、畸形来源、缺少来源及详情 ID 不一致。反例按实际接口适用性选择并解释，不凭空增加每个查询不存在的权限模型。
- 对改动的 Tool 同时验证独立 Handler 与 Ready/Loop 的实际输出和来源；遵循现有错误码与预算语义，不新增任意查询入口。
- 交付：必要实现修正、补缺测试、接入说明与阶段证据；无缺口部分复用既有验证。

验收：替换声明范围内的数据/检索来源仅需改变装配；拒绝时实际来源未被读取；错误不会变成成功空列表；未声明的公司连接没有被构造。基础报表普通链接和现有页面行为保持兼容。

### MOD-025c：状态、模型目录与健康接入验证

- 对 D/E 组分别验证已有存储身份注入、结果库工厂和模型目录/健康存储；不把所有状态强制搬到同一后端。
- 使用临时目录和 SQLite 等当前已支持的真实存储完成写入、关闭、重新打开及读取验证；Fake 只替换外部边界，不能用内存 mock 代替声称已验证的持久化。
- 验证两套显式状态配置不交叉读取，测试身份不等同于已认证生产身份；用现有可信测试主体证明存储归属拒绝。
- 在相关真实 HTTP/Session 路径核对保存与恢复、共享资料原文、目录状态及模型配置独立性；仅检查本次改变的链路，不重做 UI。
- 写明每类状态的维护窗口、配套成员、配置优先级、缺失数据行为和回滚限制。保留结果永久删除和跨轮回读规则。
- 交付：必要存储装配修正、真实持久化/HTTP 验证、状态搬迁说明。尚无完整运行 Profile 的上传/目录/模型管理明确标注“应用组合待 MOD-027”，不伪称整个服务独立交付。

验收：已声明切片不依赖原仓库数据库或演示业务生成；隔离状态能持久化重开；缺少必要成员明确失败；用户模型配置和私有资料未被读取、重建或改写。

### MOD-025d：应用模型探针组合与债务退出

- 按第 4.3 节调整职责及实际消费者，保留应用入口与 HTTP 错误协议；必要时增加一个有实际消费者的装配模块，路径由执行时职责决定。
- 使用 `httpx.MockTransport` 回放原能力检查，核对实际请求序列、Thinking 档位/方言、工具参数、Context 构建与校验；构造“通用协议通过但 Context 响应不合法”的反例，证明仍阻断应用兼容性通过。
- 在管理端真实路由链验证不支持能力、超时、坏响应、配置错误不会更新为已验证/已发布；MockTransport 不等于真实 Qwen 可用。
- 用新的隔离进程证明纯模型协议检查不导入 Memory、不触发数据库初始化、客户端正确关闭；Context 规则仍有唯一来源。
- 更新原文件归属、运行 Profile 的必要闭包与测试消费者；仅在实际依赖消失并通过检查后删除台账中的两条 MOD-025 债务，其他 MOD 的例外不顺手退出。
- 交付：最小职责修正、离线协议/管理端反例、独立导入证据、台账与迁移说明。

验收：两条网关→Context 依赖实际消失；完整应用检查范围未减少；纯网关与完整应用检查不可混用；默认 HTTP/管理端行为、Qwen 参数及现有模型数据兼容。

### MOD-025e：双平台交付复核与总验收

- 汇总各组固定输入、预期、命令和结果；每组区分“说明已完成”“契约可替换”“切片可运行”“真实接入未完成”。
- 按当前 MOD-024 交付机制构建、复制并在仓库外使用新 venv 验证实际受影响的 Profile。至少覆盖 `tool_sources`、`application_storage` 和 `model_transport`；若 Skill/资源闭包受影响，再验证 `skill_release`，否则保留明确未重跑原因。
- Windows 与 Linux/WSL 使用各自解释器、依赖锁；验证 `app.*` 实际导入来源为安装目录。临时目录需在仓库外，不能只修改 cwd 而仍通过 PYTHONPATH 读取仓库。
- 如纯网关独立目标需要新增最小 Profile，必须复用发布组、唯一文件所有者和现有安装器，写清当前消费者；不得把整个 Memory 或应用依赖塞入模型 Profile 来通过检查。新 Profile 的成员和外部依赖要双平台实际安装验证。
- 按第 6 节完成阶段回归，写一份 `docs/reports/mod-025-adapter-integration.md`，同步总方案、结构、搬迁说明、测试索引和 TODO 状态；报告不复制另一套长期手工台账。
- 交付：经验证的既有/必要扩展制品、接入材料、唯一验收报告与任务状态更新。

验收：第 7 节全部完成条件满足后才标记 MOD-025 完成；交付机制和应用组合范围不冒充 MOD-026～028 已完成。

## 6. 测试、基线与执行命令

### 6.1 开始与每批验证

通过 WSL Git 核对 `git status --short --branch` 和 `git log --oneline -3`；起点变化先报告差异并核对影响。保留已有修改，不重置共享工作树；以本次执行起点建立基线。

从附录列出的相关模块开始 `python -m unittest <模块名...>`，改动存储/HTTP/流式时补真实链路，声称独立迁移时做仓库外安装。每个代码批次运行根目录约定的三个检查器与 `git diff --check`，新增/修改文件核对 UTF-8/LF。纯文档批次只检查事实、链接、文本和 diff。

### 6.2 阶段结束

执行计划要求的完整 Python 与完整浏览器回归不能被定向测试替代。两平台相关契约/切片均须验证；完整 Python 至少覆盖原生 Windows，并按测试策略运行 WSL 完整门，环境导致停止时保留停止点、已运行范围与原因。网关/Schema/认证或流式重大变化触发的质量门按现有策略执行，不能自行降级；Live 不自动启动。

```bash
python scripts/check_repository.py
python scripts/check_module_boundaries.py
python scripts/check_modularization_boundaries.py
git diff --check
python -m unittest discover -s tests -t .
python scripts/run_quality_gate.py full
npm run test:e2e
```

上面的完整门在隔离数据/配置环境运行，不直接读取用户配置后调用模型。系统模块依现有测试策略按隔离进程执行；完整覆盖率、性能门、平台跳过和失败分别汇报，不能把前置失败退出写成完整门通过。

交付复用现有入口；构建 ID、目标路径和 Profile 以实际改动确定，以下是命令形式，不是已执行记录：

```bash
python scripts/build_module_release.py --output runtime/module-release/mod-025 --build-id mod025-<实际批次>
python scripts/verify_module_release.py --delivery <仓库外交付目录> --work-dir <仓库外新环境> --report <机器报告路径>
```

外部依赖需目标环境锁与离线 wheelhouse 时显式提供，不依赖宿主开发环境偷偷补包。Profile 未提供完整服务入口时，不以单模块安装成功宣称完整服务可启动。

### 6.3 已知历史限制

`0dbbcf6` 的上一轮[错误规范报告](reports/issue-1-error-standardization.md)记录 Windows 1539 项、13 失败/10 错误/3 跳过，Node 65/65、Linux 浏览器 27/27；已有完整门并非全绿。这些只是开始时的参考，不能冒充本轮基线。

对新增失败修复或定位，不仅比较数量；同名失败也要检查失败原因和实际差异。若需要改 Golden/Schema/性能预期，单独说明原因、人工审阅，不能让被测实现生成期望值。不把重试后偶然通过覆盖首轮失败。

## 7. 完成判定

仅当以下条件全部成立才可将 MOD-025 标为完成：

1. 五组接入说明均经源码核对，明确真实消费者、输入/口径/范围/来源、装配、状态归属、所需公司资料和未接入范围；没有声称整个应用都已可独立安装。
2. 值班代表链路和各组声明的替换接缝有离线可复现证据；已有验证可复用，但必须实际复核当前相关结果。失败不静默回退，拒绝不产生实际来源读取。
3. 已声明状态在隔离环境中保存/重开/归属/删除行为正确；模型配置及用户原数据未受影响，迁移成员和限制可查。
4. 模型网关的两条 Context 债务真实退出，独立导入/协议和完整应用发布检查均验证；完整检查不能被缩减的传输报告代替。
5. 受影响制品在 Windows/Linux 的仓库外安装与实际运行通过；文件唯一归属、依赖闭包和版本一致，没有引入 SHA-256 门。
6. 相关新失败全部处理，完整回归及既有失败差异已报告；若必需测试被环境阻塞而不能提供等价证据，对应子项保持未完成，不能只填“环境问题”结项。
7. 必要报告与台账更新完成，未实施的生产接入、LDAP、恢复、演示和完整组合仍保持原任务状态。方案完成和 MOD-025 实现完成分开记录。

## 8. 需要暂停并向用户确认的情况

仅对会改变需求、数据或外部结果的情况暂停相关步骤；说明现状、候选方案和影响，不阻塞其他可独立工作的部分：

- 公司资料使 Tool 名称/输入输出或业务口径必须破坏性改变，或必须新增尚未批准的业务能力。
- 必须修改已有主体 ID、共享范围、文档可见性、结果保留/删除规则或真实数据迁移才能继续。
- 发现已承诺的外部 Python/API 消费者依赖拟退出的探针入口，无法在当前范围内兼容迁移。
- 需要真实账号、真实模型调用、公司网络访问、生产初始化/迁移或修改用户配置才能验证。
- 最小替换目标实际要求提前执行 MOD-021/027、建立新基础设施，或明显超出本任务边界。

普通内部重命名、测试 fixture 隔离和已有契约内的装配修正，在获得实施指令后可自主处理；不因内部实现选择重复要求授权。

## 9. 提交、报告与交接

后续收到实施指令后按批次记录结果；有提交授权时，每批提交标题包含 MOD-025a/b/c/d/e，并在提交前审阅明确暂存范围。是否推送沿用届时用户指令，不因本方案存在自动推送、合并或关闭其他 Issue。

临时执行计划、导出旧树、原始测试输出和机器报告放忽略的 `runtime/quality/mod-025-*`，仓库外交付测试使用另行创建的临时目录；不得提交数据库、凭据、缓存或 ZIP。受跟踪报告只记录结果、命令、解释器/平台、基线差异、迁移影响和未验证范围。

交接报告逐组列出实际改动/无需改动的理由、入口命令、可读结果、失败反例、制品/依赖范围，以及下一步真实接入需要谁提供哪些资料。收尾时更新本文状态与对应工作包，不改产品任务主统计，不自动开启 MOD-026。

## 附录 A：编制基线的源码和验证入口

以下记录 `0dbbcf6` 的定位线索，执行前核对，不是必须保留的最终目录结构。新文件只在现有文件无法清楚表达实际职责时增加；不得恢复已退出的 manufacturing/integrations 目录作为永久转发层。

| 能力 | 当前主要定位 | 已有验证入口示例 |
| --- | --- | --- |
| 默认来源/Tool 装配 | `app/bootstrap/tool_sources.py` 的 `ToolSources/create_tool_bindings`，`default_tool_assembly.py`，`app/tools/*/contracts.py`、`binding.py`、`data_source.py` | `tests.test_tool_sources`、`tests.test_tool_sources_runtime`、`tests.test_default_tool_assembly`、`tests.test_tool_sources_portable` |
| 设备/报表/具名操作 | `app/tools/equipment_health/`、`process_diagnostics/`、`production_reports/`、`operational_reports/`、`enterprise_data/`、`named_queries/`；Fake 归 `app/demo_data/` | `tests.test_equipment_health_equivalence`、`tests.test_production_reports_runtime`、`tests.test_operational_reports_runtime`、`tests.test_named_queries_runtime`、相应 portable 模块 |
| 工厂知识与案例 | `app/knowledge/search_contracts.py`、`search_registry.py`、`sqlite_backend.py`，`app/tools/knowledge_search/` | `tests.test_factory_search_backend_boundary`、`tests.test_factory_search_contract_portable`、`tests.test_knowledge_search_runtime`、`tests.test_knowledge_search_portable` |
| 报表目录/共享上传 | `app/api/report_directory.py`、`app/api/routers/shared_documents.py`，`app/knowledge/shared_documents.py`；完整应用状态路径说明见搬迁文档 | `tests.system.test_http_contracts`、`tests.system.test_knowledge_uploads` 与 `tests/e2e/shift-workspace.spec.js`，实施前按实际符号挑选用例 |
| 个人知识 | `app/personal_knowledge_runtime/` 的 service/storage/ingestion 及搜索消费者；不能把共享资料视为其 owner 私有上传 | `tests.system.test_knowledge_uploads` 及实际 personal_* 测试；完整 OCR/上传服务不是已有 model_transport 切片 |
| 应用存储/会话/结果 | `app/core/storage_identity_ports.py`、`app/bootstrap/storage_identity_assembly.py`、`app/persistence/`、`app/conversation/sessions.py`、`result_lifecycle.py` | `tests.test_storage_identity_ports`、`tests.test_persistence_separation`、`tests.test_tool_result_store`、`tests.test_session_result_lifecycle`、`tests.system.test_sessions_streaming` |
| 模型协议/状态 | `app/model_gateway/gateway.py`、`streaming.py`、`compatibility.py`、`registry.py`、`health.py` | `tests.test_model_compatibility`、`tests.test_model_health`、`tests.test_model_transport_portable`、`tests.system.test_model_governance` |
| 完整探针消费者 | `app/api/runtime_dependencies.py` 导出、`app/api/routers/admin.py` 消费；`app.main` patch 接缝、浏览器测试服务及直接 Python 测试消费者 | `tests.test_api_router_boundaries`、`tests.test_model_compatibility`、`tests.system.test_model_governance`、`scripts/run_browser_test_server.py` |
| Context 协议 | `app/memory_system/context/history.py` 的 `build_contextualizer_messages`，`protocol.py` 的响应格式及验证 | 复用现有 Context 用例并增加网关独立运行、完整组合失败阻断的缺口验证 |
| 制品/依赖台账 | `evaluations/mod_024_release_v1.json`、`evaluations/mod_003_boundaries_v1.json`、`scripts/build_module_release.py`、`verify_module_release.py` | `tests.test_module_release`、`tests.test_module_release_install`、两个边界检查器 |

编制时来源装配包含七类可选业务 Port，默认 21 项业务工具；现有 Profile 为 tool_sources、skill_release、model_transport、application_storage，发布组使用唯一成员归属。模型目录/健康已经通过存储身份绑定使用显式接缝，不应重复抽取；待处理的是具体替换缺口及探针的实际依赖。

台账中两条 `exit_task=MOD-025` 的边是 `app.model_gateway.compatibility → app.memory_system.context.history` 与 `→ app.memory_system.context.protocol`。源文件变化、Profile 扩展和债务退出必须以实施后的扫描结果为准，不能只修改台账使检查变绿。

## 附录 B · 内网接入与迁移清单

| 能力 | 当前输入、结果及接入点 | 公司须提供的资料 |
| --- | --- | --- |
| 基础报表 | 管理端维护报表名称、文件夹、URL、排序和启停，应用用 `FAB_REPORT_DIRECTORY_PATH` 指定目录 JSON。助手上的良率趋势、制程通过率和其他指标走 `ToolSources.production_reports`、`operational_reports` 等具名绑定。调用带日期区间及适用的制程、设备、产品筛选。检查指标单位和聚合粒度，成功空结果代表本次条件没有命中。 | 报表维护权限、导航链接规则。数据查询另需口径、源系统、刷新延迟、只读授权和时间区间约定。 |
| SOP 与历史 case | 用 `register_factory_search_backend` 注册宿主工厂并以 `FAB_FACTORY_SEARCH_BACKEND` 显式选择。工厂侧实现 `FactorySearchBackend`，提供目录时同时实现 `FactoryCatalogBackend`。Tool 绑定校验 `tool_source_kind`，传主体、检索范围及候选上限，匹配 `reference_id` 和原文来源。文档仅接收 Active，案例仅接收 Validated，详情验证请求 ID。未知配置或目录能力缺失直接报错。个人知识另走按主体限定的状态库，管理员共享资料通过现有共享页面管理。 | 稳定文档/案例 ID、版本、状态、原文链接或详情 API、可见性、更新和停用规则。 |
| 值班数据 | `ToolSources` 组合可注入 Port，默认路径由 `default_tool_assembly.py` 绑定 SQLite。设备健康、异常、传感器、Cpk 和具名批次/事件查询使用各自的 `contracts.py`。查询按计划范围传参，数据来源附查询范围，权限拒绝、来源超时和成功空列表分别处理。日期口径按当前工具契约，报警时间线最多返回 100 行。 | 选定只读 DB 或报表/API，明确设备范围、单位、时间区间/时区、事件计数与分页、超时及重试条件。 |
| 应用状态 | `StorageIdentityBindings` 绑定应用存储和可信测试主体，`application_storage` 可独立初始化应用 Schema 和结果库。普通来源读取由各 Adapter 管理会话，迁移和建库走显式维护入口。保存及撤销结果按 tenant、owner、session 约束。 | 维护窗口、既有主体标识与状态所有者、目标存储路径、备份与回滚负责人。 |
| 模型 | 模型连接、SSE 和通用探针在 `app/model_gateway`。目录、选择及健康由其 registry/health 经状态绑定写入。管理端 `app.main.check_model_compatibility` 进入 `bootstrap.model_compatibility_assembly`，通过同一客户端检查 Context 契约。纯传输报告带 `scope=model_transport`，登记兼容性时拒收。 | 端点和凭据引用、能力声明、Thinking 方言/档位、超时和上下文窗口。使用实际 Qwen 等供应商的验收另行安排。 |

迁移前停止写入并保存一组同时间点的文件。以启动实例的实际配置为准，普通启动时实例默认分配独立的应用库及结果库。进程环境优先于 dotenv，已有实例使用相同签名和主体名回读。

| 状态 | 配套成员及恢复验证 |
| --- | --- |
| 会话、消息、执行记录和结果引用 | `FAB_AGENT_DATABASE_PATH`、`FAB_TOOL_RESULT_DATABASE_PATH` 或对应实例的 `state/` 成员一起备份。恢复后核对旧 Session、引用分页、跨主体拒绝和永久删除。结果库路径与其他库重合会失败。 |
| 个人与共享知识 | 个人元数据/索引库 `FAB_PERSONAL_DATABASE_PATH` 与 `FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH` 下的原文配套。共享资料按 `FAB_SHARED_DOCUMENTS_ROOT` 整体保留目录索引、上传原文件和已有抽取内容。历史 SOP/case 则由工厂知识后端或对应知识库独立迁移。 |
| 报表目录与模型配置 | 单独复制报表目录 JSON。模型目录和健康随运营库备份，文件配置及密钥引用按 `FAB_LOCAL_MODELS_PATH`、`FAB_MODEL_CREDENTIALS_PATH` 管理，部署时由配置所有者提供。恢复后核对发布状态、用户选择、档位和凭据引用。 |

`scripts/manage_databases.py backup` 备份已注册的部门库。会话结果库、个人文件和索引、共享目录、报表目录 JSON、模型配置与凭据文件需要另列为同一迁移批次的成员。失败时停写，按原路径恢复整组快照。完整 HTTP 组合、可用的真实生产身份及公司后端留待对应工作包。
