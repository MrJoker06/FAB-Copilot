# 模块化工作包追踪

状态核对：2026-11-12，源码基线 `7859df9`。本表只维护未完成的模块化工作包，另计于产品任务；未完成共 9 项。

已完成工作包、原验收限制和依赖修订见[模块化归档](archive/modularization.md)及[完成索引](completed.md)。新方向的确认不自动改变 MOD 编号或既有验收结果。

MOD-029 单项更新：2026-11-15，方案基线 `c5312d1`；已实施 a～d，e 验收进行中，不改变其他工作包状态或既有验收。

| 工作包 | 阶段 | 状态 | 依赖 | 当前验收证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `MOD-020`～`MOD-023` | P4 | 计划中 | P2 | Checkpoint、提交和恢复协议 | 按需求启用 |
| `MOD-029` | P2/P5 | **029a～d 已实现，e 验收进行中** | MOD-030/031 已完成；不等待完整恢复链 | [v3.0](../tool-result-offloading-plan.md)、[029a](../reports/mod-029a-result-access-contract.md)、[029b](../reports/mod-029b-result-store.md)：[实施报告](../reports/mod-029-tool-result-access.md)：已接入聊天/后台/Session 清理，完整门尚待收尾 | 继续完整阶段门与基线对照；不自动开始 MOD-025 |
| `MOD-025`～`MOD-028` | P5 | 计划中 | 对应稳定 Ports | 交付制品、演示、Fake 集成与迁移评审；MOD-027 另承接 MOD-015 收尾时保留的 `run_agent` 兼容 facade、`TOOLS`/`TOOL_HANDLERS`、`compatibility` 装配边和 `core/settings.py` 配置锚点（台账 exit_task 已改为 MOD-027） | 与里程碑交错执行 |

业务数据访问、量化小模型的受控查询约束及交付验收依据[解耦总方案](../architecture-modularization-master-plan.md)；[当前结构](../current-project-structure.md)说明实际模块归属。历史目录与分层不是不可调整的实现要求。
