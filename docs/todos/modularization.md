# 模块化工作包追踪

状态核对：2026-11-21，MOD-025 实施基线 `cc52529`。本表只维护未完成的模块化工作包，另计于产品任务；未完成共 7 项。

已完成工作包、原验收限制和依赖修订见[模块化归档](archive/modularization.md)及[完成索引](completed.md)。新方向的确认不自动改变 MOD 编号或既有验收结果。

MOD-029 已完成并移入[归档](archive/modularization.md#mod-029结果卸载与-session-级回读)，[实施报告](../reports/mod-029-tool-result-access.md)保留完整门既有失败；其他工作包未自动启动。

| 工作包 | 阶段 | 状态 | 依赖 | 当前验收证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `MOD-020`～`MOD-023` | P4 | 计划中 | P2 | Checkpoint、提交和恢复协议 | 按需求启用 |
| `MOD-026`～`MOD-028` | P5 | 计划中 | 对应稳定 Ports | 演示、Fake 集成与迁移评审；MOD-027 另承接 MOD-015 收尾时保留的 `run_agent` 兼容 facade、`TOOLS`/`TOOL_HANDLERS`、`compatibility` 装配边和 `core/settings.py` 配置锚点（台账 exit_task 已改为 MOD-027） | 保持原依赖，未自动启动 |

业务数据访问、量化小模型的受控查询约束及交付验收依据[解耦总方案](../architecture-modularization-master-plan.md)；[当前结构](../current-project-structure.md)说明实际模块归属。历史目录与分层不是不可调整的实现要求。
