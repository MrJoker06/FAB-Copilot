# 日志与运行监控 TODO

归档日期：2026-11-12。本文保留已完成任务的原定义、设计上下文和验收记录；旧目录、旧数量、阶段性“下一项”和未提交表述均为当时事实，不代表当前状态。未完成任务及可选候选以[当前清单](../observability.md)为准，当前实现以源码和报告为准。

## 已完成

- [x] `OBS-001` 为每次 Agent 请求生成独立 `run_id` 和请求关联标识。
- [x] `OBS-002` 记录模型调用、重试、工具调用、耗时、Token、状态和来源数量。
- [x] `OBS-003` 支持 metadata 和 full 两种日志内容模式。
- [x] `OBS-004` full 模式仍然强制脱敏凭据和认证字段。
- [x] `OBS-005` 在 AI 运营库保存 Agent Run、工具事件和回答来源。
- [x] `OBS-006` 管理端展示用户运行状态、最近运行、成功率、Token 和失败数量。
- [x] `OBS-007` 管理监控 API 受独立管理员认证保护。
- [x] `OBS-014` 对完整内容日志增加显式测试开关和自动到期治理；服务端在最终写入时复核 24 小时有时区到期窗口，监控与管理端展示安全策略状态及自动回退原因。
- [x] `OBS-015` 定位流式输出中途停滞的责任阶段，记录模型首 Token、相邻 Token 最大间隔、服务端 `answer_delta` 入队与 SSE 发送、浏览器读取、平滑缓冲积压和 Markdown 渲染耗时。诊断区分上游模型、服务端队列、网络/SSE 和浏览器主线程停顿；metadata 模式只保存聚合时延，不记录回答正文，并提供固定问题的复现实验报告。
- [x] `OBS-016` 区分 `status=success` 与 `outcome=degraded`，记录降级阶段、原因与 fallback；补齐 Session/消息持久化关联，监控上下文与首次回答 P50/P95，并兼容旧日志。普通 access 生命周期只写汇总日志、不建立 `req` 文件，流式错误仍保留独立记录；schema 升级为 1.3。
- [x] `OBS-017` 修正并扩展 Trace 语义：审计 schema 升级为 1.4，并以 `audit_schema_version` 与 `turn_decision_schema_version` 分字段保存，核心 envelope 字段不再可被组件覆盖；分别记录 `knowledge_source_count`、`tool_evidence_count`、`total_reference_count`，模型通用知识标记不计作知识来源。监控按 Run 暴露 context、routing、retrieval、tools、synthesis、stream 六阶段耗时及 P50/P95；DecisionArbiter 只记录受限候选枚举、来源、置信度、选中/拒绝状态和策略理由，不记录原始思维或凭据。旧 `schema_version`、`source_count` 和旧 TurnDecision 事件在读取时增量归一化，无数据库迁移。依赖：`AGENT-036`、`AGENT-038`。

## 历史任务记录

当前无非企业级可观测性待办；`QA-004` 已完成 Trace 的脱敏离线回放与跨层回归，`DEPLOY-012` 也已将该回归纳入受保护的远程质量门。

## 企业级暂缓
