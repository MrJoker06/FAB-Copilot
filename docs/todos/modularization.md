# 模块化工作包追踪

状态核对：2026-11-12，源码基线 `7859df9`。本表只维护未完成的模块化工作包，另计于产品任务；未完成共 9 项。

已完成工作包、原验收限制和依赖修订见[模块化归档](archive/modularization.md)及[完成索引](completed.md)。新方向的确认不自动改变 MOD 编号或既有验收结果。

| 工作包 | 阶段 | 状态 | 依赖 | 当前验收证据 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| `MOD-020`～`MOD-023` | P4 | 计划中 | P2 | Checkpoint、提交和恢复协议 | 按需求启用 |
| `MOD-029` | P2/P5 | **重审稿 v2.0 待审核，未实施** | MOD-030/031 已完成；不等待完整恢复链 | [重审稿](../tool-result-offloading-plan.md)以 7859df9 为源码基线，明确辅助回读、共享额度、视图预算及生命周期；029a～e 均未实施 | 审核方案及候选额度，获准后排在 MOD-025 前实施 |
| `MOD-025`～`MOD-028` | P5 | 计划中 | 对应稳定 Ports | 交付制品、演示、Fake 集成与迁移评审；MOD-027 另承接 MOD-015 收尾时保留的 `run_agent` 兼容 facade、`TOOLS`/`TOOL_HANDLERS`、`compatibility` 装配边和 `core/settings.py` 配置锚点（台账 exit_task 已改为 MOD-027） | 与里程碑交错执行 |

业务数据访问、量化小模型的受控查询约束及交付验收依据[解耦总方案](../architecture-modularization-master-plan.md)；[当前结构](../current-project-structure.md)说明实际模块归属。历史目录与分层不是不可调整的实现要求。
