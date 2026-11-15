# MOD-029b：独立结果存储与结构分页

日期：2026-11-15。起点 `983ac38`，运行代码基线 `c5312d1`。本批交付存储层；MOD-029 整体未完成。

## 实际实现

- `app/core/tool_result_units.py`：严格有限 JSON 值、原序记录/保留分隔符的段落/字典键值单元、完整单元优先分页；超长单元转为明确片段，按完整响应 UTF-8 字节检查，确保游标前进。
- `app/persistence/tool_result_store.py`：显式初始化独立库；事务内不可变发布、幂等调用身份、单结果/Run/Session/全库字节与数量配额；主体/Session 归属与实时许可回调；持久随机引用及 HMAC-SHA-512 游标，重启后可继续分页。签名只防游标篡改，不是内容校验门，也不是访问授权。
- 删除核心：同库事务持久撤销 Session 并清理正文，迟到写入拒绝；并发发布先提交则被清理、撤销先提交则拒绝。Run 生命周期不删除提交结果。
- 开关值可持久保存，默认 true；存储类本身是可信内部 API，实际 Run 固定开关、Tool 授权、阶段和读取预算由后续宿主接入负责，不能将存储方法可调用当成模型已获权限。
- application_storage Profile 加入上述两文件，10 → 12；其余三 Profile 不扩张。受管源码 315（287 Python、28 静态），交付成员 319，四 Profile 源码并集 162/含资源 166，DB 候选 34。

初始化拒绝不相关既有库；普通读写在未初始化时不创建文件。检查现存符号链接/reparse point，完整路径替换/宿主路径配置及受信目录保证仍需在宿主接入验收，不以当前检查宣称解决所有文件系统竞态。内容超配额失败不驱逐已有 Session。

Session 永久删除的 agent 库持久意图、当前会话存在性验证和重启补偿编排，尚未接入；本批只交付结果库的撤销/清理原语。后台 HTTP/页面、实际聊天 Run 和辅助 Tool 同样尚未接入，下一批须完成，不能将本批称为默认应用已开始卸载或永久删除已联动。

## 验证与限制

`tests.test_tool_result_store` 新增 15 项：两端实际 SQLite 保存/重启；手写夹具的记录/段落/对象；超长中英文重组；全响应大小；全部层级配额且不驱逐；并发容量认领；同调用幂等/冲突；跨归属/实时拒绝；游标篡改/挪用；持久开关；初始化/既有库拒绝；有限 JSON 拒绝；真实触发器中止回滚与不兼容 Schema；并发删除发布；符号链接拒绝。

| 命令/范围 | 实际结果 |
| --- | --- |
| Windows `.venv-win/Scripts/python.exe -m unittest tests.test_tool_result_store` | 15/15，0.531 秒，无跳过 |
| WSL venv `python -m unittest tests.test_tool_result_store` | 15/15，0.658 秒，无跳过 |
| Windows 存储 + module_release + persistence_separation | 首轮新增反例前 27 项通过，17.932 秒；后新增 3 项另跑通过，未重跑同一批全量 |
| Ruff 新增两模块/测试 | format/check 通过；初轮发现未用 sqlite3 导入，已删除后通过 |

真实 MOD-024 Profile 测试在仓库外新 venv、隔离解释器中保存/重开/回读/撤销结果，同时检查未安装 demo_data，并继续验证原应用状态。Linux 同组合 27 项通过，102.857 秒；后追加 3 项另跑通过。check_repository、两个边界检查器及 git diff --check 通过，files=315 errors=0；相关 Markdown 编码/LF/本地链接检查通过。原始日志位于忽略的 runtime/quality/mod-029b-*。

未运行完整门、浏览器、真实性能、Live 或公司接口；旧 full 失败仍保留。本批没有业务数据库搬迁，不改变工具 Schema、业务证据、默认模型工具清单或既有 SQL 口径。
