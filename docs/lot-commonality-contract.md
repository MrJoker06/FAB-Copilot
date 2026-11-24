# Lot 相关性分析 · B1 数据与契约

状态为待前后端共同签收。基线是 `feat/pe-ee-duty-workspace` 的 `4711c13`。依据是[后端计划](lot-commonality-backend-plan.md)第 1～4 节和[前端计划](lot-commonality-frontend-plan.md)第 2～3 节。本文冻结 B1 的字段、统计口径和样例。F1/F2 与 B2/B3 按本文并行实现，路径和符号可在 B3 中按现有代码调整，字段语义与样例不随实现改写。

样例和夹具：

- [合成来源事实](../tests/fixtures/lot_commonality/source_passes.json)：10 个 lot、33 次过站，人工规定，对应后端计划第 4 节。
- [请求／响应样例](../tests/fixtures/lot_commonality/contract_examples.json)：创建、回读、成员、分页、履历明细与错误。计数和成员是人工预期，履历明细是来源事实的原样投影。
- [样例核对测试](../tests/test_lot_commonality_contract.py)：核对样例与计划预期、计数守恒、证据可回查和排序规则一致。它不实现聚合，B2 的实现须另以这两份夹具为输入通过断言。

修改夹具须说明原因并独立审阅，不得用被测实现生成或改写预期。

## 1. 数据条件核实结论

| 来源 | 同次加工分到多个腔 | 各腔片数／wafer | 返工后再次上机 | 结论 |
| --- | --- | --- | --- | --- |
| 本地模拟库 `process_runs` | 不能表示。`UNIQUE(lot_id, operation_seq)`，`chamber` 为单值必填，无同次加工批号 | 无 | 无单独过站。每个 lot 最多 18 行，与固定路线等长，“工序＋层别”不重复。`rework_flag=1` 共 3,257 行，只是该次过站上的标志 | 只能展示“哪一次过站用过哪个腔”，粒度为 `reported` |
| 企业接口样例 `process-runs` | 不能表示，单值 `chamber` | 无 | 无返工字段，也无层别和等待时长 | 同上，且路径和返工维度不可用 |
| 公司履历（用户 2026-11-21 确认，仓库内未核实） | 有同次加工批号 | 有 wafer 级腔室记录 | 返工会另起过站记录 | 可展示“哪一次加工、各腔多少片、哪几片” |

本地数据核实于 2026-11-21，读取 `data/departments/manufacturing_operations.db`：179,509 行、10,013 个 lot，腔室只有 `A`/`B`，ETCH-01～04 都同时有 A 和 B。因此腔室必须按“机台/腔室”成对计算。

契约按能力声明同时支持两种粒度：每次过站带腔室数组，片数和 wafer 清单可为空，`chamber_granularity` 声明该条记录实际能证明到什么程度。本地来源接入后不改字段，公司来源补齐后也不改字段。

## 2. 来源字段与粒度映射

| 契约字段 | 本地 `process_runs` | 公司履历 | 备注 |
| --- | --- | --- | --- |
| `record_ref` | `process_runs:{run_id}` | 由同次加工批号派生的过站引用 | 同一结果版本内稳定，用于回查 |
| `source_record_refs` | `[process_runs:{run_id}]` | 合并前的 wafer／腔室记录主键 | 一次过站可由多条来源记录合并 |
| `source_pass_id` | `null` | 同次加工批号（track-in／batch） | 只有来源认可的批号才可合并记录。时间接近或站点相同都不能合并 |
| `lot_id` | `lot_id` | lot 号 | |
| `pass_seq` | `operation_seq` | 履历序号，字段名待公司确认 | 只用来源顺序判断相邻，不用时间推断顺序 |
| `operation_key`、`layer`、`step` | `layer_name/process_step` | 路线站点标识，字段名待确认 | 区分同名工序（本地 ETCH 出现在 GATE、SPACER、VIA-1） |
| `equipment_id` | `equipment_id` | 机台号 | |
| `chambers[]` | 单元素：`{chamber, chamber_key: "{equipment_id}/{chamber}", wafer_count: null, wafer_ids: null}` | 由 wafer 级记录按腔室汇总片数和 wafer 号 | 不同机台的同名腔室按 `chamber_key` 分开 |
| `chamber_granularity` | `reported` | `wafer_ids`（或只有片数时为 `wafer_count`） | 见下表 |
| `chamber_set_complete` | `true`，依据是模拟 Schema 每次过站一个必填腔室。这是演示假设 | 已分配片数等于该次过站片数时为 `true` | 只有 `true` 才能确认“未用某腔” |
| `allocated_wafer_total` | `null` | 各腔片数之和 | 任一腔片数未知时为 `null` |
| `recipe` | `recipe` | recipe | |
| `track_in_at` | `run_time`（无时区），按显式配置的来源时区补偏移 | 加工时间，时区待确认 | 不得猜测时区；未配置时拒绝时间范围和时间截止。本地来源配置为时区名 `Asia/Shanghai` 加固定偏移 `+08:00`，不依赖系统时区库（Windows 的 Python 可能没有 tzdata）。请求中的时间范围和时间截止必须带偏移，否则返回 `VALIDATION_ERROR` |
| `queue_hours` | `queue_hours`（小时） | 待确认 | 单位固定为小时；缺失为 `null` |
| `rework.is_rework` | `rework_flag = 1` | 返工过站标志 | |
| `rework.rework_of_record_ref` | `null`（无原过站记录） | 被返工的原过站，若来源能关联 | 本地无法区分“返工前”和“返工后”两次经过 |
| `missing_fields` | 通常为空（本地字段必填） | 逐条列出 | 缺失与“不适用”分开 |
| lot `wafer_count` | `lots.wafer_count` | lot 片数 | |

| `chamber_granularity` | 含义 | 可下的结论 |
| --- | --- | --- |
| `not_applicable` | 站点没有腔室概念（清洗、量测等） | 该站不产生腔室候选，不计为缺失 |
| `unknown` | 应有腔室但来源未给出 | 腔室候选判为未知，原因 `FIELD_MISSING` |
| `reported` | 来源给出用过哪些腔，没有片数 | 可判“用过／确认未用”（后者需 `chamber_set_complete`），片数为空 |
| `wafer_count` | 每腔片数已知 | 另可展示各腔片数 |
| `wafer_ids` | 每腔 wafer 号已知 | 另可展示 wafer 清单。首版不把异常晶圆与腔室关联 |

本地 `wafer_maps` 有 wafer 号和机台，没有腔室，所以本地不能把异常晶圆对应到腔室。

**来源能力声明。** `source` 除 `source_id`、`kind`、`timezone`、`queried_at` 外，还声明 `chamber_granularities`（来源可能给出的粒度）、`pass_identity`（`source_pass_id` 表示按来源批号合并记录，`record` 表示一条记录就是一次过站）和 `rework_model`（`separate_pass` 表示返工另起过站并可关联原过站，`flag_only` 表示返工只是过站上的标志）。本地 `process_runs` 来源声明为 `["reported"]`、`record`、`flag_only`；样例夹具声明公司履历的目标能力。

## 3. 统计口径

**组与分母。** 每组输入先去除首尾空白；空值和非法格式直接拒绝。组内重复只计一次并回传 `duplicates`。跨组重复保留在各组，`overlaps` 标出交集；合并视图 `union` 按唯一 lot 计数。每个候选在每组满足 `hit + miss + unknown = denominator = unique_count`。只要输入中有当前主体无权访问的 lot，整次请求按 `SCOPE_DENIED` 拒绝，不回显该 lot，也不透露它是否存在。

**lot 状态。** 每组的 `lot_states` 给出每个唯一 lot 的状态：`complete`、`incomplete`（有缺字段、顺序缺口、截断或局部失败）、`not_found` 和 `source_failed`。后两种 lot 在所有候选中都计为未知。

**覆盖分两项。** `coverage.records` 表示范围内的过站记录是否齐全，`coverage.order` 表示顺序是否可用。存在、机台、腔室和 recipe 维度只看记录覆盖，路径维度还要求顺序覆盖。来源截断（`truncated`）或分页中途失败（`failures`）都会让记录覆盖变为 `partial`：已取到记录中的命中仍然有效，确认未命中改判为未知。

**三态判定。** 判定范围是 lot 在 `scope` 内的过站。

| 维度 | 命中 | 确认未命中 | 未知 |
| --- | --- | --- | --- |
| `equipment`（站点＋机台） | 有一次该站过站的机台等于该机台 | 记录齐全，且该站各次过站机台已知、都不等于该机台；或者记录齐全却没有经过该站（`OPERATION_NOT_VISITED`） | 其余情况 |
| `chamber`（站点＋`chamber_key`） | 有一次过站的 `chambers` 含该腔 | 记录齐全，且该站各次过站的腔室集合完整（`chamber_set_complete`）、都不含该腔 | 有腔室缺失、集合不完整或记录不全 |
| `recipe`（站点＋recipe） | 同 equipment，比较 recipe | 同 equipment | 同 equipment |
| `path_adjacent`（A 站 → B 站） | 有一次 A 站过站的下一次过站（按 `pass_seq`）是 B 站 | 记录和顺序都齐全，且每次 A 站后面都不是 B 站，或未经过 A 站 | 顺序缺口或记录不全 |

同一 lot 多次命中只计一次，`record_refs` 列出全部证据过站。返工过站算作新的一次经过；在 `path_adjacent` 中，返工也会形成 A→A 这样的相邻关系。

**候选。** 候选取主组（`role=primary`）中至少两个不同 lot 命中的值。主组全部命中时 `all_shared=true`。排序依次为：主组命中数降序、主组未知数升序、维度（equipment、chamber、recipe、path_adjacent）、`candidate_id` 升序。排序不代表根因判断，也不引入评分。候选数超过 `max_candidates` 时，按排序截取并置 `candidates_truncated=true`。

**组合条件（成员读取）。** `conditions` 由候选（`{candidate_id}`）和过站属性（`{attribute: "rework", value: true}`）组成，`match_scope` 有两种：

- `same_pass`：同一次过站同时满足全部条件。每次过站按三值逻辑取“与”（假 ∧ 未知 = 假）。任一过站为真则命中；所有相关过站都为假且记录齐全则确认未命中；其余为未知。路径候选涉及两次过站，不能用于 `same_pass`。
- `any_pass`：每个条件各自在任意过站上成立，再对 lot 级结果按三值逻辑取“与”。

响应原样回传 `query.match_scope`，页面和助手必须展示实际采用的范围。

**时间与截止。** 请求的 `timezone` 用于显示和解释时间。来源时区在 `source.timezone` 中回传。时间范围为左闭右开 `[start, end)`。截止有两种：按时间截止（含截止时刻），或按工序截止（`{mode: "operation", operation_key, occurrence, per_lot}`，含截止过站本身）。若某 lot 中截止工序出现多次而未指定 `occurrence` 或 `per_lot`，整次请求返回 `CUTOFF_AMBIGUOUS` 并列出这些 lot，不擅自取末次。lot 中找不到截止工序时，该 lot 计为未知，原因 `CUTOFF_NOT_FOUND`。截止之后的过站（包括事后返工）不进入判定。成员响应的 `hit_time_range` 是命中证据过站的最早和最晚 `track_in_at`；等待时间只展示实测值，单位为小时，不设参考阈值。

**未知原因码**：`LOT_NOT_FOUND`、`FIELD_MISSING`（带 `field`）、`CHAMBER_SET_INCOMPLETE`（腔室集合不完整，不能确认未用某腔）、`SEQUENCE_UNKNOWN`、`SOURCE_TRUNCATED`、`SOURCE_PAGE_FAILED`、`CUTOFF_NOT_FOUND`。**确认未命中依据码**：`OTHER_VALUE`、`OPERATION_NOT_VISITED`、`NOT_ADJACENT`、`CONDITIONS_NOT_MET`。

## 4. 操作与字段

| 操作 | 样例键 | 说明 |
| --- | --- | --- |
| `POST /api/lot-commonality/analyses` | `create_analysis` | 输入组（`group_id` 由客户端指定，`union` 为保留值；`role` 取 `primary`、`concurrent_abnormal`、`historical_abnormal`、`normal_reference`，必须有且只有一个 `primary`）、`dimensions`、`scope`、`timezone`、选填 `description`。返回 `analysis_ref`（`^lca_[a-f0-9]{32}$`）、`status`（`complete`/`partial`）、来源与能力、实际范围、组回执、交集、限额和候选 |
| `GET /api/lot-commonality/analyses/{analysis_ref}` | `read_analysis` | 回读同一版本，响应体与创建时一致 |
| `POST .../{analysis_ref}/members` | `members_*` | `group_id`（可为 `union`）、`conditions`、`match_scope`、可选 `status` 筛选、`limit`、`cursor`。返回不受 `status` 筛选影响的完整计数、`hit_time_range`、成员（`lot_id`、`status`、`record_refs`、`reasons`）和分页。成员按命中、未命中、未知排序，再按 `lot_id` 排序 |
| `POST .../{analysis_ref}/records` | `records_chamber_b` | `group_id`、`lot_ids`、可选 `candidate_id`、`limit`、`cursor`。返回请求 lot 的覆盖情况和候选状态，以及分页的过站记录（字段见第 2 节）。过站按请求 lot 顺序排列，同一 lot 内按 `pass_seq` 升序，无序号的放在最后，再按 `record_ref` 排序。矩阵和路径视图都由这些记录渲染，计数和状态只取服务端值 |

**分页。** 分页单位是成员或过站记录。`limit` 默认 50，最大 200。`cursor` 是不透明字符串，绑定 `analysis_ref`、主体和除游标外的全部查询参数；不匹配时返回 `RESULT_CURSOR_INVALID`。最后一页的 `next_cursor` 为 `null`。`total` 是精确值，因为结果版本有界。

**引用与生命周期。** 同一个 `analysis_ref` 的汇总、成员和明细都读取同一份固定数据；输入改变或重新查数会产生新引用。引用不存在、已过期、属于其他主体或所属会话已删除时，一律返回 `RESULT_UNAVAILABLE`，不区分具体原因。每个入口都按当前主体重新授权。浏览器传入的计数和记录不作为依据。B3 已确定：分析快照存入 [MOD-029 结果库](reports/mod-029-tool-result-access.md)所在的 `tool_results.db`，新增一张会话可为空的快照表，沿用该库的路径校验和容量控制；页面单独创建的结果保留 7 天，聊天中创建的结果绑定会话，并随现有会话删除与撤销流程失效。

B3 实现：结果库 Schema 升到 2，初始化时为 Schema 1 的库原地追加 `analysis_snapshots` 表，已有 Session 结果不动。会话绑定的版本不按时间过期，`expires_at` 为 `null`；会话删除后立即不可读（删除流程未完成时也不可读），清理时一并删除。容量上限：单个版本 32 MiB；每个主体最多 64 个未过期的页面版本，每个会话最多 16 个版本，两类合计每个主体 256 MiB；整库总量与 Session 结果共用 1 GiB／4,096 条。超限时返回 `RESULT_STORAGE_LIMIT`，不写入、不挤掉已有版本；过期的页面版本在下次写入时清理。会话版本只能靠删除会话释放容量。游标用结果库的密钥签名，载荷只含版本号、查询绑定摘要和偏移量。

容量实测（2026-11-24，Windows Python 3.13，本地 `process_runs`，4 个维度，最终代码）：200 个 lot 的快照 2.1 MB，创建 0.23 秒，读一页成员 0.03 秒；500 个 lot（3 组）的快照 5.3 MB，创建 0.68 秒，读一页成员 0.12 秒，汇总响应 210 KB（350 个候选）。B4 把候选判定改为模板加按需计数、按工序索引成员后，限额最严的合成场景（500 个 lot × 100 次过站＝50,000 行来源上限）汇总 4.9 秒、成员 0.10 秒、明细 0.15 秒（此前分别为 59.6 秒和 45 秒）；50,000 行约 29 MB，低于单个版本 32 MiB 上限。公司履历带 wafer 清单时每次过站更大，上线前须用代表性数据复测。

**限额。** `limits`（4 组、每组 200 个 lot、总计 500 个唯一 lot、50,000 行来源记录、500 个候选）按上面的实测保留：最严场景快照约 29 MB、汇总在 5 秒内，均有余量。超限时整次拒绝，返回 `ANALYSIS_LIMIT_EXCEEDED` 并说明是哪一项限额，不静默截断输入。

**Agent 工具。** B3 提供三个具名只读工具：`create_lot_commonality_analysis`、`read_lot_commonality_members`、`read_lot_commonality_records`，参数与上面三个操作一致，与页面 API 共用同一套计算和授权路径。模型不生成 SQL，也不从聊天文字重新计算计数。

B3 实现：`app/tools/lot_commonality/binding.py` 的 `create_lot_commonality_bindings(service, session_id=...)` 生成三个绑定，`session_id` 由服务端装配时给定，工具创建的版本绑定该会话。工具错误映射到 Tool 错误目录：`ANALYSIS_LIMIT_EXCEEDED`、`CUTOFF_AMBIGUOUS`、`RESULT_CURSOR_INVALID` 及其他输入错误（`INVALID_ARGUMENTS`）为参数无效；`SCOPE_DENIED`、`RESULT_UNAVAILABLE` 为拒绝；`RESULT_STORAGE_LIMIT` 为预算阻止；来源失败为 `DATA_SOURCE_FAILED`；存储故障为 `RESULT_READ_FAILED`。工具返回的错误不带 `context` 和具体说明。

F4 实现：新增独立意图 `lot_commonality`，只在识别为共性问题的路由上装配这三个工具（专用 profile，含 `session_id`），默认工具目录和其他意图不变。给模型的精简视图在 `app/core/lot_commonality_view.py`：汇总只带组回执、计数和前若干候选（单个工具消息小于 8 KB），成员和记录另有自己的精简投影，由 `app/core/tool_result_projection.py` 优先按 `MODEL_VIEWS` 投出；200 KB 的完整汇总不进入模型上下文。页面附带引用时，`app/api/services/analysis_attachment.py` 在任何消息入库前按当前主体重新授权，把固定版本的精简摘要拼进模型问题；回答里出现的引用只取工具轨迹（attached/created/read），不取模型文字。无效、他人或失效引用在入库前返回 404 `RESULT_UNAVAILABLE`；`analysis_ref` 与 `tool_result_ref` 互斥（422）。系统验证见 `tests/system/test_lot_commonality_chat.py`（脚本化回环模型驱动的真实 HTTP 链路）。

## 5. 错误

沿用现有 HTTP 信封 `error_code/detail/request_id/retryable`。附加信息放在 `context` 中，`app/api/errors.py` 的 `error_payload` 已支持附加字段。样例见 `contract_examples.json` 的 `errors`：

| 样例键 | HTTP | 错误码 | 场景 |
| --- | --- | --- | --- |
| `scope_denied` | 403 | `SCOPE_DENIED` | 输入含无权 lot；响应不回显该 lot |
| `result_unavailable` | 404 | `RESULT_UNAVAILABLE` | 引用不存在、过期、他人所有或会话已删除 |
| `cursor_invalid` | 400 | `RESULT_CURSOR_INVALID` | 游标与查询参数不匹配 |
| `same_pass_with_path` | 422 | `VALIDATION_ERROR` | 路径条件用于 `same_pass` |
| `cutoff_ambiguous` | 422 | `CUTOFF_AMBIGUOUS`（新增） | E 两次经过 GATE/ETCH，未指定出现次数 |
| `limit_exceeded` | 422 | `ANALYSIS_LIMIT_EXCEEDED`（新增） | 超过暂定限额 |
| `source_failed` | 502 | `DATA_SOURCE_FAILED` | 整次来源查询失败；不当作无数据，也不切换到模拟来源 |
| （无样例） | 403 | `SCOPE_DENIED` | 当前身份没有 `analyst` 角色，任何操作都拒绝 |
| （无样例） | 507 | `RESULT_STORAGE_LIMIT` | 超过结果版本的容量上限，见第 4 节 |
| （无样例） | 503 | `RESULT_STORE_UNAVAILABLE` | 结果库不可用或 Schema 不符，`retryable=true` |

局部失败不作为错误返回：分析 `status=partial`，相关 lot 的状态为 `incomplete` 或 `source_failed`，并带上原因码。两个新增码已登记到[错误码参考](error-code-reference.md)。

## 6. 样例与计划预期对照

主组为 A～H，同期异常组为 B、J、K，维度为 equipment、chamber、path_adjacent，无时间范围。

| 计划第 4 节预期 | 样例位置与结果 |
| --- | --- |
| ETCH-07 为 8/8 | `eq:GATE/ETCH:ETCH-07` 主组 8/0/0，`all_shared=true` |
| CH-B 命中 6、确认未命中 1、未知 1，成员依次为 A～F、G、H | `members_chamber_b`；G 依据 `OTHER_VALUE`，H 原因 `FIELD_MISSING: chamber` |
| B 分腔共 25 片（12/13），C 片数为空 | `records_chamber_b` 中 `pass:B-02`（`wafer_ids`，12＋13），`pass:C-02`（`reported`，`allocated_wafer_total=null`） |
| E 两次经过同腔，CH-B 仍为 6 个唯一 lot；“CH-B 且确认返工”只有 E | `pass:E-02`、`pass:E-03`（返工，指向 E-02）；`members_chamber_b_rework_same_pass` 为 1/7/0。H 的 ETCH 过站不是返工，按“假 ∧ 未知 = 假”计为确认未命中 |
| 刻蚀后紧接量测为 5 命中、2 未命中、1 未知，F、G 的分叉可查 | `members_path_etch_metrology_page_1/2`（每页 4 个）；F、G 的证据指向 GATE/WET-STRIP 过站 |
| 同期组 CH-B 为 1/3，合并后 10 个唯一 lot、CH-B 仍为 6 | CH-B 同期组 1/2/0，`union` 为 6/3/1 |

另外两项可直接核对：WET-02 主组为 2/6/0，H 虽然顺序不全但记录齐全，所以计为确认未命中；而 `path:GATE/CLEAN>GATE/ETCH` 为 7/0/1，H 因顺序缺口计为未知。

后端计划第 4 节的独立反例（证据只在第 101 行、同名腔室属于另一机台、分页中途失败、截止之后才返工、两个用户互读引用、超过预算、读取已失效结果）由 B2/B3 按本文规则另建夹具并断言，不并入上述样例。

## 7. 验证范围与交接

- **本地来源能验证的**：机台、单腔 `reported` 粒度、recipe、相邻路径（本地顺序总是完整的）、返工标志和等待小时数。
- **只能用合成夹具验证的**：同次分腔、各腔片数与 wafer 清单、按批号合并记录、返工另起过站及其关联、腔室缺失、顺序缺口、来源截断与局部失败。
- **公司上线前要确认的**：同次加工批号、履历序号、站点标识、加工时间与时区、等待时长和返工关联对应的实际字段名；wafer 级记录的完整性（`chamber_set_complete` 的判定依据）；数据权限；以及代表性数据下的行数与耗时，用于修订限额。
- **来源替换**：新来源实现 `app/tools/lot_commonality/contracts.py` 的 `LotHistorySource.fetch(lot_ids, principal) -> LotHistoryBatch`，把公司履历投影成第 2 节的过站字段（不存在的字段进 `missing_fields`，证明不到的粒度按 `chamber_granularity` 声明），`source_metadata` 声明实际能力（粒度、`pass_identity`、`rework_model`），再替换 `app/bootstrap/lot_commonality_assembly.py` 的 `_source()`。页面 API、Agent 工具、聊天附带引用、结果库和限额都走 `service.py`，不需要改动。本地 `SQLiteLotHistorySource` 的键集分页、行数预算、只读连接和查询超时可作参照。字段缺口以上面「公司上线前要确认的」清单为准，接入时逐项回填实际字段名。
- **F1/F2**：直接用 `contract_examples.json` 驱动界面，不另写一份手工副本。需要静态提供时，由 F2 决定复制或映射到 `display_mock_data/`，并以本文件为准。
- **B2**：以 `source_passes.json` 作为来源替身，输出须与 `contract_examples.json` 逐字段一致（`analysis_ref`、时间戳和游标等不透明或运行期字段除外）。实现位于 `app/tools/lot_commonality/`：`analysis.py` 计算并生成可序列化的固定快照，`sqlite_source.py` 按键集分页读取本地 `process_runs`，在行数预算处截断并标记，不补造未命中。游标令牌和快照保存由 B3 负责。
- **B3**：已实现。`service.py` 是页面 API 和工具共用的授权与读取入口，`app/bootstrap/lot_commonality_assembly.py` 装配本地来源和结果库，`app/api/routers/lot_commonality.py` 提供四个路由，与其他路由一样经 `app/api/runtime_dependencies.py` 发布、在 `app/main.py` 注册。`tests/test_api_runtime_boundaries.py` 对 `app/main.py` 的行数上限从 250 调到 260：该上限设立时文件为 227 行，此后报表目录等功能已增到 249 行，新增路由的导入和注册无法再放进 250 行；`app/main.py` 仍只做组装，不含业务实现。验证见 `tests/system/test_lot_commonality_api.py`（真实 HTTP 与工具读同一版本、越权、过期、会话删除、游标、容量、并发、重新查询）和 `tests/test_tool_result_store.py` 的 `AnalysisSnapshotStoreTests`（Schema 升级、撤销、限额、令牌）。
- **F4/B4**：已实现。相关性分析页面「问助手」把当前结果写成草稿和可移除的引用标签，发送时以 `analysis_ref` 结构化字段传递（不出现在消息文本和 URL）；助手回答中本轮附带、创建或读取的引用显示「在共性分析页打开」，点击切回相关性分析页、回读同一版本并按结果回填输入区（重复项与描述不在快照中，回填为去重后的唯一 lot 和空描述）；合成样例和已失效结果禁用「问助手」。无效、他人或失效的引用在消息入库前被 404 拒绝。浏览器验证见 `tests/e2e/lot-commonality-chat.spec.js`：聊天模型为脚本化回环协议夹具的 lot-commonality 场景（确定性调用三个工具），四个用例覆盖创建后回开、附带发问与移除标签、失效引用、样例与失效结果禁挂；同一组发现可从页面和助手两条路径复现。真实 DeepSeek 探针（`runtime/quality/lca_deepseek_probe.py`，一次性库副本，不打印凭据，报告写入 `runtime/quality/lca_deepseek_probe.json`）于 2026-11-24 用有效密钥执行 5 个用例，全部符合预期：创建（`lot_commonality` 意图、工具成功、按 3/3 共同命中列出机台/腔室/recipe）、附带解读（按引用读成员并给出排查优先级）、他人引用与不存在引用均入库前 404、无关问题仍走原有意图路由。首轮探针暴露模型在未要求范围时自行附加截止工序（`CUTOFF_NOT_FOUND`、零候选），已在 `binding.py` 的工具与 `scope` 描述中明确「未明确给出范围时 time_range 和 cutoff 均为 null」，修复后模型一次调用即得到真实候选。
- **F4/B4 验证记录（2026-11-24）**：WSL `run_quality_gate.py full` 的 Python 覆盖运行（1526 项）、system 预算、覆盖率（≥80%）、Node（85 项）、`check_repository` 全部通过；浏览器全量 45/45；Windows Python 3.13 全量 1620 项通过（14 项既有跳过）。首轮全门暴露 8 个 portable 基线未随新模块更新（6 个切片计数、2 个切片缺文件、1 个轻量导入基线），已修正后复跑通过，非代码行为回归。环境问题单独记录：仓库默认布局未执行运行时存储分离，`evaluate_rag.py` 直接运行报 `RUNTIME_STORAGE_MIGRATION_REQUIRED`（既有状态，与本次改动无关）；未改动真实数据，5 个评估器改在一次性已分离库副本上运行，全部通过。ruff 全仓 252 个既有错误、改动文件错误与基线一致；仓库/模块边界、refactor 契约、`git diff --check` 通过。真实 DeepSeek 探针在换用有效密钥后执行，5 个用例全部通过，并据此修正了工具范围描述（见上条）。
- **F3**：已实现。页面「查询」走第 4 节的真实接口；「载入契约样例」仍只回放样例，结果带「合成样例」标记。成员或明细返回 `RESULT_UNAVAILABLE` 时，整个结果标为「已失效」并停用计数下钻，提示重新查询；`RESULT_CURSOR_INVALID` 提供回到第一页；`retryable=true` 的失败提供重试；`VALIDATION_ERROR` 显示 `fields`。浏览器验证见 `tests/e2e/lot-commonality-http.spec.js`：测试直接读取参考库 `data/departments/manufacturing_operations.db`（服务端使用其一次性副本）得出期望值，逐项核对页面分子、分母、成员顺序和两页原始过站；超限、他租户的 `SCOPE_DENIED`、换用户后的 `RESULT_UNAVAILABLE`、改写游标后的 `RESULT_CURSOR_INVALID` 都由真实服务端返回。本地来源不会截断或中途失败，「部分返回」用例把真实响应改写成 `partial` 后只检查页面呈现；晚返回和 503 重试用拦截延迟或替换单次响应。该用例依赖 Node 22 自带的 `node:sqlite`（会打印实验特性警告）。
