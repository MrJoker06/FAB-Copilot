# 连续对话上下文设计

## 目标

连续对话不能依赖“那么、继续、详细一点”等短语枚举。语言表达无法穷举，固定补丁既会漏掉新说法，也可能把独立问题错误绑定到旧主题。

当前 Agent Loop 使用以下顺序：

1. 从 Session 读取最近 20 条消息。
2. 对“第 N 项、最后一项”这类结构明确的界面选择做确定性解析。
3. 有历史消息的自由文本进入独立 `contextualization` 模型阶段，由模型判断是独立任务、追问、纠正还是回忆；没有历史且已能完整路由的首轮任务直接进入主循环，首轮未知问题仍使用语义阶段辅助分类。
4. 模型通过 JSON 响应契约返回结构化关系、完整问题、主题锚点、置信度和受限的意图提示。
5. 只有置信度不低于 0.65 的追问、纠正或回忆才允许改写当前问题；有效但不足以绑定的非独立结果标记为 `ambiguous`，才可请求用户选择历史消息。
6. `DecisionArbiter` 是最终路由的唯一决策点：原始用户文本决定言语行为和显式新任务，`resolved_question` 只为已确认目标补全参数；Router、TurnDecision 不得在仲裁后静默改写任务类型。
7. 仲裁从上一条可信 assistant metadata 的受限 `turn_decision.active_flow` 恢复 `meta:<subject>` 或 `task:<intent>`；旧 Session 或非法字段安全退化为无活动 Flow，绝不从聊天正文猜测。高置信度 followup/correction 的合法 `answer_meta` 可在活动元对话 Flow 中阻止扩写新增的“文档/知识库/规范”启动 SOP；原始文本明确的良率、设备、批次、制程和 SOP 新任务始终优先切换 Flow。
8. 对话路由会构建受限的 `TurnDecision.actions[]`；它只决定回答、澄清、回忆或交给既有任务路由，不包含工具、SQL 或自由参数。`selected_origin`、`policy_reason` 与脱敏候选摘要用于审计，不保存原始问题、扩写文本或模型 reasoning。制造任务仍由既有 Planner 决定具体取证步骤。

```text
Session history + current turn
            |
            v
  Contextualization node
  standalone | followup | correction | recall
            |
            v
 DecisionArbiter -> Intent Router -> Planner -> Agent Tool Loop -> Validator -> Answer
```

## 结构化契约

上下文阶段只返回以下数据，不负责回答问题，也不产生制造事实：

```json
{
  "relation": "standalone | followup | correction | recall",
  "resolved_question": "可独立理解并进入路由的完整问题",
  "topic_anchor": "本轮引用的历史主题；独立问题为空",
  "target_message_ids": [],
  "confidence": 0.0,
  "intent_hint": "conversation | general_knowledge | manufacturing_analysis | unclear",
  "turn_actions": [{"type": "answer_meta", "subject": "capabilities", "detail": "detailed"}]
}
```

`standalone` 不改写输入。`followup` 补全省略对象或动作，`correction` 应用用户最新修改并移除被否定要求。`recall` 必须通过 `target_message_ids` 选择当前用户有权读取的原始 Session 消息；服务端再读取对应用户消息和配对助手消息，不能使用模型生成的 `topic_anchor` 伪造历史。当用户要求“更前面的一个”时，由上下文模型在可见消息 ID 中选择更早的目标，而不是依赖固定短语补丁。

`conversation` 表示助手身份、能力、问候以及不请求外部技术或制造事实的交互或元问题。当确定性 Router 返回 `unknown` 时，置信度不低于 0.65 的 `conversation` 提示可进入确定性的零工具助手对话路径；其检索判定为 `NOT_APPLICABLE`，不会附加知识库为空的披露。相同条件下，`general_knowledge` 提示可以进入通用知识检索路径。对于模型已高置信度判定为追问或纠正的消息，同一通用知识提示也可以修正仅因“知识库”等来源措辞形成的 `sop_lookup` 路由；模型判定为 `standalone` 时不应用该修正。`manufacturing_analysis` 和 `unclear` 仍保留原路由或澄清要求；两类语义提示都不能覆盖良率、设备、批次等制造意图，也不能直接触发制造数据工具。

`turn_actions` 是可选扩展，旧 Provider payload 不含它仍兼容。v1 最多三个动作且最多一个主要动作；`acknowledge` 可与主要动作组合。`answer_meta` 仅使用身份、能力、使用方式、限制、运行状态、回答复盘、社交和其他主题；`route_task` 只能指向既有非对话路由。动作字段非法时仅丢弃动作并安全澄清，不会破坏已经成功恢复的 `resolved_question`。能力回答读取受实现映射测试约束的目录，普通用户不会看到管理员模型治理能力；模拟数据、Thinking 和多模态都按已验证运行状态描述。

`DecisionArbiter` 的候选只保留路由/动作枚举、来源（`original_text`、`history`、`model_expansion`、`semantic_context`）、置信度、选中状态和原因码。候选冲突按显式策略选择；低置信度或无可靠绑定时保守澄清。它不使用追问短语词典，不引入 Rasa/LangGraph，也不改变现有 Planner、Playbook 或 Evidence 架构。

## 上下文窗口

- 最多读取最近 20 条 Session 消息。
- 用户消息最多保留 1000 字符，助手消息最多保留 1600 字符。
- 上下文阶段总历史预算为 16000 字符，从最新消息向前保留。
- 用户 Thinking 只用于后续主推理/答案循环；结构化上下文分类无条件关闭 Thinking，但仍审计用户是否请求过它。
- 上下文分类首轮输出预算为 1200 token；若只返回推理流而没有最终 JSON，唯一一次协议纠正重试提升到 2400 token。`MODEL_CONTEXT_TIMEOUT_MS` 默认 15000 ms（边界 1000-60000 ms），是跨协议纠正和网络重试的总阶段 deadline；到期立即保守降级。
- 当前实现不把旧消息重复写回 Session，完整历史仍由会话数据库持久化。
- 上下文输入给每条历史消息附带真实 `message_id`；无持久化 ID 的单元测试或兼容调用使用窗口内临时 ID。
- 后续当单会话显著增长时，应增加滚动摘要或 compaction，而不是继续扩大原始消息窗口。

## 失败与安全边界

- `recall` 返回的消息 ID 必须存在于当前租户、当前用户已经读取的 Session 历史窗口内，否则拒绝绑定历史。
- 上下文协议接受单层 `json` 代码围栏并忽略不影响契约的额外字段，但必需字段、字段类型、枚举、置信度范围和消息 ID 仍严格校验。协议错误只执行一次带原因码的纠正重试，不消耗或继承主模型更大的网络重试预算。
- 上下文状态分为 `not_applicable`、`resolved`、`ambiguous` 与 `unavailable`。超时、网络、协议和熔断均为 `unavailable`：它不证明用户引用了历史，系统必须保留原始问题并按直接路由处理；仍无法理解时只给出中性当前意图澄清。只有模型成功返回有效、非独立但不足以绑定的 `ambiguous` 才列出历史候选。当前问题本身已经明确为制造任务时，始终保持当前独立任务。
- 上下文分类器使用 `response_format=json_object`，不占用 Agent 工具协议；制造工具和知识工具仍只由后续主循环调用。
- 上下文阶段不得调用制造数据或知识库工具。
- 来源偏好是上下文条件，不单独决定回答意图；模型需要同时保留上一轮尚未完成的信息目标。系统不通过关键词强制继承历史，明确的新问题应返回 `standalone`。
- `resolved_question` 不是证据，后续制造事实仍必须经过正常工具与 Evidence Validator。
- 日志记录关系、`resolution_state`、置信度、耗时、Token、阶段和 Thinking requested/effective 策略。成功送达但上下文不可用的 Run 保持 `status=success`，同时记录 `outcome=degraded`、降级阶段、原因和回退动作；监控聚合降级 Run 与上下文超时。普通 API 访问事件仅写入轮转汇总日志，不建立独立 `req-*.jsonl` 文件。metadata 模式中的协议错误只记录原因码、响应长度、内容指纹、结束原因和推理字符数；系统不保存 `reasoning_content` 正文。仅测试用 full 模式保存最终响应内容，日志不记录或展示隐藏思维链。

## 制造运营概览边界

Router 将带有运营审视动作且能解析出整厂或具体制程范围的问题交给制造综合诊断 Playbook。该规则适用于全部制程族及其别名，不依赖某个站点或固定问句；具体制程会下推到能力、设备健康、设备效率、缺陷和异常报表，避免回答混入其他站点数据。制程级回答可以引用整厂良率与周期作为背景，但不得将其表述为该制程自身指标。明确的良率、设备故障、缺陷、批次追踪和 SOP 请求仍由专用意图处理，原理介绍等通用知识问题不会因出现制程名称而进入生产分析。

制造范围解析结果独立记录为 `scope_resolution`，区分整厂、制程、设备、产品、未知范围和非制造问题。问题含有明确但无法映射的范围标识时不得回退到整厂；Planner 必须先返回范围澄清且工具预算为零。无范围限定的“最近生产状况”仍可视为整厂请求。未知缩写只有在受治理目录中建立映射后才能作为已解析范围使用，模型猜测不能创建或替代该映射。

执行计划进一步生成 `scope_contract`。每个步骤标记为 `primary` 或 `context_only`；制程级问题中的整厂总览和整厂良率只能作为背景。设备级问题必须把设备编号下推到健康、生产率、近期异常和传感器工具。Answer Contract 保存每个来源的范围角色并要求结论提交证据引用；主范围声明没有主范围证据，或只引用背景工具时，由服务端降级为待验证假设。产品级综合诊断在全部必需工具具备一致产品过滤能力前不得执行。

## 参考实现

- [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/)：每次运行前合并 Session 历史和新输入，并支持限制历史、输入过滤与长会话压缩。
- [LangGraph Memory](https://langchain-ai.github.io/langgraph/how-tos/memory/manage-conversation-history/)：将短期消息作为线程状态，并提供裁剪、删除和摘要策略。
- [LangGraph Repository](https://github.com/langchain-ai/langgraph) 与 [OpenAI Agents SDK Repository](https://github.com/openai/openai-agents-python)：两者均为千星以上的主流开源 Agent 项目。
