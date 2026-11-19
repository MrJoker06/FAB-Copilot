# Issue #2 第 5 项：请求类型与业务主题分离

实施日期：2026-11-19。分支 `feat/pe-ee-duty-workspace`，源码基线 `a8a522c`。本项服务 PE / EE 值班问答、查数和问题定位，不实施 MOD-025 或 Issue #2 第 6 项的证据等级重审。

## 行为与范围

路由新增独立的 `request_type` 和 `business_topics`，旧 `intent` 保留为现有 Planner / Tool 装配的兼容选择结果。主题包含能力、良率、设备等，并不表示一定需要读取这些主题的当前生产数据。

| 用户输入 | 请求类型 | 主题 | 执行决策 |
| --- | --- | --- | --- |
| 什么是 Cpk？ | explanation | capability | 知识解释，不要求补制程，不开放制造 Tool |
| 查询昨天 CMP 的 Cpk | data_query | capability | 实际查询，保留 CMP 和昨天的范围 |
| 什么是导致昨天良率下降的主要原因 | diagnosis | yield | 实际诊断，不能因“什么是”而绕过数据取证 |
| 如何提高良率 | recommendation | yield | 通用建议，先走知识检索，不伪装为当前产线诊断 |
| 基于近期良率数据给改善建议 | recommendation | yield | 有当前数据目标，进入已有业务流程 |
| 解释 ETCH-04 报警代码的含义 | explanation | equipment | 解释术语，不因设备编号和“报警”触发当前故障查询 |
| 解释 Cpk，并查询昨天 CMP 的 Cpk | mixed | capability | 先确认主任务，不默默执行任一半 |
| 查询 YMS 站点良率 | data_query | yield | 未映射的公司简称继续澄清，不猜成某个制程 |

请求类型为 `explanation`、`data_query`、`diagnosis`、`recommendation`、`procedure_lookup`、`conversation`、`mixed`、`unknown`。主题由现有业务词表和确定性制程映射产生，不代表完整公司实体目录。

## 处理流程与职责

1. `app/intent_runtime/rules.py` 分别识别信息目标和业务主题。处理明确否定与替代任务，降低“参考 SOP / 知识库”等来源偏好对任务分类的干扰；当前仍是有限语言规则，不是通用语言理解器。
2. `routing.py` 结合两类结果选择旧执行意图。知识解释和没有当前数据目标的通用建议进入 `general_knowledge`；实际诊断仍使用既有制造路由、范围、风险与取证机制。混合请求先澄清，纯概念多主题不再被当作多个制造查询。
3. `conversation/decision_arbiter.py` 保留当前输入的优先权，检查扩写与原请求类型是否一致。完整的概念问题不会被旧制造 Flow 劫持；明确查数请求不会被知识问答提示覆盖。已有知识讨论可以承接一个明确的新查数追问，但不能凭模型扩写新造操作范围。
4. 新类型追问切换的操作范围从本轮输入及最近用户消息核对，不将助手回复或模型自报置信度当作实体依据；检查主题、制程、设备、批次与显式时间。缺少来源或扩写改变本轮日期时继续澄清。当前模型仍只能恢复上下文，不能创造公司简称映射或获得执行权限。
5. `planning_runtime/queries.py` 提取批次时复用已明确的任务文本，避免 Router 排除的否定对象在 Planner 中被重新选为第一个批次。
6. `bootstrap/default_tool_assembly.py` 对 `general_knowledge` 与 `sop_lookup` 只装配知识能力。Dispatcher 实际拒绝强行提出的制造调用；既有身份、预算、数据来源参数校验继续生效。
7. 路由事件、HTTP 流式结果和 Session 元数据写入新字段。分类解释只描述任务，不生成制造事实、SQL 或业务证据。

`confidence` 沿用旧兼容字段，仍是未校准的规则/语义提示分数。它不是正确概率，也不提供执行权限；路由系统消息明确这一点。

## 实现选择及参考

本轮实际比较可离线执行的两种方案：基线的业务关键词优先路由，以及请求类型/主题分离并复用既有上下文解析的候选方案。没有增加模型调用、Embedding 服务、运行依赖或额外 Agent。

- 继续只提高“什么是”的关键词优先级不能区分真实因果问题，故未采用。
- 采用独立任务维度、既有模型上下文提示和服务端仲裁，能够在现有环境重现、验证和部署；代价是语言规则和业务词表仍需维护，未解决全部同义表达或开放域语言问题。
- Embedding / 轻量分类器需要额外编码器、语料和部署评估；独立模型分类需要公司量化模型的实测及结构化输出、时延和错误率对照。本轮未实测这两种候选，不将其描述为效果落后，也不宣称已验证公司 Qwen 的分类表现。

机制参考：[LangGraph 的结构化路由](https://docs.langchain.com/oss/python/langgraph/workflows-agents#routing)与 [Semantic Router 校准说明](https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/features/calibration)。前者支持将选择结果结构化后再分支；后者强调原始相似度与校准概率的区别、校准与独立测试语料分开。本项没有引入这些框架，也没有执行概率校准。

## 兼容与限制

- 默认全局工具目录仍为 21 项具名业务工具 + `submit_analysis`，名称、输入 Schema 和全局对象身份未变；SOP 路径的每 Run 可用工具有意收窄为知识检索。
- `IntentRoute` 新字段带默认值，既有手工构造仍成立；API 新增的是输出元数据，不要求迁移数据库或回填历史消息。旧 `intent` 名称不等同于新请求类型，例如纯 Cpk 查询仍可使用兼容意图 `capability_excursion`。
- 沿用已有制造计划，纯查询仍可能使用现有多工具模板；本项不承诺每个查询只执行一个 Tool，不重写 Playbook / Skill 的证据语义，也不调整 Validator 等级。
- 新计划 ID 的既有计算包含 route 元数据，新增字段会改变新 Run 的计划 ID；没有重写旧计划、会话或执行记录，不代表 Checkpoint / 恢复链已经实现。
- 公司简称、设备和产品目录需通过实际可信来源完善。本轮没有接入公司目录、真实数据库或报表系统，也没有更改模型配置和凭据。
- 否定、复合请求与语义追问支持的是本报告验证的范围；不能把有限规则或回归样例的通过率当作开放域保证。历史同任务的上下文处理仍沿用既有流程，本项新增的范围核对用于明确类型切换和明确操作型追问。

## 独立预期的离线对照

`evaluations/intent_request_gold.json` 显式定义 63 条输入及请求类型、主题和执行决策预期。预期来自场景定义，没有由被测路由器生成。它包含知识解释、实际查数、诊断、建议、SOP、未知范围、复合任务、否定与对话反例；本轮用于开发与修正，不是独立保留集或生产流量准确率估计。

`python scripts/evaluate_intent_routing.py --report runtime/quality/issue2-5-routing-evaluation.json` 可重现当前对照。将 `a8a522c` 的 `app/` 用 WSL Git 导出到临时根后，通过 `--root <export-root>` 在独立进程读取旧实现；评估器核对实际导入来源，拒绝不存在或不一致的源码根，也拒绝空样例及重复 ID。

| 指标 | a8a522c | 本轮 |
| --- | ---: | ---: |
| 执行决策符合预期 | 39 / 63 | 63 / 63 |
| 非业务请求误路由到业务路径 | 13 | 0 |
| 应走业务路径但未进入 | 1 | 0 |
| 知识问题走了业务或无关澄清路径 | 19 / 25 | 0 / 25 |
| 请求类型、主题符合预期 | 无对应字段，不适用 | 各 63 / 63 |

上述“路径”是 Router 的决策，不等于基线实际调用了对应数据库；例如缺少制程时基线会错误澄清而不是执行 Tool。真实拒绝和持久化由下方链路测试另证。没有用这组分数估计模型计费、延迟或真实问答正确率。

## 验收

环境为 WSL `.venv-linux` Python 3.11.15、Windows `.venv-win` Python 3.13.5；浏览器和 Node 使用 Linux Node 22.22.2。原始日志与临时导出位于忽略的 `runtime/quality/issue2-5-*`，不提交数据库、日志、构建物或真实业务资料。

| 范围 | 命令与方法 | 结果 |
| --- | --- | --- |
| 修改前基线 | WSL `python -m unittest tests.test_intent_router tests.test_intent_runtime_boundaries tests.test_turn_decision` | 47 项通过；最初误用了不存在的 test_decision_arbiter 模块名，纠正后重跑并单独保留原日志 |
| 请求类型、仲裁、Tool 拒绝和具名 Planner | WSL `python -m unittest tests.test_intent_requests tests.test_intent_router tests.test_turn_decision tests.test_default_tool_assembly tests.test_named_planner_runtime` | 最后 79 项通过；包含扩写虚构设备/制程/批次、改变日期、低分、没有活动 Flow、错误语义提示、混合任务及被否定批次的实际计划参数 |
| 上下文与交付扩大检查 | WSL 隔离审计器指定路由、上下文、边界、交付、实际 HTTP 等 12 个模块/用例 | 范围补齐前 173 项，1 项既有 thinking_policy 失败，其他通过；不能称这批全绿 |
| 最后 WSL 验收 | 隔离审计器指定 `test_intent_requests`、具名 Planner、Router、turn_decision、默认 Tool、runtime_ports_portable、module_release 和新增 HTTP 用例 | 90 项通过，包括最终批次与范围约束、实际 HTTP/Session、仓库外制品安装与导入来源；与上行重叠，不相加计数 |
| 新增 HTTP 真实链路 | 隔离 TestClient、实际 run_agent / Coordinator / 路由 / Loop / Dispatcher、知识 Port 与模型传输离线替换 | Windows 单项通过，最后两平台各自的上述验收也覆盖；确认模型看到的工具集不含制造 Tool、轨迹没有制造调用、实际流式结果与提交后的 Session 新字段一致 |
| Windows 最终完整审计 | `python -X utf8 runtime/quality/persistence_audit.py . runtime/quality/issue2-5-windows-complete` 内部运行隔离 `unittest discover` | **1563 项，13 失败 / 10 错误 / 3 跳过**，测试 366.953 秒、含发现/装配审计 369.197 秒；与起点留存 1549 项审计的失败、错误和跳过 ID 集合逐项完全一致；仍非全绿 |
| 浏览器 | WSL `PLAYWRIGHT_PORT=28001 npm run test:e2e`，范围检查收口后用 28003 复核 | 两轮均 27/27。最后仅补批次范围/Planner 解析，与浏览器界面无直接变更，已由随后完整 Python 和 90 项实际链路覆盖 |
| Node | `node --test tests/*.test.js` | 65/65 |
| 离线评估 CLI | Windows / WSL `python scripts/evaluate_intent_routing.py --report <ignored-report>`；旧实现从独立 Git 导出根运行 | 当前两平台均 63/63，基线 39/63；源码根校验通过，无模型或数据源访问 |
| 仓库与边界 | WSL `python scripts/check_repository.py`（含两个边界检查器）、`git diff --check` | 通过，324 应用文件、边界 errors=0；不新增依赖债务或兼容消费记录 |
| Ruff | 全量 JSON 诊断按文件、规则和描述多重集与起点比较 | 428 → 427，无新增诊断；保留既有问题，不宣称全量 Ruff 通过 |

最终审计的 1563 项相对上一轮留存 1549 增加 14 项，其中 13 项属于本任务；另 1 项是上轮完整发现之后补充、已定向验证并随 a8a522c 提交的新布局参考集测试，本次首次纳入整套发现。没有把固定样例的 63 个数据行混算成 63 个 unittest 方法。

新增元数据与其导致的新计划 ID 是有意变化；旧制造流程、命名工具与实际参数由现有回归和新增反例检查。上述失败 ID 集合相同不等于旧快照逐字节相同，也不证明生产模型表现一致。本项没有重录原来已经失败的 DOM、OpenAPI 或旧模型消息快照。

### 初次失败及修正

首轮分类曾将带改善建议的当前生产问题转入通用知识，已根据真实操作目标修正；相反，报警代码“含义”与真实报警原因分别验证，避免只做“什么是”前缀优先。原 source-preference 单元测试改用真正的纯文档查询作为测试输入；带明确概念目标的输入现在直接按新契约走知识路径。

开发期首次 Windows 全量为 1560 项、17 失败 / 10 错误 / 3 跳过，其中新增差异来自两条尚未补齐的边界样例及新增 HTTP 对旧门面的三条消费记录。随后 HTTP 改用实际公开 run_agent 与原生知识 Port，未放宽边界清单；补齐请求范围和批次实际参数反例后重做最终完整审计。期间 1561 / 1562 项两轮为 12 失败 / 10 错误 / 3 跳过，proxy fixture 的旧失败当轮没有出现，但最终又出现；没有据临时消失宣称修复。初次记录、扩大检查的既有失败和最终结果均保留。

未重复整个 `run_quality_gate.py full`；本轮按阶段规则分别运行完整 Python、完整浏览器、Node、定向与仓库外验证。

本轮未运行真实模型、Live、公司接口、LDAP、性能门或新的覆盖率；远程 CI 结果另行核实，不因本地定向通过而宣称 full 全绿。MOD-025 草稿及其原有文档改动继续保留，未混入本任务实施范围。
