# 日志与运行监控 TODO

## 已完成

- [x] `OBS-001` 为每次 Agent 请求生成独立 `run_id` 和请求关联标识。
- [x] `OBS-002` 记录模型调用、重试、工具调用、耗时、Token、状态和来源数量。
- [x] `OBS-003` 支持 metadata 和 full 两种日志内容模式。
- [x] `OBS-004` full 模式仍然强制脱敏凭据和认证字段。
- [x] `OBS-005` 在 AI 运营库保存 Agent Run、工具事件和回答来源。
- [x] `OBS-006` 管理端展示用户运行状态、最近运行、成功率、Token 和失败数量。
- [x] `OBS-007` 管理监控 API 受独立管理员认证保护。
- [x] `OBS-015` 定位流式输出中途停滞的责任阶段，记录模型首 Token、相邻 Token 最大间隔、服务端 `answer_delta` 入队与 SSE 发送、浏览器读取、平滑缓冲积压和 Markdown 渲染耗时。诊断区分上游模型、服务端队列、网络/SSE 和浏览器主线程停顿；metadata 模式只保存聚合时延，不记录回答正文，并提供固定问题的复现实验报告。

## 当前队列

- [ ] `OBS-014` 对完整内容日志增加显式测试开关和自动到期治理。

## 企业级暂缓

- [ ] `OBS-008` 使用 Redis 或事件流聚合多实例实时运行状态。
- [ ] `OBS-009` 接入 OpenTelemetry Trace、Metric 和 Log，并统一关联 request_id、run_id 和 session_id。
- [ ] `OBS-010` 将日志发送到 Loki、ELK 或 OpenTelemetry Collector。
- [ ] `OBS-011` 建立模型错误率、工具错误率、延迟、Token 和成本告警。
- [ ] `OBS-012` 建立日志保留、归档、删除和访问审计策略。
- [ ] `OBS-013` 增加租户级、模型级、工具级和 Playbook 级运行报表。
