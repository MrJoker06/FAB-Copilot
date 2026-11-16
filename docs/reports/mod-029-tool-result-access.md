# MOD-029：Session 级结果卸载与受控回读

日期：2026-11-15～16。源码起点 `c5312d1`，方案提交 `3ac63b6`，分支 `experiment/parallel-platform`。依据 [v3.0 方案](../tool-result-offloading-plan.md)，承接 [029a](mod-029a-result-access-contract.md)、[029b](mod-029b-result-store.md)、[029c](mod-029c-result-read-tool.md)。

**状态：029d 接入已实现，029e 阶段验收进行中，尚未整体完成。** 完整门和基线对照待最终收尾，定向通过不代表全绿。

## 实际实现

| 归属 | 实际行为 |
| --- | --- |
| `persistence.tool_result_store` | 独立 SQLite 快照、事务容量认领、不可变引用、结构分页、持久 Session 撤销；默认开启设置保存在结果库 |
| `bootstrap.result_access_assembly` / `agent_runtime.result_access_run` | 可信主体、Session、Run、开关快照、实时许可和资源关闭；正常 Run 结束保留已提交快照 |
| Ready/Loop、Typed/Skill | 原始采用结果与模型视图分开；显式分派绑定携带同一访问状态。无 Session 不保存，但仍有界展示；不新增默认 Skill 发布 |
| `conversation.result_lifecycle` | 持久删除意图 → 本进程在途取消 → 结果库撤销/清理 → 主库永久删除。失败保持待清理，启动幂等恢复，不声称跨库原子事务 |
| 管理端、聊天页面、HTTP/NDJSON | 管理员严格布尔开关，刷新恢复；关闭截断与成功卸载分别提醒；消息元数据保存引用/时间，恢复后可查看和翻页 |

`read_tool_result` 是运行内辅助能力，未加入默认 21 项业务工具与 `submit_analysis` 定义。只接受不透明引用、受控游标和页大小，不接受 SQL、路径、自由搜索。关闭只作用于新 Run，已有结果保留，重新开启可授权读取。

旧结果由用户选择具体引用进入 `snapshot_review`：只展示该快照一页及原时间/范围，明确未重新查询来源；不调用模型、不产生新业务证据。不猜目标，不扫描全部 Session 结果。保存、回读及后续模型请求复查权限和删除意图；不能撤回已发送字节。跨进程和迟到回调由持久记录及结果库事务拦截，本地取消不是唯一保证。

## 额度和兼容

- 单结果视图 8 KiB，基础派生上下文 24 KiB，单页 4 KiB，保留回读合计 16 KiB，总派生视图 40 KiB。JSON 外层、引用和转义计入；HTTP 在聊天模板处理后的实际边界检查，不切断 JSON 协议。
- 最多回读 4 次，与业务共享 Guard 剩余额度，解析失败也计数；不增加业务次数、观察、来源或进展。Ready 完成和允许的综合停止原因可读，硬限额、最后轮、撤销、取消、截止和 `check_failed` 不开放回读。
- 综合最多 6 次实际请求，重试/修复共享固定截止及输出预算。普通主综合 8192、Ready Thinking 原特例 32768，另最多 2048 修复额度。未知 usage 保守扣预留；Typed `ModelRequest.max_output_tokens` 为可选上限，接入的 Model Port 必须执行，全零旧 usage 也保守扣预留。
- 保留单份 4 MiB、Run 16 MiB/16 份、Session 64 MiB/128 份、全库 1 GiB/4096 份；不足时不静默驱逐其他 Session。

默认结果库位于 `FAB_DATABASE_DIR/tool_results.db`，宿主可设置 `FAB_TOOL_RESULT_DATABASE_PATH`；拒绝应用库别名及已有符号链接/reparse point。应用状态 Schema 16 新增持久删除意图表。导入不建库，宿主显式初始化。没有修改业务证据规则、默认工具输入 Schema，没有恢复任意 SQL、实现完整恢复链或 LDAP。

## 已取得的验收证据

环境：Windows `.venv-win` Python 3.13.5；WSL 新 `.venv-linux` Python 3.11.15，复用既有 Conda 依赖并在新 venv 安装项目已声明的 jsonschema。旧 venv 缺 Pillow、原 Conda 缺 jsonschema 的失败保留；未修改原 Conda 环境。

| 命令/范围 | 实际结果 |
| --- | --- |
| 两端 `python -m unittest tests.test_tool_result_store tests.test_result_read_tool tests.test_session_result_lifecycle tests.test_result_access_runtime tests.test_simulation_profile` | 当轮各 49 项通过；后追加 Typed 默认入口及实际 Ready 完成读取反例另验，不算入该轮数量 |
| 两端 `python -m unittest tests.test_module_release_install tests.test_persistence_separation` | 当轮各 8 项通过，真实构建并在仓库外 venv 安装；最终绑定修正后需复验 |
| WSL Node 22.22.2 `npm run test:e2e` | 19/19，含新开关持久化、恢复快照分页及既有功能/无障碍/视觉；未更新截图 |
| 两端实际 `python -m uvicorn app.main:app` | 临时库上 health=`ok`，受认证设置接口 `enabled=true`，结果库实际创建；已停止测试进程 |

原始日志、导出树、机器报告放入忽略的 `runtime/quality/`，不提交数据、凭据或构建产物。

## 空间及效果样例

合成 30 条中英文记录共 72,741 字节，模型视图 8,192 字节，四次读取各 2,930 字节，增加共享调用 4 次、业务调用 0 次、模型调用 0 次。单次保存/预览 Windows 约 8.718 ms，WSL 约 9.527 ms；这是离线观察，不是 p95、真实模型质量或生产 SLO。

两端文件均为 106,496 字节；删除使快照数从 1 降至 0，17 页进入 freelist，文件不立即缩小；新 Session 同量写入复用空闲页，文件未增长。空闲临时库显式 `VACUUM` 后为 36,864 字节。实际策略为复用空间，需缩小时在维护窗口停止写入/关闭连接后压缩，不逐次删除执行 VACUUM，不承诺安全擦除、备份或原来源删除；小型撤销/意图记录保留以阻止迟到写入。

## 验收修正及待收尾

已修正二次 JSON 空格造成超界、Typed 外部分派绕过 facade 导致访问状态丢失、真实 Ready 停止原因不在读取许可中，以及 Schema/源码切片断言过期。保留历史小结果协议，未重生成业务 Golden 或放宽阈值。

首轮基线导出缺少被忽略的参考库，该轮环境失败无效；已补齐同源只读 SQLite backup 重做比较。完整门仍有既有失败，最终状态须以修正后完整审计与基线子集对照填写。尚需最终切片复验、Ruff 无新增、工具契约/台账及 UTF-8/LF 检查。

未运行真实模型、公司来源、远程 Live 或 LDAP。路径测试不扩大宣称为抵御具有宿主目录写权限者的一切替换攻击；快照测试也不证明模型分析质量提升。
