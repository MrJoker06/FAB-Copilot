# MOD-029c：辅助回读 Tool 与共享调用预算

日期：2026-11-15。起点 `12fb487`。本批实现辅助执行能力，实际聊天/后台接入和完整门仍归 029d/e；MOD-029 尚未完成。

## 实际改动

`agent_runtime/tools/result_access.py` 用同一个 ToolDefinition 声明 read_tool_result 的输入、输出、描述和版本，通过现有 ToolBinding/Registry/Dispatcher 执行。只可注册到本轮 Registry，显式拒绝全局 DEFAULT_TOOL_REGISTRY，不改变 21 项业务工具或 submit_analysis 的描述/Schema。

结果读取保留原 Session/来源/时间，使用宿主提供的主体、固定开关、允许阶段、截止和实时授权回调。独立调用存储类不等于模型获权；实际 Dispatcher 在执行前拒绝 viewer、主体不匹配、无授权、关闭、取消和截止。最后提交轮等硬停止由共享认领再次拒绝。

ToolLoopGuard 增加同步保护的辅助认领：与业务调用共享 total_calls，不增加每业务工具、重复签名、证据、无进展或停止原因；并发业务/回读只能用同一份总额度。辅助另限 4 次/16 KiB，失败引用查询也占用，输出按实际模型内容 UTF-8 字节计。每次认领只供一次 Handler，不能在一次合法调用后无预算反复直调。

输入校验在现有 Dispatcher 的认领前发生；格式/额外字段拒绝不开始读取、不消费实际工具执行次数，须由 029d 的有限模型请求协议限制重复非法请求。已认领后未知引用、无效游标、响应预算失败等均计尝试与返回字节。权限/参数/预算/内部存储失败分开返回既有 ToolError 类别，不将存储故障一律伪装成权限错误，不暴露内部异常文本。

## 验证

- Windows：`python -m unittest tests.test_result_read_tool tests.test_loop_guard tests.test_tool_dispatcher`，35 项通过（1.647 秒）；包括 9 项新辅助回读测试。
- WSL Python venv：`python -m unittest tests.test_result_read_tool tests.test_tool_dispatcher`，29 项通过（1.181 秒），含 jsonschema 校验真实 Handler 成功输出及拒绝响应。
- 反例覆盖关闭、阶段、角色/授权、取消、截止、最后轮、未知引用、参数/游标格式、辅助次数、共享剩余额度、并发认领和直接 Handler 无认领拒绝；真实 SQLite 快照来自旧 Run，同 Session 可读。
- 初轮夹具误用 create_execution_plan 参数顺序，修正后暴露并修正 Handler 的状态/ErrorKind 不匹配；两端失败记录保留，不将首轮写成通过。

Windows 加 module_release 共 44 项通过（15.875 秒）。Ruff、check_repository、两个边界检查器与 git diff --check 通过。尚未进行宿主模型协议、HTTP/SSE/页面、完整模型请求预算、Session 删除编排或浏览器验收；不将本批测试等同这些链路已接入。

当前受管源码 316（288 Python、28 静态），交付组 320 个成员；DB 候选仍 34，application_storage 仍为 12 文件。辅助模块已进入唯一文件归属，但尚未因有源码成员就宣称其完整运行 Profile 已验收，029e 按实际宿主依赖补齐交付。
