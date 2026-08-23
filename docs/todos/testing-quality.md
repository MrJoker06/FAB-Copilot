# 测试质量 TODO

## 已完成

- [x] `QA-001` 建立可重复的 quick/full 本地质量门：根目录 unittest discovery 不再假绿，上传幂等重放固定返回首次 attempt=1，补齐版本、企业数据、能力报表、RAG 搜索和管理监控 HTTP 契约；full 使用 app 分支覆盖率下限，且 Node、静态 JS 与 RAG 黄金集均纳入门禁。详见[测试策略](../testing-strategy.md)。
- [x] `QA-002` 按数据报表、知识上传、HTTP/企业契约、模型治理、会话流式五个领域拆分 54 个系统测试。每个模块在独立进程中以 SQLite backup 创建部门参考库的临时一致快照并清理；full 先覆盖非系统测试，再逐模块 coverage append。2026-08-02 首次宿主完整门实测数据报表 16.5 秒、HTTP/企业契约 23.0 秒、知识上传 15.5 秒、模型治理 16.7 秒、会话流式 19.1 秒，总计 90.7 秒；据此将模块告警/失败预算校准为 45/75、60/90、45/75、45/75、50/80 秒，总计 180/300 秒，报告写入 `runtime/quality/system_test_timings.json`。
- [x] `QA-003` 为 `run.sh`、数据库迁移/备份、运行时清理和流式 smoke 脚本增加离线契约及风险分支测试：启动验证使用临时 Git 仓库和假 Conda，不启动 uvicorn、模型或网络；数据库备份只读读取并以 staging 原子发布，失败清理半成品；运行时删除严格校验根目录、实例 ID 和符号链接；流式 smoke 通过可注入 transport 验证 NDJSON 协议与失败输出。

## 当前产品待办

- [x] `QA-004` 建立 `synthetic_redacted` 脱敏离线 Trace 回放与黄金矩阵：7 个 case 覆盖通用问题、CMP 制程能力、整厂综合三条真实请求链路，文档/知识库/规范三种 Router 失败扩写和显式 SOP 反例；跨层断言 TurnDecision、路由、计划、主/背景范围、严格工具路径、证据强度、结构化提交、答案增量与 Session 持久化。CMP 与整厂 case 分别声明禁止的主范围或主工具，ready case 的业务调用次数必须等于 `planned_tool_calls`，模型业务工具选择固定为 0；数据集拒绝凭据和隐藏推理字段，回放器与正常 quick/full 质量门的真实 LLM、网络调用均为 0。依赖：`AGENT-036`、`AGENT-037`、`AGENT-038`、`OBS-017`。
