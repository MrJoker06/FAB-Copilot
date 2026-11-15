# MOD-029a：执行接缝与结果回读契约

日期：2026-11-15。起点 `3ac63b6`（仅文档提交，运行代码仍为 `c5312d1`）。所属方案：[MOD-029 v3.0](../tool-result-offloading-plan.md)。本报告固定实施契约，不代表快照、后台开关或回读功能已经实现。

## 1. 核对结论

| 实际符号 | 核对结果与实施决定 |
| --- | --- |
| `agent_runtime.service.run_agent` / `_run_agent_impl` | 外部接收 Session，但内部调用没有 Session 参数，目前只记日志。以宿主可信作用域传递 Session、主体及固定开关，不能从工具参数或用户消息推断所有者 |
| `AgentRunRequest` / `CoordinatorRunState` | 尚无 Session/结果访问状态。沿现有可注入依赖增加本轮访问接缝，不通过修改业务 Tool 参数传递 Session |
| `RuntimeContext` / Typed `AgentRun` | 主体和 Run 已类型化，Session 尚未表达；独立入口需显式绑定有效 Session，不绑定则仅有界预览并提示不可保存 |
| `loop_dispatch.execute_dispatched_loop_round` | 直接序列化成功的 result.data。必须换为有界模型视图，原 ToolResult、trace/observation 不改 |
| `loop_tool_round.execute_tool_round` | 使用 prompt_content。保留旧注入接缝，但视图也接入相同限制与提醒 |
| `synthesis.ready.ready_synthesis_messages` | 按行投影后嵌入 task JSON。实际任务包装后还需总字节检查，不只检查原 result |
| `request_ready_synthesis` / `request_synthesis_correction` | 当前只开放 submit_analysis。主综合/重试/修复要使用同一有限阶段预算，回读需要实际协议循环 |
| `loop_request.prepare_round_request` / `ToolLoopGuard` | 仅综合时拒绝所有业务调用。辅助读取需独立的实际认领入口，仍增加 total_calls，不增加业务工具/重复签名/证据/进展统计 |
| `api.services.chat` / `chat_stream` / `services.history` | 真实聊天由服务端读取 Session 历史；不能只依赖不可信 request.history 寻找旧引用。旧结果查看需显式目标选择和服务端核验 |
| `conversation.sessions` | 普通删除为归档，可恢复；permanent 及 bulk-delete 才清理。先持久删除意图，再结果库撤销/清理，最后完成 Session 删除 |
| `storage_identity_ports` / `bootstrap.storage_identity_assembly` | 已有显式存储/主体接缝，复用装配能力；新库不绑定 demo_data 或生产查询 |
| `api.routers.admin` / `api.schemas` / `static` | 使用现有 current_admin 及严格请求模型；持久开关与已保存值由后台真实 API/页面管理，不只增加环境变量 |

无新业务工具，原 21 项业务工具和 submit_analysis 的名称/描述/输入 Schema 不变。当前工具目录、已有纯模块及制品切片必须保留原基线对照。

## 2. 持久化契约

首期单个独立 SQLite 库，由宿主显式初始化；不在模块导入时建文件。库路径通过受信设置提供，与 agent/knowledge/demo 文件不同；不得将结果库误配置为既有部门库并写入，路径与普通文件边界须校验。

最小事实分组如下，表名为实施约定，可在代码审查时按消费者简化：

- `result_store_meta`：Schema 版本、持久游标签名密钥及全局开关；未配置开关为 true，显式 false 保留，读取错误不默认成功。
- `tool_result_snapshots`：随机引用、租户/所有者/Session/原 Run/调用身份、工具名、原来源、查询完成时间、对象/时间范围、格式版本、完整规范化结果、逻辑单元数、内容字节。归属及调用身份设唯一约束。
- `result_store_sessions`：结果库内 Session 撤销标记，防止迟到写入在删除后复活；结果发布与撤销使用同库事务序列化。
- agent 库的 `session_result_deletions`：租户/所有者/Session、持久待删除意图及进度。删除意图提交后对新聊天/读写设置门禁；不和结果库的字节计数重复维护。

正文只保存一份规范化 JSON，不同时持久复制每个分页单元；回读时从最多 4 MiB 的有界正文解析单元。初期接受这一读取成本，记录实测，不预建额外大对象/索引后端。内容与来源元信息均计入持久配额，SQLite 文件/索引/WAL 开销另记录。

发布事务使用 BEGIN IMMEDIATE：检查撤销和真实 Session、检查单次/Run/Session/总字节及数量、写入并提交；重复同一调用只返回已有已提交结果，但仍核验归属与 Session。技术重试内容不一致应拒绝，不能覆盖不可变快照。所有 SQL 为固定参数化语句。

游标采用绑定引用、格式、单元位置及片段位置的服务端签名编码；密钥保留在库内，不暴露到模型或日志。签名用于游标完整性，不是内容哈希或授权凭证，不新增 SHA-256 内容校验门。每页仍重新授权。

## 3. 分页及独立期望

输入字段：result_ref、可选 cursor、limit；不额外接受用户、Session、Run、路径、SQL 或过滤表达式。limit 默认 20、最多 50，布尔/非整数/小于 1/额外字段拒绝。cursor 至多 2048 字符，必须匹配原引用和有效位置。

快照支持 JSON 列表、字符串、字典及有限标量：列表单元为原记录；文本按保留分隔符的段落；字典按原键顺序表达 key/value 单元并标明根类型，不能拍平或丢键；标量单个单元。集合、非字符串对象键、NaN/Infinity 和任意对象明确拒绝，不 default=str。

正常页输出有效 JSON，携带 format/version、result_ref、原 tool/source_ref、queried_at、scope、unit_kind、units、total_units、next_cursor、has_more。限制作用于完整 JSON 序列化后的 UTF-8 字节，不能仅裁 units。超长单元才返回 unit_fragment，标明单元索引、字符范围及总长度；正常完整记录和不完整片段不能混称。

独立固定输入和期望保存于 [夹具](../../evaluations/mod_029_result_access_v1.json)：列表顺序、文本分隔符和字典 key/value 期望手写，不由分页实现生成。长字段由重复独立文字构造，重组必须严格等于规范化完整单元；超小响应额度须明确失败，不能返回无前进页。实际分页实现和上述用例的执行归 029b/c，不将本夹具存在称为通过。

## 4. 冻结起步额度与协议

本轮按用户“按照计划执行”指令采用 v3.0 已列出的候选初值作为实现起步配置：8 KiB 单视图、24 KiB 基础视图、4 KiB 单读取响应、每 Run 最多 4 次/合计 16 KiB 回读、40 KiB 基础及保留回读合计；4 MiB 单快照、16 MiB/16 份单 Run、64 MiB/128 份单 Session、1 GiB/4096 份总有效内容。后续若固定样例无法容纳必要元信息，应记录样例和影响再修订，不悄悄提高。

同一综合阶段最多 6 次实际请求，含重试/修复；主输出预算按当前普通 8192/DeepSeek Thinking Ready 32768，加最多一次 2048 修复，修复 10 秒以内且不超过阶段剩余时间。失败 usage 未知扣该次预留；所有调用使用阶段固定截止，不因分页重置。

共享调用认领与原业务 total_calls 使用同一事实。只有授权/阶段检查通过后才认领一次读取尝试，引用错误等实际读取失败也占用；硬预算拒绝不额外执行。读取不调用 record_result、begin_round/finish_round，不改变 stop_reason 或业务计数。取消、check_failed、硬限额、最后提交轮不得读取。

历史结果查看必须通过服务端绑定的同 Session 引用进入有限综合。前端/聊天请求可提供目标 result_ref，但它只作目标选择，宿主验证 Session/所有者、当前开关与原范围；不能以引用本身授权或信任 request.history。目标不明确则选择/澄清，不能搜索并注入全 Session 数据。普通历史页面加载无自动读取/模型调用。

## 5. 删除状态与线性化

归档不进入清理。永久删除先在 agent 库事务中记录 intent，再提交并释放会话写锁；不持有 agent 写事务等待结果库写锁。新的 Session 使用/结果访问先检查 intent。结果库事务先设置撤销再清内容，保证先发布则清掉、先撤销则迟到发布拒绝；完成后再在 agent 事务中删会话和完成 intent。

| 中断位置 | 可恢复结果 |
| --- | --- |
| intent 未提交 | Session/结果原样，调用未宣告成功 |
| intent 已提交，结果尚未撤销 | Session 删除中，不接受新使用；启动重放后撤销/清理 |
| 结果清理后，Session 尚未删除 | 结果已不可读，intent 重放完成 Session 删除，不伪装原快照仍在 |
| Session 删除后，回应丢失 | 重复请求按已完成记录/不存在处理，不能新建同 ID 或恢复旧结果 |
| 发布与清理并发 | 结果库序列化，迟到发布不能越过持久撤销标记；不依赖仅进程内锁 |

每次读取的授权/intent 检查确定访问线性化边界；删除无法撤回已发送内容。未开始或授权已撤销的读取拒绝，不把内部正文/连接信息写到公开错误。清理失败须可观察并可重试，批量逐项报告。逻辑释放与 SQLite 文件缩小分开验收，不无条件每次 VACUUM，不声称物理安全擦除或外部备份删除。

## 6. 基线验证与下一批

实际命令以平台解释器运行，日志位于忽略的 runtime/quality/mod-029a-*。Windows Python 3.13.5 与 Linux/WSL Python 3.11.15 分开记录，不能将缺依赖错误当作业务测试通过。

- Windows：persistence_module_boundaries、loop_guard、ready_result_policy、agent_synthesis_boundaries 共 40 项通过；evidence_truncation、storage_identity_ports、agent_runtime_boundaries 另 36 项通过。
- WSL 原 venv：前四模块发现 17 项，2 个模块导入错误为缺 PIL；记录保留，未安装/修改依赖。
- Linux Conda：前四模块加 evidence_truncation 共 51 项通过（Python 3.11.15）。本批为契约核对，未重跑完整门/浏览器/覆盖率/Live；历史 full 未通过。

本批 JSON 夹具语法/独立期望人工核对、UTF-8/LF/本地链接和 diff 检查通过；仓库边界结果以本批实际检查记录为准。

下一批为 029b：先实现独立结果库与结构分页/生命周期，不先改业务 Tool。029c/d 再接实际回读与后台/宿主协议；未接宿主前不能称为 MOD-029 完成。
