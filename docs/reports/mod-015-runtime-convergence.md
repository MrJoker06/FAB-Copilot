# MOD-015：Runtime 收口、依赖类型化与兼容退出

日期：2026-11-07。基线：`1c61601`（MOD-012）。状态：进行中（015a～015d 已验证，015e 未开始）。

## 分批

用户确认把 MOD-015 拆成 5 个批次，每批独立验证，不一次性改写 Runtime：

| 批次 | 内容 | 状态 |
| --- | --- | --- |
| 015a | 兼容台账收敛：删除纯转发模块与已无生产消费者的旧 facade，修正台账；附带配置优先级修复 | 已验证（2026-11-07） |
| 015b | 依赖组/状态类型化与 EventSink | 已验证（2026-11-07） |
| 015c | Loop 职责拆分 | 已验证（2026-11-07） |
| 015d | 存储/身份依赖注入 Port（含 model_gateway → persistence/identity/memory 的 5 条债务） | 已验证（2026-11-07） |
| 015e | Skill 启用/未启用完整链路，取消/异常无状态泄漏验收 | 未开始 |

## 015a：兼容台账收敛

### 范围

只做兼容退出和台账校正，不涉及类型化、Loop 拆分或存储改造。公开入口 `run_agent`、`service` 动态发布、`TOOLS`/`TOOL_HANDLERS` 对象身份及 live patch 语义不变。

### 变更

| 项 | 变更 |
| --- | --- |
| 配置优先级 | `app/core/settings.py` 先加载项目 `.env`，再加载工作区 `.env`（项目上两级目录）。两者都用 `setdefault`，所以优先级为：进程环境变量 > 项目 `.env` > 工作区 `.env`。原来顺序相反，工作区里残留的旧 `DEEPSEEK_API_KEY` 会盖住项目密钥。`FAB_PROJECT_ENV_FILE` / `FAB_WORKSPACE_ENV_FILE` 覆盖路径的方式不变 |
| coordinator 转发模块 | 删除 `app/agent_runtime/coordinator_{availability,loop,model,prepare,ready}.py`。唯一消费者 `tests/test_agent_runtime_boundaries.py` 改为直接使用 `app.agent_runtime.stages.*`，断言改为“各阶段的 canonical 所在模块 + 旧文件不存在”。原来的 `"async def" not in coordinator_prepare` 检查只用于保证转发模块里没有逻辑，文件删除后这项检查已无对象，由“文件不存在”断言替代 |
| 上下文 facade | 删除 `app/conversation/context_resolver.py`。`tests/test_context_resolver.py`、`tests/test_memory_system_context.py`、`tests/test_conversation_runtime_module_boundaries.py` 改为导入 `app.memory_system.{contracts,context.history,context.resolver}`，并断言旧文件不存在。`tests/test_module_boundaries.py` 里只是把它当合成夹具字符串，未改 |
| `state.endpoint` | 从 `stages/model.py`、`CoordinatorRunState` 字段和 `model_state` 视图里删除；主路径从 MOD-012 起就不再读取它 |
| 旧 synthesis facade | 删除 `compatibility.py` 中 `(client, endpoint, headers)` 形式的 `_request_ready_synthesis` / `_request_synthesis_correction`，保留 `_request_ready_synthesis_session` / `_request_synthesis_correction_session`（`legacy_agent_assembly` 本来就只用这两个） |
| `ClientModelSession` | 删除这个已无生产消费者的类及其 `__all__` 项。`tests/test_agent_synthesis_boundaries.py` 改用本地的 `ModelSessionPort` 测试替身；`tests/test_model_gateway_port.py` 删除旧适配器测试，Port 一致性改为检查 `HttpModelSession` |
| 兼容性探针 | `check_model_compatibility` 改用 `ModelEndpoint.from_connection(connection)` 的 `chat_completions_url` 和 `headers()`。注入的 `client` 参数和自建客户端（`follow_redirects=False`）保持不变：这是管理端探针，不在 Run Loop 内。`model_gateway` 仍不导入 `agent_runtime` |
| URL 规范化 | `ModelEndpoint.from_connection` 对 `base_url` 去掉末尾的 `/`。原探针有 `rstrip('/')`，这一步保证改成单一来源后 URL 不变；Runtime 侧的 `base_url` 本来就在 `settings.py`/`registry.py` 中规范化过，实际取值不受影响 |
| 台账 | 删除 6 个文件的归属、6 个兼容入口及其消费记录；`compatibility_consumers` 按检查器实算结果重写（只有删除，没有新增）。`module_boundaries_v1.json` 删除 `canonical_modules` 中的 `app.conversation.context_resolver`，`production_forbidden_imports` 保留该路径，用来防止生产代码重新引入（`retired_modules` 只接受 `app.<根模块>`，不能登记嵌套路径） |
| 债务更正 | `dependency_debt` 中 5 条 `exit_task: "MOD-012"`（model_gateway.compatibility → memory_system.context.history/protocol；model_gateway.health → persistence.database；model_gateway.registry → persistence.database / core.identity）改为 `MOD-015`，并在 reason 末尾注明 MOD-012 只收口了客户端生命周期，这些存储/身份边移到 015d。检查器和测试都不断言 exit_task 的具体取值 |

`evaluations/mod_002_reference_v4.json` 是冻结的历史参考（成员来自固定 Git 基线 `0c93cf6`，`validate_archive` 只拿 ZIP 和元数据比对，不检查当前工作树），所以仍列出已删除的文件，没有修改。

### 兼容说明

- 外部如果还在导入 `app.agent_runtime.coordinator_*` 或 `app.conversation.context_resolver`，会得到 `ModuleNotFoundError`。应改用 `app.agent_runtime.stages.*` 和 `app.memory_system.*`；两者导出的对象与原转发对象相同。
- 调用 `service._request_ready_synthesis(client, endpoint, headers, ...)` 的代码应改为先通过 `ModelGatewayPort.open()` 拿到会话，再调用 `_request_ready_synthesis_session(session, ...)`。
- 部署方如果依赖“工作区 `.env` 覆盖项目 `.env`”，现在需要把值写进项目 `.env` 或进程环境变量。

### 测试

新增/调整：`tests/test_settings_env_precedence.py`（4 项，用子进程分别验证项目覆盖工作区、进程环境覆盖两者、项目缺失时回落到工作区、都缺失时不设置）；`tests.test_model_compatibility` 新增 1 项（探针 URL/凭据头与 `ModelEndpoint` 一致，末尾 `/` 被规范化，源码中不再拼接 URL）；`tests.test_model_gateway_port` 删除旧适配器测试 1 项（20 → 19），并补充末尾 `/` 断言。

| 检查 | 结果 |
| --- | --- |
| WSL 定向 19 模块（Py 3.11，测试用 PIL 桩）：任务要求的 16 个模块 + 新优先级测试 + `test_module_boundaries` + `test_agent_tool_runtime_boundaries` | 251 项通过 |
| WSL 扩展 17 模块（执行/准备/Loop/Ready 调度、默认原生 Runtime、Memory、规划、综合、证据、Playbook、LoopGuard、`tests.system.test_model_governance` 等） | 183 项通过 |
| Windows 定向同 19 模块（Py 3.13） | 251 项：其中 11 个测试方法失败，共 19 个子测试 failure（`test_module_boundaries` 反斜杠路径断言）和 4 个 error（symlink WinError 1314）。HEAD 导出副本上跑同样 4 个模块，结果完全相同（failures=19、errors=4），属于既有环境问题 |
| Windows 扩展同 17 模块 | 183 项：8 个 error，都是临时 SQLite 清理时的 WinError 32；这 8 项在 HEAD 导出副本上同样报错 |
| `scripts/check_modularization_boundaries.py` | 272 文件 / 0 错误（两端） |
| `scripts/check_module_boundaries.py` | 通过（两端） |
| Ruff check（WSL，14 个改动文件 + 1 个新文件） | 改动文件共 47 项，HEAD 同样路径也是 47 项，规则和数量逐文件一致，没有新增；新文件通过 |
| Ruff format | `gateway.py`、`test_model_gateway_port.py` 和新测试文件通过；另外 12 个改动文件在 HEAD 就未按 ruff 格式化，本次没有整体重排，新增代码沿用各文件原有写法 |

没有调用真实模型服务，也没有运行性能门、浏览器或覆盖率。

### 台账计数

| 项 | 前（`1c61601`） | 后 |
| --- | --- | --- |
| 受管文件 | 278 | 272（244 Python / 28 静态） |
| 依赖债务 | 29 | 29（5 条 exit_task 由 MOD-012 改为 MOD-015） |
| 兼容入口 | 13 | 7 |
| 兼容消费记录 | 99 | 91 |
| DB 候选 | 26 | 26 |

剩余 7 个兼容入口为 `service.run_agent`、`service._run_agent_impl`、`service._coordinator_dependencies`、`service.TOOLS`、`service.TOOL_HANDLERS`、`service` 模块和 `agent_runtime.compatibility`。按台账，它们在 015b～015e 迁移相应依赖后再处理；`run_agent` 是公开 API，会保留。

### 回滚

撤销 015a 的改动即可：恢复 6 个已删除的模块、两个 synthesis facade、`ClientModelSession` 和 `state.endpoint`，同时恢复台账与测试。不涉及数据迁移。只回滚配置优先级时，交换 `settings.py` 中两行 `_load_env` 的顺序，并删除 `tests/test_settings_env_precedence.py`。

## 015b：依赖组/状态类型化与 EventSink

### 范围

只做类型化和一个审计适配器：依赖组、运行状态和 Loop 上下文的字段从 `Any` 换成结构化 Protocol / `Callable` / 领域类型；新增把 `RuntimeEvent` 写成审计记录的 `AuditEventSink`。不改任何运行时行为：事件名与字段、进度 payload、重试/健康/回退判定、live patch 语义、`__getattr__` 动态导出和默认值全部不变。不涉及 Loop 拆分（015c）和存储/身份注入（015d）。

### 变更

| 项 | 变更 |
| --- | --- |
| 新模块 `app/agent_runtime/ports.py` | Runtime 侧类型端口集合。`runtime_checkable` 的 `RuntimeSettings` / `RuntimeModelConnection` 是只读结构化视图，只列出 Runtime 实际读取的字段；`core.settings.Settings` / `ModelConnection` 结构化满足它们。边界检查器禁止 `agent_runtime` 导入 `app.core.settings`（`TYPE_CHECKING` 下也算），所以不能用 `Settings` 本身。22 个可调用 Protocol（`AuditEmitter`、`ProgressSink`、`AnswerStreamer`、`AgentRunPreparer`、`EvidenceValidator`、`AnswerContractFactory`、`OfflineAnswerer`、模型健康四件、`ReadyPlanExecutor`、`ReadyUnavailableResultBuilder`、`ReadySynthesisRequester`、`GeneralKnowledgePrefetcher`、`ResultBuilder`、`AgentLoopRunner`、`LegacyAnswerSynthesizer`、`SubmissionSynthesizer`、`SynthesisCorrectionRequester`、`ToolRunFactory`、`OfflineToolRunner`）加 `ToolRunBindings`（ready/loop 两个只读属性）；其余依赖用 `Callable` TypeAlias（`Clock`、`SettingsProvider/Resolver`、消息构造器、谓词、归一化等）。`JsonObject = dict[str, Any]`、`ObservationList` 两个别名。所有领域类型只在 `TYPE_CHECKING` 下导入，导入该模块只加载标准库。调用方总是按位置传的参数声明为 positional-only，旧 facade 和测试替身无论参数名如何都满足端口；每个端口只列出 Runtime 消费者实际传入的参数 |
| `dependencies.py` | 58 个依赖组字段全部类型化（如 `settings_type: type[RuntimeSettings]`、`model_gateway: ModelGatewayPort`、`tools: list[JsonObject]`、`tool_run_factory: ToolRunFactory \| None`），经 `TYPE_CHECKING` + `from __future__ import annotations`，运行时零导入变化；字段名、顺序、默认值、`bind_compatibility_globals` 与 `__getattr__` 快照不变 |
| `coordinator_state.py` | `CoordinatorRunState` 字段类型化（`settings: RuntimeSettings \| None`、`selected_playbook: DomainPlaybook \| None`、`tool_run: ToolRunBindings \| None`、`evidence_observations: list[EvidenceObservation]` 等）；`CoordinatorStateView.__setattr__` 的 value 标为 `object`。字段名、视图分组和 `__post_init__` 不变 |
| `execution/agent_loop.py` | `AgentLoopContext` 字段类型化，仅注解；循环逻辑、重试/健康/回退路径不变 |
| `telemetry.py` | 新增 `RUNTIME_STAGE_AUDIT_EVENT = "runtime_stage_completed"`、`runtime_event_audit_fields(event)` 和 `AuditEventSink(emit)`。字段映射固定顺序：公共 `call_id`、`kind`、`status`（枚举值）、`runtime_event_schema_version`；`model_response` 加 `prompt_tokens` / `completion_tokens` / `total_tokens`；`tool_result` 加 `tool_name`、`row_count`、`execution_state`（枚举值）。审计信封保留的 `schema_version`、`run_id` 由信封写，事件名和 `run_id` 按 `audit.emit` 的前两个位置参数传入。`AuditEventSink` 是 `EventSink` 适配器，异常向发布方传播（与每个 `EventSink` 一致）；只有显式装配才会用它，默认 coordinator 路径未接入，其审计流不变 |
| `bootstrap/default_coordinator_assembly.py` | 仅注解：返回值标为 `CoordinatorDependencies`，`tool_run_factory` 返回 `DefaultRunTools`，`offline_tool_runner` 参数/返回类型化 |
| `scripts/build_portable_unit.py` | `imported_app_modules` 从 `ast.walk` 改为 `NodeVisitor`，跳过 `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` 分支（这些导入运行时从不执行，便携包不需要提供目标模块）；运行时导入的校验逻辑不变。`dispatcher_pilot` 等清单文件列表不变 |
| 台账 | `mod_003_boundaries_v1.json` 登记 `app/agent_runtime/ports.py`（runtime / platform_core），受管文件 272→273；新增兼容消费记录 `tests/test_runtime_dependency_types.py` → `app.agent_runtime.service`（import），消费记录 91→92；兼容入口 7、债务 29、DB 候选 26 不变 |

### 兼容说明

- 剩余 `Any` 只有三处有意保留：`JsonObject` 的 JSON 值（`dict[str, Any]`）、`AuditEmitter` 的 `**fields: Any`（审计透传字段）、`CoordinatorStateView.__getattr__ -> Any`（动态视图）。测试里的 Any 守卫允许列表为空，防止回流。
- 端口是结构化的：旧装配（`legacy_agent_assembly`）产出的真实依赖快照经 58 字段逐一绑定验证满足注解；`Settings`/`ModelConnection` 经 `isinstance` 验证满足 `RuntimeSettings`/`RuntimeModelConnection`。
- 不改任何公开入口；外部消费者无感知。

### 测试

新增 `tests/test_runtime_dependency_types.py`（16 项：Any 守卫与负面对照、字段顺序锁定、`get_type_hints` 可解析、22 个端口签名形状、真实 Settings 结构化满足、真实 service 快照 58 字段逐一满足、`AgentLoopContext` 提示与依赖组一致、`AuditEventSink` 映射/失败工具字段/异常传播/与真实 `audit.emit` 端到端、未接入默认路径、新进程导入只多出 `app.agent_runtime.ports` 且不拉入 httpx/sqlite3/`app.core`/model_gateway/persistence/telemetry）；`tests/test_portable_units.py` 新增 1 项（`TYPE_CHECKING` 导入不计为未声明 app 导入，`else` 分支仍计入）。

| 检查 | 结果 |
| --- | --- |
| WSL 定向 46 模块（Py 3.11，测试用 PIL 桩；含全部 Runtime 行为、边界、台账、便携切片与 bundle 安装套件） | 433 项全部通过 |
| Windows 定向同 46 模块（Py 3.13） | 433 项：failures=26、errors=18，全部为既有 Windows 环境问题且与 HEAD 基线（416 项：failures=28、errors=18）逐项一致——`test_module_boundaries` 反斜杠路径断言 19 个子测试 failure、symlink 权限 WinError 1314 ×5、临时 SQLite 清理 WinError 32 ×11、bundle 安装子进程 GBK 输出 UTF-8 解码失败/输出为空致 JSONDecode ×3、设备健康便携文件名含 `?` ×1、空环境 Winsock 初始化失败（WinError 10106）便携切片 ×5。HEAD 上多出的 2 个 `test_modularization_boundaries` failure（台账未登记 ports.py）由本批台账登记修复 |
| `scripts/check_modularization_boundaries.py` | 273 文件 / 0 错误（两端） |
| `scripts/check_module_boundaries.py` | 通过（两端） |
| Ruff check（WSL，9 个改动/新增文件） | 全部通过，与 HEAD 同路径结果一致 |
| Ruff format | 新文件 `ports.py`、`test_runtime_dependency_types.py` 0 偏差；共享文件与 HEAD 计数一致（`agent_loop.py` 580→576 略降），未整体重排任何既有文件 |

没有调用真实模型服务，也没有运行性能门、浏览器或覆盖率。

### 台账计数

| 项 | 前（015a 后） | 后 |
| --- | --- | --- |
| 受管文件 | 272 | 273（245 Python / 28 静态） |
| 依赖债务 | 29 | 29 |
| 兼容入口 | 7 | 7 |
| 兼容消费记录 | 91 | 92 |
| DB 候选 | 26 | 26 |

### 回滚

删除 `app/agent_runtime/ports.py`、`tests/test_runtime_dependency_types.py` 和 `telemetry.py` 的三个新增符号，恢复 `dependencies.py`、`coordinator_state.py`、`agent_loop.py`、`default_coordinator_assembly.py` 的 `Any` 注解、`build_portable_unit.py` 的 `ast.walk` 实现、台账登记和 `test_portable_units.py` 的新增测试。不涉及数据迁移。

## 015c：Loop 职责拆分

### 范围

只做纯重构：把 `run_agent_loop`（原单函数约 700 行）按职责拆成 6 个模块，`agent_loop.py` 只保留 `AgentLoopContext` 和一个短编排函数。事件名/字段/顺序、进度 payload 及顺序、追加的消息、重试与健康记录、本地回退、用量累计、返回的结果 dict、异常（含 `CancelledError` 和裸 `raise` 重抛）以及 dispatch_binding（MOD-014 注入路径）与旧路径的差异全部不变。不涉及存储/身份注入（015d）。

### 模块划分

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `execution/agent_loop.py` | 196（原 812） | `AgentLoopContext`（字段不变）、`_resolve_dispatch_binding`（绑定一致性与 `validate_loop_binding`）、`run_agent_loop` 编排：打开会话 → 每轮“构建请求 → 模型调用 → 用量/分类/追加 assistant → 文本答案 / 提交 / 工具轮 + 轮末校验” → 轮次上限终止。`LOOP_SYNTHESIS_MAX_TOKENS` 仍可从此处导入 |
| `execution/loop_state.py` | 67 | `LoopRunState`（slots dataclass）、`sync_to_context`、`build_result`、`add_usage` |
| `execution/loop_request.py` | 83 | 最后一轮保留、仅综合系统消息、阶段进度、请求 payload（tools / tool_choice / max_tokens，绑定 `tools_json` 解析失败抛 `RuntimeContractError`） |
| `execution/loop_model_call.py` | 270 | 带重试的模型调用：`model_call_started/finished`、`decide_model_failure`、健康失败记录、本地回退（`native_fallback` 或 `offline_answer`）、裸 `raise`、重试延迟/进度/`asyncio.sleep`、成功事件、`thinking_answer_effective`、健康成功/恢复；成功时返回 `ModelTurn`（assistant、usage、response_id、stream_state、model_started），回退时返回结果 dict |
| `execution/loop_answer.py` | 297 | 无工具调用的文本答案收尾；`submit_analysis` 提交（非法 JSON → `request_synthesis_correction` 纠正 → salvage → 降级旧答案）；轮次上限终止答案 |
| `execution/loop_tool_round.py` | 291 | Dispatcher 工具轮（F）与旧工具轮（G：`begin_round`/`finish_round`、blocked/ok/error、知识过滤、`EvidenceObservation`） |
| `execution/loop_round_validation.py` | 114 | 轮末证据校验、进入综合、知识回退状态、答案契约、校验/综合系统消息、校验进度、`knowledge_fallback_enabled`、`loop_guard_round_finished`、注入路径同步 context |

### LoopRunState

字段：`evidence_validation`、`answer_contract`、`knowledge_fallback`、`fallback_announced`、`applied_synthesis_reason`、`health`、`thinking_answer_effective`（初值 False）。它是一次 Run 内这些可变事实的唯一持有者（§5.5），运行开始时从 context 快照一次，之后各模块只读写 state，不再读 context 上的这些字段。原来 `_build_result` 和轮末两处重复的 context 回写合并为 `sync_to_context(context)`，调用点不变：仅在 dispatch_binding 非空时，于每个工具轮末尾和构建结果之前写回；本地回退和异常路径照旧不写回。messages/trace/sources/evidence_observations/total_usage 仍是 context 上的同一对象，原地修改。模块级没有可变状态。

### 补丁点与语义保持

- `time.perf_counter`、`asyncio.sleep`、`traceback.format_exc` 仍以模块属性调用（`time.`/`asyncio.`/`traceback.`），对 `asyncio.sleep`、`time.perf_counter` 的全局 patch 继续生效；仓库内没有测试 patch `agent_loop` 命名空间里的这些名字。`traceback.format_exc()` 仍在原 `except` 块内调用；traceback 文本中的文件名会变成新模块，属预期差异，不在比较范围内。
- 本地回退仍在 `except` 块内执行，回退中抛出的异常仍以原异常为 `__context__`；非回退路径仍在 `except` 块内裸 `raise`。
- 提交修复使用最后一次成功尝试的 `usage` 和 `model_started`（由 `ModelTurn` 携带），与原局部变量语义相同。
- 公开入口不变：`run_agent_loop(context, *, dispatch_binding=None)` 与 `AgentLoopContext` 仍归 `agent_loop` 所有，`execution/__init__.py` 惰性导出、`test_tool_dispatcher_boundaries` 的名称→模块映射不变。

### 等价证据

- 新增 `tests/agent_loop_split_scenarios.py`：全部协作者为记录型替身（真实 `ToolLoopGuard`、`ExecutionPlan`、`EvidenceObservation`，注入路径复用 `tests/test_loop_dispatcher.py` 的 Dispatcher 夹具），按发生顺序记录 emit 事件与字段、notify payload、模型请求与 stream_state、`asyncio.sleep` 延迟、纠正请求、合成调用、`build_result` 时的 context 同步快照，以及最终 messages/trace/sources/观测/用量/守卫摘要/会话开闭和返回值或异常。只剔除 `duration_ms`、`elapsed_ms`、`traceback`。
- 黄金样本 `tests/fixtures/agent_loop_split_golden.json` 用改动前代码录制，并在 `git archive HEAD`（`f9c3c96`，原 812 行 `agent_loop.py`）导出副本中独立重录，字节一致；同一代码连续录制两次也字节一致。
- 37 个场景：文本答案（普通/空内容/流式指标/通用知识披露/对话无工具/DeepSeek thinking）、旧工具轮（ok + 重复参数 blocked + 工具异常 + 知识过滤 + 混合 submit 拒绝 + 参数非法 JSON + 无 id/无名称 unplanned → 第二轮仅综合 + 知识回退公告）、无进展终止、轮次上限、`submit_analysis`（合法/空对象/非对象 JSON/截断 → 纠正接受/纠正被拒 → salvage/无 token 上限 → 降级/工具轮后提交）、503 重试后成功、持续失败本地回退（健康开/关、主恢复试探不重试）、`native_fallback`（旧路径/注入路径）、不可重试错误重抛、已输出正文后失败重抛、第二轮失败重抛、流中取消（旧路径/注入路径）、注入路径（工具轮 + 文本、显式参数传绑定、提交、非法提交降级、required 契约文本、失败重抛、失败记录健康、绑定不一致、绑定校验失败）。新代码 37/37 与黄金样本逐项一致。
- 变异自检：把 `sync_to_context` 改为空操作，6 个注入路径场景立即与黄金样本不符，说明比较能发现回写时机变化。
- 取消：`tests/test_agent_loop_split.py` 用真实 `task.cancel()` 在第二轮流中取消，验证 `CancelledError` 传播、会话关闭、无健康失败记录、无 `build_result`，注入路径 context 只保留第一轮末的同步值，旧路径 context 完全不被写回。

### 测试

新增 `tests/test_agent_loop_split.py`（9 项：行数预算与委托、公开名称归属与签名、`LoopRunState` 字段与 AST 级“唯一回写点/无模块级可变状态”守卫、新模块不含 httpx/AsyncClient/URL/凭据头、计时/sleep/traceback 调用形式、黄金覆盖、37 场景逐项一致、两种取消）。`tests/test_model_gateway_port.py` 的 `GATEWAY_CALLERS` 静态清单追加 6 个新模块，`import httpx` 检查扩展到全部 Loop 模块；9 个便携切片测试（skill_releases、production_reports、process_diagnostics、operational_reports、named_queries、loop_dispatcher、litho_cpk、knowledge_search、enterprise_tools）的 blocked 元组在 `agent_loop` 之外同时屏蔽 6 个新模块。便携切片和 `evaluations/mod_0xx_*.json` 文件清单本来就不含 `agent_loop.py`，所以没有改动清单或计数。

| 检查 | 结果 |
| --- | --- |
| WSL 定向 34 模块（Py 3.11，测试用 PIL 桩；新测试 + 任务要求的 21 个模块 + 9 个便携切片 + `test_modularization_reference`、`test_agent_tool_runtime_boundaries`、`test_tool_sources_portable`） | 339 项全部通过 |
| Windows 同 31 模块（Py 3.13，不含后 3 个） | 320 项：failures=23、errors=12，全部是既有 Windows 环境问题，与 HEAD 导出副本逐项一致：`test_module_boundaries` 反斜杠路径 19 个子测试、便携切片子进程 GBK/UTF-8 解码与非零退出 ×7、临时 SQLite 清理 WinError 32 ×7、symlink WinError 1314 ×2。HEAD 副本上 `tests.system.test_model_governance` 因导出不含未跟踪的参考库而无法启动，工作树上 17 项通过 |
| `scripts/check_modularization_boundaries.py` | 279 文件 / 0 错误（两端） |
| `scripts/check_module_boundaries.py` | 通过（两端） |
| Ruff check（WSL，8 个新文件 + 11 个改动文件） | 全部通过；HEAD 同路径也全部通过 |
| Ruff format | 新文件和重写后的 `agent_loop.py` 已按 ruff 格式化（`agent_loop.py` 偏差 576→0）；其余 10 个改动测试文件偏差与 HEAD 一致（0） |

没有调用真实模型服务，也没有运行性能门、浏览器或覆盖率。

### 台账计数

| 项 | 前（015b 后） | 后 |
| --- | --- | --- |
| 受管文件 | 273 | 279（251 Python / 28 静态；6 个新模块登记为 runtime / platform_core） |
| 依赖债务 | 29 | 29 |
| 兼容入口 | 7 | 7 |
| 兼容消费记录 | 92 | 92 |
| DB 候选 | 26 | 26 |

### 偏差

- 原实现中，若重试次数为负，重试循环一次也不执行，随后访问未赋值的局部变量，抛出 `UnboundLocalError`。新实现在这种情况下抛出 `RuntimeError("model retry loop ended without a model turn")`。`settings.py` 把 `model_max_retries` 限制在 0～4，主恢复试探固定为 0，所以生产配置走不到这条路径。
- `traceback` 字段里的文件名和行号会指向新模块。

### 回滚

删除 6 个新模块，用 `f9c3c96` 的版本恢复 `agent_loop.py`，再删除 `tests/test_agent_loop_split.py`、`tests/agent_loop_split_scenarios.py`、`tests/fixtures/agent_loop_split_golden.json`，并撤销 `mod_003_boundaries_v1.json` 中新增的 6 条登记以及 10 个测试文件的清单/blocked 改动。不涉及数据迁移。

## 015d：存储/身份依赖注入 Port

### 范围

只做依赖反转：会话、知识检索、模型注册/健康、个人知识和运行状态不再直接导入 SQLite 存储、执行存储、审计 sink、请求身份上下文和具体检索后端，改为依赖一个只含标准库的窄 Port，由装配层显式安装默认实现。SQL、表结构、返回值、事件名与字段、权限判断和 live patch 语义全部不变。`dependency_debt` 中 20 条存储/身份债务移除 15 条，另 5 条留待更合适的任务处理（见“延后的债务”）。不涉及 Skill 链路验收（015e）。

### 变更

| 项 | 变更 |
| --- | --- |
| 新模块 `app/core/storage_identity_ports.py` | 只导入标准库。`runtime_checkable` 的 `PrincipalView`（`tenant_id`、`user_id`、`roles`、`knowledge_owner_id` 只读属性，`core.identity.Principal` 结构化满足）；7 个 `Callable` 别名；冻结 dataclass `StorageIdentityBindings`（`session_factory`、`current_principal`、`defect_alias_reader`、`audit_emit`、`executions_for_session`、`reconcile_plan_steps`、`factory_search_backend_factory`）；`install_storage_identity(bindings, *, replace=True)`（类型不对抛 `TypeError`，`replace=False` 时保留已安装的绑定）、`configured_storage_identity()`、`storage_identity_bindings()`、`reset_storage_identity()`（仅供测试隔离）。未安装时 `storage_identity_bindings()` 抛 `StorageIdentityNotConfiguredError`（`RuntimeError` 子类），消息里写明安装函数全名。导入时不安装任何绑定 |
| 新模块 `app/bootstrap/storage_identity_assembly.py` | 默认绑定 `DEFAULT_STORAGE_IDENTITY_BINDINGS`。每个绑定在调用时才读取具体模块属性（`database.db_session()`、`identity.current_principal()`、`database.get_active_defect_aliases()`、`audit.emit`、`execution_store.executions_for_session/reconcile_plan_steps`、`sqlite_backend.SqliteFactorySearchBackend()`），所以对这些具体模块的 patch 照样能传到所有消费者。`install_default_storage_identity()` 以 `replace=False` 安装，可重复调用，不覆盖自定义装配 |
| 新模块 `app/core/model_capabilities.py` | `MODEL_CAPABILITY_DEFAULTS`、`normalize_capabilities` 从 `model_gateway/registry.py` 原样移入。`registry` 从这里导入并继续导出同一对象；`persistence/database.py` 的迁移函数原来在函数内惰性导入 `model_gateway.registry`，现改为顶层导入 `core.model_capabilities`，`database → registry` 的反向边因此消失 |
| `search_query.sqlite_fts_query` | 纯函数从 `sqlite_backend.py` 原样移到 `search_query.py`；`sqlite_backend` 与 `rag` 都从这里导入，三处是同一对象，`rag → sqlite_backend` 边消失 |
| `conversation/sessions.py` | `db_session`、`executions_for_session`、`reconcile_plan_steps`、`current_principal` 改为同名模块级委托函数，签名不变，调用时读取已安装的绑定 |
| `knowledge/rag.py` | `get_active_defect_aliases`、`current_principal` 改为同名委托函数；`patch.object(rag, ...)` 仍然生效，因为 rag 内部照旧按模块全局名调用 |
| `knowledge/search_registry.py` | `"sqlite"` 分支改为调用 `factory_search_backend_factory()`；错误信息和其他后端名的处理不变 |
| `model_gateway/health.py`、`registry.py`、`telemetry/runtime_status.py` | `db_session`（registry 另有 `current_principal`）改为同名委托函数；`Principal` 注解换成 `PrincipalView` |
| `personal_knowledge_runtime/service.py` | `db_session`、`emit` 改为同名委托函数；`_ingestion/_document/_search_dependencies()` 照旧在调用时读取模块全局，`patch("...service.db_session")` 不受影响 |
| 装配入口 | `app/api/runtime_dependencies.py`（`app.main` 经此导入）和 `app/bootstrap/default_coordinator_assembly.py`（`app.agent_runtime.service` 经 compatibility 导入）在模块级调用 `install_default_storage_identity()`。所以启动 HTTP 服务和直接在 Python 里调用 `run_agent` 都与改动前一样可用 |
| 脚本与测试 | `scripts/prepare_ci_data.py`（`ensure_model_catalog()` 前）和 `scripts/evaluate_rag.py`（`evaluate()` 开头）显式调用安装函数；`tests/test_model_publication.py`、`tests/test_factory_search_backend_boundary.py` 不经过 `app.main`，所以加了 `setUpModule` 安装默认绑定 |
| 台账 | `mod_003_boundaries_v1.json`：登记 3 个新文件（两个 `core` 模块为 core_contracts_configuration / platform_core，装配模块为 application_bootstrap / application_bundle），受管文件 279→282；删除 15 条债务，5 条改 exit_task 并在 reason 末尾注明“Deferred from MOD-015d: …”；`database_candidates` 按检查器实算重写（`personal_knowledge_runtime/service.py` 退出，`bootstrap/storage_identity_assembly.py` 加入，仍为 26）；`database_ledger.sources` 相应增删，sessions/health/registry/runtime_status 的初始化说明改为 Port 写法，health/registry 的 exit_task 由 MOD-012 改为 MOD-015。`module_boundaries_v1.json` 删除 5 条已不存在的例外边（37→32） |

已移除的 15 条债务：

| 来源 | 目标 |
| --- | --- |
| `conversation.sessions` | `persistence.database`、`persistence.execution_store`、`core.identity` |
| `knowledge.rag` | `persistence.database`、`core.identity`、`knowledge.sqlite_backend` |
| `knowledge.search_registry` | `knowledge.sqlite_backend` |
| `model_gateway.health` | `persistence.database` |
| `model_gateway.registry` | `persistence.database`、`core.identity` |
| `persistence.database` | `model_gateway.registry` |
| `personal_knowledge_runtime.service` | `telemetry.audit`、`persistence.database` |
| `telemetry.runtime_status` | `persistence.database`、`core.identity` |

### 延后的债务

| 债务 | 新 exit_task | 原因 |
| --- | --- | --- |
| `manufacturing.enterprise_data → core.identity` | MOD-008 | 过渡期旧 facade。MOD-009 要求先审查保留的 API/Python/live patch 消费者才能删这条边，这属于 MOD-008 旧路径退出 |
| `manufacturing.reports → persistence.database` | MOD-008 | 过渡期旧 facade，有 4 处 `db_session` patch 点；`database_ledger` 把旧路径记为保留，随 MOD-008 旧路径退出一起处理 |
| `model_gateway.compatibility → memory_system.context.history`、`→ memory_system.context.protocol` | MOD-025 | 要去掉这两条边，只能改公开兼容性探针的签名/行为，或把 context_memory 协议逻辑移进 core，都超出“零行为变化”的范围 |
| `persistence.execution_store → core.identity` | MOD-021 | REF-027 例外要求执行存储的身份锚点保持公开；稳定的调用身份归 MOD-021 |

### 补丁点与语义保持

逐项验证过的 patch 点（新增测试和既有测试都覆盖）：

- 具体模块：`patch("app.persistence.database.db_session")` 同时传到 sessions、health、个人知识 service（registry、runtime_status 走同一个绑定）；`patch("app.core.identity.current_principal")` 和 `set_principal(...)` 上下文传到 rag、sessions、registry 与 `sessions._scope()`；`patch("app.persistence.database.get_active_defect_aliases")` 传到 rag；`patch("app.knowledge.sqlite_backend.SqliteFactorySearchBackend")` 传到 `search_registry.get_factory_search_backend("sqlite")`。
- 消费者模块：`patch("app.model_gateway.health.db_session")`（`tests.test_model_health`）、`patch.object(health, "db_session")`（`tests.test_model_gateway_module_boundaries`，README 也写了这种用法）、`patch("app.personal_knowledge_runtime.service.db_session")`（`tests.test_personal_knowledge`、`tests.test_personal_knowledge_module_boundaries`，并经 `_document_dependencies()` / `_search_dependencies()` 取到）、`patch.object(rag, "current_principal" / "get_active_defect_aliases" / "get_factory_search_backend" / "get_factory_catalog_backend")`（`tests.test_knowledge_search_adapters`、`tests.test_factory_search_backend_boundary`）、`patch("app.knowledge.rag.get_active_defect_aliases")`（`tests.system.test_knowledge_uploads`）、`patch.object(runtime_status, "_users")`（未改动）。
- 改动前后对象相同：`registry.normalize_capabilities`、`registry.MODEL_CAPABILITY_DEFAULTS`、`sqlite_backend.sqlite_fts_query`、`rag.sqlite_fts_query`。

### 兼容说明

- 不经过 `app.main` 或 `app.agent_runtime.service` 而直接调用上述消费者的代码（独立脚本、单独导入 `sessions`/`registry`/`rag` 的测试等），需要先调用一次 `app.bootstrap.storage_identity_assembly.install_default_storage_identity()`；否则会立即得到写明安装函数的 `StorageIdentityNotConfiguredError`，不会悄悄打开数据库。仓库内的这类消费者已全部补上。
- 要替换存储或身份实现，可以在装配根调用 `install_storage_identity(StorageIdentityBindings(...))`；之后默认安装函数不会覆盖它。
- 公开函数名、签名和返回值不变；`Principal` 仍可传给所有标注为 `PrincipalView` 的参数。

### 测试

新增 `tests/test_storage_identity_ports.py`（10 项）：两个 core 模块在新进程中只加载标准库；12 个委托入口在未安装时都抛出带安装函数名的错误，且导入消费者不会拉入 `app.api.runtime_dependencies`；导入 `app.main` 和 `app.agent_runtime.service` 都会安装默认绑定；默认安装可重复且不覆盖自定义绑定、错误类型抛 `TypeError`；替身绑定在调用时传到 sessions/registry/runtime_status/个人知识/rag/search_registry/health；`Principal` 满足 `PrincipalView`；移动的纯函数在各处是同一对象；AST 守卫确认 8 个文件不再导入已移除的目标；具体模块 patch 穿透默认绑定；消费者模块 patch 仍然生效。

| 检查 | 结果 |
| --- | --- |
| WSL 全部 168 个测试模块逐模块运行（Py 3.11，测试用 PIL 桩，导出副本带 `data/departments`），与 HEAD 导出副本（167 个模块）对照 | 1290 项（HEAD 1280 项，差值为新增的 10 项）。158 个模块通过；10 个模块的失败在 HEAD 上同名同数，全部是环境问题：缺 PIL/docx/pypdf（`test_ocr`、`test_ocr_assets`、`test_ocr_evaluation`、`test_personal_knowledge_module_boundaries`、`tests.system.test_knowledge_uploads`、`test_tool_contracts`、`test_tool_registry`、`test_modularization_fixture_clock` 中的子进程）和 `test_startup_script`（8 failures + 1 error）。没有新增失败 |
| Windows 定向 43 模块（Py 3.13，`.venv-win`；新测试、所有导入改动模块的测试、边界/台账/便携切片和 5 个系统测试模块），与 HEAD 导出副本（同样带 `data/departments`）对照 | 440 项：failures=20、errors=9，全部是既有 Windows 环境问题，测试名与 HEAD 一致：`test_module_boundaries` 反斜杠路径 19 个子测试、`tests.system.test_data_reports` 的 WAL/DELETE 日志模式断言 1 个、symlink WinError 1314 ×2、临时 SQLite 清理 WinError 32 ×5（其中 `test_default_native_runtime` 3 个；HEAD 上该模块是 4 个，具体哪几项出错每次不同）、`test_personal_job_sse` 无法打开数据库文件 ×1、知识检索便携切片子进程 GBK/UTF-8 解码 ×1。HEAD 副本 431 项：failures=20、errors=11，多出的 2 个 error 是缺少新测试模块和上述 WinError 32 的波动。`tests.system.test_knowledge_uploads` 在 Windows 两端都通过（14 项） |
| `scripts/check_modularization_boundaries.py` | 282 文件 / 0 错误 |
| `scripts/check_module_boundaries.py` | 通过 |
| Ruff check（WSL，4 个新文件 + 16 个改动的 Python 文件） | 新文件通过；改动文件共 20 项，逐文件与 HEAD 相同，没有新增 |
| Ruff format | 4 个新文件 0 偏差；改动文件的偏差行数都不高于 HEAD（`rag.py` 42→37、`registry.py` 93→89，其余相同），没有整体重排既有文件 |

没有调用真实模型服务，也没有运行性能门、浏览器或覆盖率。

### 台账计数

| 项 | 前（015c 后） | 后 |
| --- | --- | --- |
| 受管文件 | 279 | 282（254 Python / 28 静态） |
| 依赖债务 | 29 | 14（移除 15 条；5 条存储/身份债务改到 MOD-008 ×2、MOD-025 ×2、MOD-021 ×1） |
| 兼容入口 | 7 | 7 |
| 兼容消费记录 | 92 | 92 |
| DB 候选 | 26 | 26（`personal_knowledge_runtime/service.py` 退出，`bootstrap/storage_identity_assembly.py` 加入） |
| `module_boundaries_v1.json` 例外 | 37 | 32 |

### 偏差

- 原计划只在 `app.main` 的装配路径安装默认绑定。逐模块对照时发现 `tests.test_agent_preparation_boundaries` 不经过 `app.main`、直接导入 `app.agent_runtime.service` 跑一次运行，会在 `effective_agent_settings` 取身份时失败。直接调用 `run_agent` 是公开用法，所以在 `default_coordinator_assembly.py` 也加了模块级安装（同属 bootstrap，不新增跨模块边），并在新测试里覆盖。
- `scripts/evaluate_ocr.py`、`scripts/run_live_e2e.py`、`scripts/run_browser_test_server.py` 和 MOD-008 性能夹具 worker 没有加安装调用：前两者用到的函数（`_extract_sections`、`_decode_model`）不访问绑定，浏览器测试服务器导入 `app.main`，性能夹具经 `app.agent_runtime.service` 安装；`tests.test_default_performance_fixture` 在两端都通过。

### 回滚

删除 3 个新模块和 `tests/test_storage_identity_ports.py`，恢复 10 个消费者模块原来的直接导入（`registry` 恢复 `MODEL_CAPABILITY_DEFAULTS`/`normalize_capabilities` 定义，`sqlite_backend` 恢复 `sqlite_fts_query` 定义，`database.py` 恢复函数内惰性导入），删除 `runtime_dependencies.py`、`default_coordinator_assembly.py`、两个脚本和两个测试里的安装调用，并恢复两份台账。不涉及数据迁移。
