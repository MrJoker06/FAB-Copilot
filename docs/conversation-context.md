# 连续对话上下文设计

## 目标

连续对话不能依赖“那么、继续、详细一点”等短语枚举。语言表达无法穷举，固定补丁既会漏掉新说法，也可能把独立问题错误绑定到旧主题。

当前 Agent Loop 使用以下顺序：

1. 从 Session 读取最近 20 条消息。
2. 对“第 N 项、最后一项”这类结构明确的界面选择做确定性解析。
3. 未知、歧义、通用知识或仍缺少必要范围的消息进入独立 `contextualization` 模型阶段；已经能完整路由的制造任务直接进入主循环。
4. 模型通过 JSON 响应契约返回结构化关系、完整问题、主题锚点、置信度和受限的意图提示。
5. 只有置信度不低于 0.65 的追问、纠正或回忆才允许改写当前问题。
6. 完整问题再进入 Intent Router、Playbook、Planner、工具循环和证据校验。

```text
Session history + current turn
            |
            v
  Contextualization node
  standalone | followup | correction | recall
            |
            v
 Intent Router -> Planner -> Agent Tool Loop -> Validator -> Answer
```

## 结构化契约

上下文阶段只返回以下数据，不负责回答问题，也不产生制造事实：

```json
{
  "relation": "standalone | followup | correction | recall",
  "resolved_question": "可独立理解并进入路由的完整问题",
  "topic_anchor": "本轮引用的历史主题；独立问题为空",
  "confidence": 0.0,
  "intent_hint": "general_knowledge | manufacturing_analysis | unclear"
}
```

`standalone` 不改写输入。`followup` 补全省略对象或动作，`correction` 应用用户最新修改并移除被否定要求，`recall` 只恢复用户要求回忆的历史内容。

当确定性 Router 返回 `unknown` 时，只有置信度不低于 0.65 的 `general_knowledge` 提示可以进入通用知识检索路径。`manufacturing_analysis` 和 `unclear` 仍保留澄清要求，模型提示不能直接触发制造数据工具。

## 上下文窗口

- 最多读取最近 20 条 Session 消息。
- 用户消息最多保留 1000 字符，助手消息最多保留 1600 字符。
- 上下文阶段总历史预算为 16000 字符，从最新消息向前保留。
- 当前实现不把旧消息重复写回 Session，完整历史仍由会话数据库持久化。
- 后续当单会话显著增长时，应增加滚动摘要或 compaction，而不是继续扩大原始消息窗口。

## 失败与安全边界

- 模型未返回合法 JSON 对象时，在现有模型重试上限内重试；仍失败、字段类型非法、关系类型非法或置信度过低时，不绑定历史，按当前输入独立路由。
- 上下文分类器使用 `response_format=json_object`，不占用 Agent 工具协议；制造工具和知识工具仍只由后续主循环调用。
- 上下文阶段不得调用制造数据或知识库工具。
- `resolved_question` 不是证据，后续制造事实仍必须经过正常工具与 Evidence Validator。
- 日志记录关系、置信度、耗时、Token 和结构化结果；不记录或展示隐藏思维链。

## 参考实现

- [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/)：每次运行前合并 Session 历史和新输入，并支持限制历史、输入过滤与长会话压缩。
- [LangGraph Memory](https://langchain-ai.github.io/langgraph/how-tos/memory/manage-conversation-history/)：将短期消息作为线程状态，并提供裁剪、删除和摘要策略。
- [LangGraph Repository](https://github.com/langchain-ai/langgraph) 与 [OpenAI Agents SDK Repository](https://github.com/openai/openai-agents-python)：两者均为千星以上的主流开源 Agent 项目。
