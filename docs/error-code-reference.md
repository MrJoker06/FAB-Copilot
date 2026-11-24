# 错误码与场景处理参考

基线：2026-11-18，`feat/pe-ee-duty-workspace`，源码起点 `3415428`。关联 GitHub #1 第 7 项。运行代码以 `app/agent_runtime/tools/contracts.py` 的 `TOOL_ERROR_CATALOG` 为 Tool 错误语义的唯一来源；本页解释诊断与处置方法。现有 HTTP/领域协议另见末节，并未统一改造成 ToolResult。

## 命名与返回字段

- 新增公开错误码使用 `UPPER_SNAKE_CASE`，表示稳定的失败原因；同一原因使用同一个码，不把异常文本、设备号、身份或请求编号拼入码中。
- `error_kind` 是分类，`status` 是调用结果，`execution_state` 表示执行是否开始/结束，三者不能互相替代。`INVALID_ARGUMENTS` 可细分 parsing/validation；前置失败为 dependency。
- `error` 是安全公开描述，`user_message` 是面向值班用户的中文说明，`recovery_action` 是处置建议。`retryable` 不授予权限，不会自动重试。
- `execution_state=unknown` 时统一提示先核实执行状态，`retryable=false`。超时不证明远端操作已停止；不能直接重复调用。
- Dispatcher 仅保留已知且分类匹配的策略/预算拒绝码，未知码降为 `POLICY_DENIED`/`BUDGET_BLOCKED`，不直接回显外部拒绝文本。自定义 ToolError 仍兼容，不会把任意外部码注册成可信语义。
- 旧 Guard 的小写原因只作为兼容输入/诊断；新增公开投影使用大写码。历史会话不重写，旧轨迹仍可展示。

## 处理策略

| recovery_action | 当前处理与下一步 |
| --- | --- |
| correct_arguments | 拒绝本次输入；修正类型、必填项、范围或分页参数后才可重新提交 |
| request_access | 拒绝执行/回读；确认身份、角色和数据范围，按实际授权流程申请权限 |
| use_existing_results | 阻止重复/超预算/未计划的调用；使用已有结果或结束当前分析，不绕过预算 |
| skip_dependent_step | 跳过依赖前置成功的步骤；不能把未调用的处理器标为执行成功 |
| report_source_failure | 来源返回失败；明确缺少依据，不伪装为空数据或自动换模拟来源 |
| start_new_run | 调用前已超过期限；需要时由用户重新发起任务，仍受权限与预算约束 |
| check_execution_state | 已进入执行但完成状态不确定；先核实，禁止自动重复调用 |
| retry_read | 只针对受控结果回读的故障；当前不自动重试，重新读取仍消耗读取预算 |
| contact_administrator | 契约、装配、内部处理或记账失败；保留任务/请求编号供管理员排查 |
| stop | 取消执行；不能把取消当成成功，也不自动继续 |

标准工厂生成的错误默认均不允许自动重试。外部 ToolError 即使声明可重试，公开投影也只对已确认状态的 data_source/timeout 保留该标记；实际调用仍重新经过授权与预算。结果回读故障的 `retry_read` 仅描述可人工尝试的方向。

## Tool 错误对应表

下表描述默认语义；执行状态 unknown 时以 `check_execution_state` 覆盖建议和中文提示。参数拒绝发生在执行前；授权/预算拒绝不会调用处理器。来源失败表示调用已结束且未取得有效数据，不等于成功但零条记录。

| 错误码 | 分类 | 公开描述 | 值班用户提示 | 默认处置 |
| --- | --- | --- | --- | --- |
| RUN_ID_MISMATCH | internal | The tool call does not belong to this run. | 工具调用与当前任务不匹配。 | contact_administrator |
| UNKNOWN_TOOL | internal | The requested tool is unavailable. | 请求的工具不存在。 | contact_administrator |
| TOOL_UNAVAILABLE | internal | The requested tool is unavailable. | 请求的工具当前不可用。 | contact_administrator |
| TOOL_CONFIGURATION | internal | The tool could not be prepared. | 工具配置不完整。 | contact_administrator |
| TOOL_PREPARATION_FAILED | internal | The tool could not be prepared. | 工具准备失败。 | contact_administrator |
| POLICY_FAILED | internal | The tool could not be authorized. | 工具授权检查失败。 | contact_administrator |
| BUDGET_FAILED | internal | The tool budget could not be checked. | 工具预算检查失败。 | contact_administrator |
| TOOL_FAILED | internal | The tool could not complete. | 工具执行失败，请凭任务编号联系管理员。 | contact_administrator |
| INVALID_RESULT | internal | The tool returned an invalid result. | 工具返回结果不符合契约，不能作为分析依据。 | contact_administrator |
| RESULT_POLICY_FAILED | internal | The tool result could not be finalized. | 工具结果处理失败，不能作为分析依据。 | contact_administrator |
| ACCOUNTING_FAILED | internal | The tool result could not be recorded. | 工具结果未能完成记账，不能标记为成功。 | contact_administrator |
| TOOL_DENIED | authorization | This tool is not authorized. | 当前身份无权使用该工具。 | request_access |
| LEGACY_DENIED | authorization | This tool is not authorized. | 当前运行未授权使用旧版工具。 | request_access |
| READ_ONLY_REQUIRED | authorization | This tool is not authorized. | 当前运行只允许只读工具。 | request_access |
| POLICY_DENIED | authorization | This tool is not authorized. | 工具调用被访问策略拒绝。 | request_access |
| CAPABILITY_DENIED | authorization | This tool is not authorized. | 当前运行未授权该能力。 | request_access |
| ROLE_DENIED | authorization | This principal is not authorized. | 当前身份角色无权使用该工具。 | request_access |
| SCOPE_DENIED | authorization | This scope is not authorized. | 当前身份无权访问请求的数据范围。 | request_access |
| RESULT_UNAVAILABLE | authorization | 结果当前不可读取。 | 结果当前不可读取。 | request_access |
| SUBMISSION_MIXED | validation | submit_analysis must be called alone. | submit_analysis 必须单独调用，不能与数据工具处于同一轮。 | correct_arguments |
| INVALID_ARGUMENTS | validation | Tool arguments are invalid. | 工具参数无效，请检查参数类型、必填项和查询范围。 | correct_arguments |
| RESULT_CURSOR_INVALID | validation | 结果分页参数无效。 | 结果分页游标无效，请从第一页重新读取。 | correct_arguments |
| RESULT_INVALID | validation | 结果分页参数无效。 | 结果读取参数无效。 | correct_arguments |
| ANALYSIS_LIMIT_EXCEEDED | validation | The analysis input exceeds its limits. | 输入超过分析限额，请缩小 lot 范围。 | correct_arguments |
| CUTOFF_AMBIGUOUS | validation | The cutoff operation is ambiguous. | 截止工序在部分 lot 中出现多次，请指定出现次数或截止时间。 | correct_arguments |
| BUDGET_EXHAUSTED | budget | The tool budget is exhausted. | 工具调用额度已用尽，请使用已有结果完成回答。 | use_existing_results |
| BUDGET_BLOCKED | budget | The tool budget blocked this call. | 工具调用被预算策略阻止。 | use_existing_results |
| TOOL_BUDGET_DISABLED | budget | The execution plan does not allow tool calls. | 当前计划不允许调用工具。 | use_existing_results |
| DUPLICATE_ARGUMENTS | budget | Identical tool arguments have already been used. | 相同工具和参数已调用，请使用已有结果。 | use_existing_results |
| TOTAL_TOOL_BUDGET_EXHAUSTED | budget | The total tool budget is exhausted. | 工具总调用额度已用尽，请使用已有结果。 | use_existing_results |
| PER_TOOL_BUDGET_EXHAUSTED | budget | The per-tool budget is exhausted. | 该工具的调用额度已用尽，请使用已有结果或其他已授权步骤。 | use_existing_results |
| UNPLANNED_TOOL | budget | The tool is not part of the approved plan. | 该工具不在当前执行计划内。 | use_existing_results |
| SYNTHESIS_ONLY | budget | The run only permits synthesis from existing results. | 当前任务已进入综合阶段，请使用已有结果。 | use_existing_results |
| RESULT_READ_BUDGET | budget | 结果读取预算已用尽。 | 结果读取预算已用尽。 | use_existing_results |
| RESULT_RESPONSE_LIMIT | budget | 结果读取响应额度不足。 | 结果读取响应额度不足，请缩小读取范围。 | use_existing_results |
| RESULT_STORAGE_LIMIT | budget | The result storage quota is exhausted. | 分析结果保存容量不足，请使用已有分析或稍后重试。 | use_existing_results |
| DEPENDENCY_FAILED | dependency | A required prior step did not succeed. | 前置步骤未成功，当前步骤已跳过。 | skip_dependent_step |
| DEADLINE_EXCEEDED | timeout | The tool deadline was exceeded. | 当前任务时限已到。 | start_new_run |
| SOURCE_TIMEOUT | timeout | The tool timed out. | 数据来源响应超时。 | start_new_run |
| DATA_SOURCE_FAILED | data_source | The tool data source failed. | 数据来源失败，不能将其当作无数据或切换到模拟来源。 | report_source_failure |
| RESULT_READ_FAILED | internal | 结果存储当前不可用。 | 结果存储当前不可用，请稍后重试读取。 | retry_read |
| CANCELLED | cancellation | The tool call was cancelled. | 工具调用已取消，不会自动继续。 | stop |

## 执行阶段与触发场景

| 阶段 | 错误码与具体触发 |
| --- | --- |
| 调用识别 | RUN_ID_MISMATCH：调用上下文属于其他 run；UNKNOWN_TOOL：工具标识不合法；TOOL_UNAVAILABLE：注册解析失败或没有可执行绑定 |
| 装配与准备 | TOOL_CONFIGURATION：绑定名称、输入构造或装配契约不匹配；TOOL_PREPARATION_FAILED：准备阶段异常；INVALID_ARGUMENTS：JSON 不是对象或输入验证拒绝；SUBMISSION_MIXED：提交分析与数据工具混在一轮 |
| 授权 | TOOL_DENIED：不在允许工具集合或处理器明确拒绝；LEGACY_DENIED：本轮不允许旧工具；READ_ONLY_REQUIRED：只读运行收到非只读工具；ROLE_DENIED/SCOPE_DENIED/CAPABILITY_DENIED：对应角色、数据范围或能力拒绝；POLICY_DENIED：其他/未知策略拒绝；POLICY_FAILED：授权检查本身异常 |
| 预算与阶段 | BUDGET_EXHAUSTED：上下文额度为零；TOOL_BUDGET_DISABLED：计划禁用工具；DUPLICATE_ARGUMENTS：重复工具参数；TOTAL_TOOL_BUDGET_EXHAUSTED/PER_TOOL_BUDGET_EXHAUSTED：总量/单工具额度耗尽；UNPLANNED_TOOL：Ready 计划外工具；SYNTHESIS_ONLY：已进入仅综合阶段；BUDGET_BLOCKED：其他/未知预算拒绝；BUDGET_FAILED：预算检查异常 |
| 执行与结果 | DATA_SOURCE_FAILED：来源明确失败；TOOL_FAILED：未分类执行异常；INVALID_RESULT：结果对象、Schema、调用身份或来源范围不符合契约；RESULT_POLICY_FAILED：结果收敛异常；ACCOUNTING_FAILED：结果记账失败，不能发布为成功 |
| 依赖、期限与取消 | DEPENDENCY_FAILED：所依赖步骤未成功；DEADLINE_EXCEEDED：开始前或结束时超过期限；SOURCE_TIMEOUT：来源超时；CANCELLED：收到取消信号。后两者及晚到结果按实际执行状态处理，unknown 不可自动重放 |
| 结果回读 | RESULT_UNAVAILABLE：会话、身份、所有权或可见性校验不通过，统一不泄露资源是否存在；RESULT_CURSOR_INVALID/RESULT_INVALID：游标/读取输入无效；RESULT_READ_BUDGET：读取额度用尽；RESULT_RESPONSE_LIMIT：可返回字节不足；RESULT_READ_FAILED：存储读取发生其他故障 |
| Lot 相关性工具（`lot_commonality` 意图装配） | ANALYSIS_LIMIT_EXCEEDED：组数或 lot 数超过分析限额；CUTOFF_AMBIGUOUS：截止工序在部分 lot 中出现多次且未指定；RESULT_STORAGE_LIMIT：分析版本超过主体或会话的保存容量，未写入；其余输入错误为 INVALID_ARGUMENTS，无权 lot 或缺少 analyst 角色为 SCOPE_DENIED，存储故障为 RESULT_READ_FAILED。见 `app/tools/lot_commonality/binding.py`；聊天附带引用在入库前的拒绝为 RESULT_UNAVAILABLE（404，不区分不存在、过期、他人或会话已删除），见 `app/api/services/analysis_attachment.py` |

## 模型、轨迹与前端

Ready/Loop 的失败传播携带错误码、分类、执行状态和建议。Legacy 执行分支把参数、权限、来源、超时与内部异常转为相同公开语义；内部异常细节不直接发给模型或页面。原有诊断日志路径仍由遥测脱敏策略管理，本次没有新增日志系统。

`tool_finished` 事件与最终 `tool_trace` 使用相同字段；页面同时展示中文提示及错误码，会话恢复后保持一致，并对 HTML 转义。当前没有新增自动重试按钮或恢复引擎。

## 既有 HTTP、领域与浏览器错误

这些入口保留原有协议：HTTP 使用 `error_code/detail/request_id/retryable`，部分领域异常有自己的状态码。HTTP 200 或一个 retryable 标记都不代表 Tool 已成功/可安全重放。不同操作的重试与幂等性由原入口负责；下面是对应表，不承诺本次改写了所有领域返回。

| 错误码 | 原因、处置与代码归属 |
| --- | --- |
| VALIDATION_ERROR、HTTP_ERROR、NOT_FOUND、INTERNAL_ERROR | 请求校验、通用 HTTP、资源缺失、未捕获异常；检查参数/资源或凭 request_id 排查，见 `app/api/errors.py` |
| ADMIN_NOT_CONFIGURED、ADMIN_AUTHENTICATION_REQUIRED、AUTHENTICATION_REQUIRED、IDENTITY_REQUIRED、INVALID_IDENTITY | 管理配置/认证/身份缺失或无效；先完成实际认证与配置，见 `app/api/dependencies.py`、`app/core/identity.py`，不自动重试 |
| MODEL_CAPABILITY_UNSUPPORTED、PROVIDER_NOT_CONFIGURED | 选定模型不支持所需能力或提供方缺失；选择已配置能力/检查配置，见 `app/api/services/chat.py` |
| MODEL_NETWORK_ERROR、MODEL_UPSTREAM_ERROR、ANALYSIS_ERROR | 网络、模型上游或分析失败；保留请求编号并确认已保存状态再重发，见 `app/api/services/chat.py`、`chat_stream.py` |
| MODEL_PUBLICATION_FAILED、MODEL_STATUS_UPDATE_FAILED、MODEL_CAPABILITIES_UPDATE_FAILED、MODEL_DELETE_FAILED、MODEL_CREDENTIAL_FAILED、MODEL_COMPATIBILITY_FAILED | 对应模型发布、状态、能力、删除、凭据及兼容配置操作失败；按具体响应纠正配置，见 `app/api/routers/admin.py`，本次不修改模型配置 |
| REPORT_DIRECTORY_CONFLICT、REPORT_DIRECTORY_UNAVAILABLE | 目录并发修改/目录存储不可用；前者刷新后编辑，后者管理员检查路径与配置，见 `app/api/report_directory.py` |
| SHARED_DOCUMENTS_UNAVAILABLE | 共享文档存储不可用；管理员检查配置，见 `app/api/routers/shared_documents.py` |
| SESSION_NOT_FOUND、IDEMPOTENCY_CONFLICT | 会话不存在/同幂等键内容冲突；检查当前会话或原请求内容，见 `app/api/services/chat.py` 与 `app/conversation/sessions.py` |
| INVALID_CURSOR、CURSOR_QUERY_MISMATCH、CURSOR_SCOPE_MISMATCH、INVALID_PAGE_SIZE | 列表游标无效、查询/范围不一致或分页大小错误；按当前筛选重新分页，见个人知识库和会话列表入口 |
| INVALID_FILTER、INVALID_DATE、INVALID_DATE_RANGE、INVALID_PROCESS_STEP、INVALID_SIGNAL、INVALID_STATUS、UNKNOWN_ENTITY | 业务查询筛选、日期、工序、指标、状态或实体无效；纠正业务参数，不执行任意 SQL，见 `app/demo_data/synthetic_fab.py`、`app/tools/` |
| INVALID_METADATA、INVALID_DOCUMENT_METADATA、INVALID_DOCUMENT_STATE | 上传/文档元数据或状态无效；修正输入或按有效状态操作，见 `app/personal_knowledge/`、`app/personal_knowledge_runtime/` 与共享上传入口 |
| DOCUMENT_NOT_FOUND、DOCUMENT_FILE_MISSING、DOCUMENT_RETRY_UNAVAILABLE、DUPLICATE_DOCUMENT | 文档不存在、文件缺失、不可重试或重复文档；检查持有资源及状态，不自动重复上传，见个人知识库运行时 |
| FILE_TOO_LARGE、UNSUPPORTED_FILE_TYPE、INVALID_FILE_CONTENT | 上传大小、类型或内容不支持；用户更换合规文件，见个人/共享知识上传入口 |
| STORAGE_FILE_MISSING、STORAGE_PATH_ERROR | 文件缺失或存储路径不可用；管理员检查实际文件与配置，见个人知识库存储实现 |
| OCR_UNAVAILABLE、OCR_FAILED、OCR_QUALITY_LOW | OCR 能力不可用、识别失败或质量不足；按详情检查依赖/替换文件，不能伪装提取成功，见 `app/knowledge/ocr.py` 与个人知识库处理器 |
| RESULT_CALL_CONFLICT、RESULT_STORAGE_LIMIT | 结果调用标识冲突/独立结果库容量不足；先排查调用身份或清理策略，不静默删除有效 Session 结果，见 `app/persistence/tool_result_store.py` |
| ANALYSIS_LIMIT_EXCEEDED、CUTOFF_AMBIGUOUS | Lot 相关性分析输入超过限额（422，`context` 说明哪项限额）/截止工序在部分 lot 中出现多次（422，`context` 列出这些 lot）；修正输入后重新创建。同一入口另用 SCOPE_DENIED（403）、RESULT_UNAVAILABLE（404）、RESULT_CURSOR_INVALID（400）、RESULT_STORAGE_LIMIT（507）、RESULT_STORE_UNAVAILABLE（503）、DATA_SOURCE_FAILED（502），见 `app/api/routers/lot_commonality.py` 与[契约](lot-commonality-contract.md) |
| RESULT_STORE_CONFIG_INVALID、RESULT_STORE_PATH_INVALID、RESULT_STORE_SCHEMA_INVALID、RESULT_STORE_UNAVAILABLE | 结果库配置、路径、Schema 或存储不可用；管理员检查，见 `app/persistence/tool_result_store.py` |
| REQUEST_ERROR、NETWORK_ERROR、STREAM_INCOMPLETE | 浏览器请求失败、网络错误或流未完整结束；保留失败状态，检查网络和会话后人工重试，见 `app/static/app/core/api.js` 与聊天控制器 |

Tool 与上述领域共享的 `RESULT_UNAVAILABLE`、`RESULT_INVALID`、`RESULT_CURSOR_INVALID` 等含义一致；内部来源/存储异常在真正的 Tool 执行边界映射到上方 Tool 表。后续新增码应更新拥有该错误的模块和本页；本次没有引入全局错误拦截或跨模块万能重试机制。
