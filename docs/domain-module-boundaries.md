# 领域模块归属与退役边界

REF-035 将 `app/` 收敛为仅两个 Python 文件：`__init__.py`（包锚点）与 `main.py`（保持 `app.main:app` HTTP 入口）。业务实现位于领域目录；旧的 `app.agent`、`app.config`、`app.rag` 等 Python 导入路径已退役，不提供别名或转发模块。

| 领域 | 实现入口 |
|---|---|
| Core | `app.core.settings`、`app.core.identity` |
| Agent | `app.agent_runtime.service`、`app.agent_runtime.tools` |
| Memory | `app.memory_system`：上下文契约、解析、历史片段与用例 |
| Personal knowledge | `app.personal_knowledge_runtime.service` |
| Planning / intent | `app.planning_runtime`、`app.intent_runtime` |
| Manufacturing / persistence | `app.manufacturing`、`app.persistence` |
| Knowledge / evidence | `app.knowledge`、`app.evidence` |
| Model / telemetry / conversation | `app.model_gateway`、`app.telemetry`、`app.conversation` |

`python -m app.manufacturing.seed` 是唯一 seed CLI。配置模块使用 `Path(__file__).resolve().parents[2]`，因此迁移后仍定位同一项目根目录、环境文件和数据资源。

`evaluations/module_boundaries_v1.json` 锁定根目录仅有 `main`，并登记每个已退役模块到其 canonical 目标的映射。`scripts/check_module_boundaries.py` 同时拒绝物理重建和生产、脚本、测试中的绝对、相对、嵌套或字面量动态旧导入；普通字符串和冻结的 `MODULE:app.*` 显示标识不是导入，不会被改写。纯模块和跨领域依赖规则继续生效，`app.main`、协调器与服务入口仍是受保护的装配边界。

所有外部 Python 调用方必须迁移到表中 canonical 路径；Git 历史保留了已移除门面的可恢复记录。

Memory 抽离后，`app.conversation.context_resolver` 暂作为无业务实现的兼容转发，供既有测试与尚未迁移的约定调用方使用；应用生产模块不得重新依赖它。Session 的原始消息读写及归属校验仍在 `app.conversation.sessions`，API 通过 `HistoryReader` 端口在原有单次读取点访问，Memory 核心不导入 API、Agent、数据库或模型网关。
