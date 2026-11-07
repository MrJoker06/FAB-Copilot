# MOD-015：Runtime 收口、依赖类型化与兼容退出

日期：2026-11-07。基线：`1c61601`（MOD-012）。状态：已验证（2026-11-07；015a～015e 全部验证）。

## 分批

用户确认把 MOD-015 拆成 5 个批次，每批独立验证，不一次性改写 Runtime：

| 批次 | 内容 | 状态 |
| --- | --- | --- |
| 015a | 兼容台账收敛：删除纯转发模块与已无生产消费者的旧 facade，修正台账；附带配置优先级修复 | 已验证（2026-11-07） |
| 015b | 依赖组/状态类型化与 EventSink | 已验证（2026-11-07） |
| 015c | Loop 职责拆分 | 已验证（2026-11-07） |
| 015d | 存储/身份依赖注入 Port（含 model_gateway → persistence/identity/memory 的 5 条债务） | 已验证（2026-11-07） |
| 015e | Skill 启用/未启用完整链路，取消/异常无状态泄漏验收；剩余台账收尾 | 已验证（2026-11-07） |

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
| WSL 全部 168 个测试模块逐模块运行（Py 3.11，测试用 PIL 桩，导出副本带 `data/departments`），与改动前基线 `bff4eca` 导出副本（167 个模块）对照 | **历史统计待核实，原记录保留：**1290 项（基线 1280 项，差值为新增的 10 项）；原文记录 158 个模块通过、10 个模块失败，与基线同名同数，原因记为缺 PIL/docx/pypdf（`test_ocr`、`test_ocr_assets`、`test_ocr_evaluation`、`test_personal_knowledge_module_boundaries`、`tests.system.test_knowledge_uploads`、`test_tool_contracts`、`test_tool_registry`、`test_modularization_fixture_clock` 中的子进程）和 `test_startup_script`（8 failures + 1 error），并记载“没有新增失败”。列举的失败模块实际只有 9 个，详见下方复核说明 |
| Windows 定向 43 模块（Py 3.13，`.venv-win`；新测试、所有导入改动模块的测试、边界/台账/便携切片和 5 个系统测试模块），与 HEAD 导出副本（同样带 `data/departments`）对照 | 440 项：failures=20、errors=9，全部是既有 Windows 环境问题，测试名与 HEAD 一致：`test_module_boundaries` 反斜杠路径 19 个子测试、`tests.system.test_data_reports` 的 WAL/DELETE 日志模式断言 1 个、symlink WinError 1314 ×2、临时 SQLite 清理 WinError 32 ×5（其中 `test_default_native_runtime` 3 个；HEAD 上该模块是 4 个，具体哪几项出错每次不同）、`test_personal_job_sse` 无法打开数据库文件 ×1、知识检索便携切片子进程 GBK/UTF-8 解码 ×1。HEAD 副本 431 项：failures=20、errors=11，多出的 2 个 error 是缺少新测试模块和上述 WinError 32 的波动。`tests.system.test_knowledge_uploads` 在 Windows 两端都通过（14 项） |
| `scripts/check_modularization_boundaries.py` | 282 文件 / 0 错误 |
| `scripts/check_module_boundaries.py` | 通过 |
| Ruff check（WSL，4 个新文件 + 16 个改动的 Python 文件） | 新文件通过；改动文件共 20 项，逐文件与 HEAD 相同，没有新增 |
| Ruff format | 4 个新文件 0 偏差；改动文件的偏差行数都不高于 HEAD（`rag.py` 42→37、`registry.py` 93→89，其余相同），没有整体重排既有文件 |

2026-11-08 文档复核：上述 WSL 记录的失败模块总数与名单不一致，尚未找到对应轮次的原始逐模块统计，暂不能判断是 158/10 写错还是漏列一个失败模块。保留原记录并标记待核实，不凭 015e 的另一轮结果推改为 159/9；“没有新增失败”为原验收记载，本次未独立复核该结论。这项待核实记录不改变其他批次已记录的测试结果，也不代表已重新运行测试。

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

## 015e：Skill 启用/未启用完整链路与取消/异常无泄漏验收

### 范围

只做验收和收尾：用确定性内存替身把三条入口路径各跑一遍成功、取消、模型异常、工具/Skill 异常，检查每次失败后进程级运行状态不变、下一次运行与第一次干净运行一致；同时退出 015 名下最后 3 条可在零行为变化内去掉的依赖债务，并把其余标为 MOD-015 的台账项逐条判定为“已修复”或“保留并改挂 MOD-027”。不改运行时代码路径、事件名与字段、公开入口或 live patch 语义。

三条路径：

| 路径 | 入口 | 夹具 |
| --- | --- | --- |
| 类型化应用，未启用 Skill | `assemble_agent(...)`（`skill_refs=()`）→ `AgentApplication.new_run` → `execute_dispatched_ready_plan` / `model_stage` + `execute_dispatched_loop_round` | 光刻 Cpk 命名计划的 4 个 Fake 工具绑定，外加一个计划不使用的 `get_defect_pareto` 绑定，用来观察 Skill 的能力收窄 |
| 类型化应用，启用 Skill | 同上，`skill_refs` 指向 `litho-cpk-diagnostic@1.0.0`；分别用文件根（`package_roots`，临时目录中的包副本）和发布库（`SkillReleaseStore` 发布并激活）两种配置 | 同上 |
| 旧入口 | 公开的 `service.run_agent`；Loop（CMP 划伤 Pareto，模型调用 `get_lot_identity`）、Ready（`查询 LOT-001 的批次信息`，6 个工具）、上下文解析（“继续”+ 带 `active_flow` 的历史，解析后走 Ready） | `tests.test_default_native_runtime` 的 SQLite 夹具库、`tests.test_model_gateway_port.ScriptedGateway`、Fake 知识 Port，patch `get_settings`/`HttpModelGateway`/`emit`/模型健康四件 |

没有调用真实模型服务或网络。

### 验收矩阵

新增 `tests/test_runtime_convergence_acceptance.py`（11 项，按路径 × Skill × 模式展开子测试）。

| 路径 | 成功 | 取消 | 模型异常 | 工具 / Skill 异常 |
| --- | --- | --- | --- | --- |
| 类型化，Skill 关闭，Ready | 4 步全部 ok，必需证据覆盖 3/3，来源含 `KB-LITHO-001`；不调用模型 | 第一个工具结束后在 notify 中挂起并取消：`CancelledError` 传播，Ready 收尾仍执行，本次 Run 的 projector 被 `clear()` 且无残留行数 | Ready 不调用模型：脚本里放一个会抛错的模型响应，计划照常完成、模型请求为 0 | `get_process_capability` 的适配器抛 `RuntimeError`：该步 error，依赖它的 3 步 blocked，trace 中不出现原始异常文本 |
| 类型化，Skill 关闭，Loop | 2 次模型调用，2 个 `model_response` 事件发布到 EventSink，4 个工具 ok | 第一次模型调用中取消：`CancelledError` 传播，模型调用已退出，守卫 0 次调用，适配器 0 次访问 | 模型抛 `RuntimeError`：原样传播，工具 0 次，EventSink 无新事件 | 同一适配器抛错：两个诊断工具 error，其余 ok |
| 类型化，Skill 开启（文件根 / 发布库），Ready | 同 Skill 关闭，另验证 Skill 元数据、`skill_context` 等于绑定的 `model_context`、首条为包内 `SKILL.md` | 同上 | 同上 | 同上；另有 Skill 重新校验失败：组装后禁用发布（发布库）或改动磁盘上的 `manifest.json`（文件根），`new_run` 抛 `AssemblyError`，且发生在预算工厂之前（没有新守卫），模型和适配器 0 次访问 |
| 类型化，Skill 开启，Loop | 同上，模型请求里 system 指令之后紧跟 Skill 上下文 | 同上 | 同上 | 同上 |
| 旧入口，Loop | `mode=deepseek`，1 个工具 ok，事件以 `agent_run_started` 开始、`agent_run_finished`（success）结束 | 模型流中取消：`CancelledError` 传播，网关会话打开 1 次、关闭 1 次，不发 `agent_run_finished` | 模型抛错：`RuntimeError` 从 `run_agent` 传出，`agent_run_finished` 为 `status=error` | `SQLiteNamedQueryAdapter.fetch` 抛错：工具结果为 `DATA_SOURCE_FAILED`，运行成功，答案不含原始异常文本 |
| 旧入口，Ready | `execution_mode=deterministic_ready_plan`，6 个工具 ok，1 次模型调用 | 综合调用中取消：同上 | 综合模型抛错：本地回退（`model_local_fallback_activated`），运行成功 | 同上，依赖步骤 blocked |
| 旧入口，上下文解析 | 解析为 `查询 LOT-001 的批次信息` 后走 Ready，2 次模型调用 | 上下文解析调用中取消：同上 | 上下文模型抛错：`resolution_state=unavailable`，发 `question_context_degraded`，`agent_run_finished` 的 `outcome=degraded`，运行成功 | 同 Ready |

每个场景结束后都检查：

- 没有残留任务（在事件循环内检查 `asyncio.all_tasks()` 只剩当前任务）；脚本模型 `active` 计数归零；旧入口网关会话打开次数等于关闭次数。
- 每次 Run 都有新的预算/守卫和 Dispatcher：两次运行的守卫、Dispatcher 都不是同一对象，`dispatcher.budget.guard` 是本次守卫，第二次的调用计数从 0 重新开始。
- 发布库状态（`store.states()`）和绑定的 Skill 快照、计划对象不变（同一对象）。
- `runtime_status` 不变：它只由 HTTP 聊天服务（`app/api/services/chat.py`、`chat_stream.py`）登记，`run_agent` 和类型化路径都不写入；测试对 `runtime_status._users` 做深拷贝比较。
- 身份 ContextVar 不变：`run_agent` 返回或抛出后，`current_principal()` 与调用前相同。
- `configured_storage_identity()` 仍是同一绑定对象；`service.TOOLS`、`service.TOOL_HANDLERS` 的对象身份和内容不变。
- 失败之后在同一应用/夹具上再跑一次，结果（trace、观测、来源、守卫摘要、调度事件、Runtime 事件、证据覆盖、Skill 元数据、`tools_json`、模型请求；旧入口为完整结果 dict 和事件序列）与第一次干净运行相等。比较前只去掉 `run_id`、`started_at`、`completed_at`、`traceback` 和所有 `*_ms` 计时字段。

Skill 能力收窄：Skill 关闭时，有效能力、Dispatcher 允许工具和 `tools_json` 都包含 5 个绑定；Skill 开启时只剩计划使用的 4 个，`get_defect_pareto` 不出现。

边界守卫（同一测试文件）：AST 检查 `decision_arbiter.py` 不导入 `memory_system`，`validator.py` 不导入 `planning_runtime` 或 `playbooks`；`ExecutionPlan`、`PlanStep`、计划范围、`DomainPlaybook`、`EvidenceRequirement` 的实例和 `ContextResolution` 字段在结构上满足新增的只读视图。

变异自检：分别注入三种泄漏，测试都能发现——跨 Run 复用同一个 Dispatcher（成功矩阵报错）、运行中向 `service.TOOLS` 追加条目（旧入口成功用例失败）、网关会话在取消时不关闭（取消用例 3 个子测试失败）。

### 泄漏排查结论

运行时代码中没有发现状态泄漏，没有需要修复的生产缺陷。记录三点观察：

- 旧入口被取消时，`run_agent` 不发 `agent_run_finished`，直接把 `CancelledError` 交给调用方。这是既有行为：HTTP 聊天服务负责取消后的终态和 `runtime_status` 收尾，本批不改。
- 测试中的 `ResourceWarning: unclosed database` 用 tracemalloc 追溯，24 个连接全部来自测试夹具（`tests/test_named_queries_adapters.py` 建库与 `tests/test_default_native_runtime.py` 的 `setUp` 中 `with sqlite3.connect(...)`，`with` 只提交不关闭），`app/` 内 0 个。Windows 上夹具清理的 WinError 32 也是这个原因；新测试在清理前调用 `gc.collect()`，夹具本身不在本批范围内，没有修改。
- Ready 路径对失败步骤的依赖步骤一律 blocked（Cpk 计划中其余 3 步都依赖 `get_process_capability`），Loop 路径没有依赖阻断；两者都是既有语义，已写进断言。

### 依赖债务退出

| 债务 | 处理 |
| --- | --- |
| `conversation.decision_arbiter → memory_system.contracts` | `decision_arbiter.py` 新增只读 `DecisionContext(Protocol)`（`applied`、`strategy`、`relation`、`confidence`、`source`、`intent_hint`），`arbitrate_decision(context: DecisionContext)`；删除对 `memory_system.contracts` 的导入。`ContextResolution` 结构化满足它 |
| `evidence.validator → manufacturing.playbooks`、`→ planning_runtime.contracts` | `validator.py` 新增 `PlanStepView`、`PlanScopeView`、`ExecutionPlanView`、`EvidenceRequirementView`、`PlaybookView` 五个只读 Protocol，14 处注解改用它们；删除两处导入。没有外部模块从 `validator` 导入被删的名字 |

两处都只改注解和导入，运行时行为不变；对应模块的既有测试（turn_decision、evidence_validator、named_planner_evidence、skill_evidence_policy、answer_synthesizer、两个模块边界测试等）全部通过。

### 台账收尾

收尾后，台账里没有任何 `exit_task` 仍为 MOD-015（只有 `legacy_sql_tool.exit_tasks` 历史列表中保留 "MOD-015" 一项作为经历记录）。

| 类别 | 已修复 | 保留并改挂 MOD-027 | 其他归属（015d 已改，未动） |
| --- | --- | --- | --- |
| 依赖债务 | 3 条（见上表） | 6 条：`agent_runtime.compatibility` → `manufacturing.processes`、`manufacturing.reports`、`bootstrap.legacy_agent_assembly`、`bootstrap.default_coordinator_assembly`；`tools.catalog → bootstrap.tool_catalog`；`tools.registry → bootstrap.tool_bindings` | 5 条：MOD-008 ×2、MOD-025 ×2、MOD-021 ×1 |
| 过渡文件归属 | — | 3 个：`agent_runtime/compatibility.py`、`agent_runtime/tools/catalog.py`、`core/settings.py` | — |
| 兼容入口 | — | 7 个：`service.run_agent`、`_run_agent_impl`、`_coordinator_dependencies`、`TOOLS`、`TOOL_HANDLERS`、`service` 模块、`agent_runtime.compatibility`；`target_checkpoint` 改为 “P5 Fake integration profile (MOD-027)” | — |
| `database_ledger.sources` | — | 19 条 exit_task；演示 seed 的初始化说明改为“retained at MOD-015 closeout and owned by MOD-027” | — |
| `legacy_sql_tool` | — | `exit_tasks` 追加 MOD-027，`replacement` 文字同步 | — |
| `module_boundaries_v1.json` 例外边 | — | 2 条 `exit_condition`（compatibility → legacy / default coordinator 装配）改为 MOD-027，并注明 “retained at MOD-015 closeout” | — |

保留的理由逐条写进台账的 reason/strategy：`run_agent` 是公开 API，它的逐次 live patch 命名空间、`_EXPORT_NAMES` 动态发布、`service.TOOLS`/`TOOL_HANDLERS` 对象身份和 `patch.dict` 语义都是有意保留的兼容契约；类型化 `AgentApplication` 路径已经不依赖它们。退掉这层 facade 必须改公开行为，归 MOD-027（内网分块搬迁与 Fake 集成 Profile，形成最小完整应用）。`core/settings.py` 仍是 live 命名空间里被 patch 的配置锚点，也被 REF-027 例外引用，配置加载与应用装配的分离同样归 MOD-027。

新测试导入并 patch `app.agent_runtime.service`，`compatibility_consumers` 按检查器实算追加 2 条（import、patch）。

### 测试

| 检查 | 结果 |
| --- | --- |
| WSL 全部 169 个测试模块逐模块运行（Py 3.11.15，测试用 PIL 桩，导出副本带 `data/departments`），与 HEAD 导出副本（168 个模块）对照 | 1301 项（HEAD 1290 项，差值为新增的 11 项）。160 个模块通过；9 个模块失败，失败模块和 failures/errors 计数与 HEAD 完全一致，全部是既有环境问题：`tests.system.test_knowledge_uploads`（errors=3）、`test_modularization_fixture_clock`（failures=1）、`test_ocr`（errors=1）、`test_ocr_assets`（errors=1）、`test_ocr_evaluation`（errors=2）、`test_personal_knowledge_module_boundaries`（errors=3）、`test_startup_script`（failures=8、errors=1）、`test_tool_contracts`（failures=1）、`test_tool_registry`（failures=1）。没有新增失败 |
| WSL 新测试连续重复运行 3 次 | 3 次均 11 项通过 |
| Windows 定向 37 模块（Py 3.13.5，`.venv-win`；新测试、两个改动模块的消费者测试、上下文/Memory、默认原生 Runtime、网关、Skill 装配/发布/光刻、Ready/Loop/工具 Dispatcher、Runtime/准备/执行边界、Loop 拆分、依赖类型、存储/身份 Port、聊天 API 边界、`tests.system.test_sessions_streaming`），与 HEAD 导出副本对照 | 412 项：failures=19、errors=9，全部是既有 Windows 环境问题，且模块和计数与 HEAD 一致：`test_module_boundaries` 反斜杠路径断言 19、临时 SQLite 清理 WinError 32 ×8（`test_default_native_runtime` 4、`test_ready_dispatcher` 2、`test_loop_dispatcher` 1、`test_named_planner_runtime` 1）、`test_modularization_boundaries` symlink WinError 1314 ×1。HEAD 副本另外 36 个模块共 401 项，failures=19、errors=9 完全相同；新测试模块在 HEAD 上因不存在而导入失败（errors=1） |
| Windows 新测试连续重复运行 3 次 | 3 次均 11 项通过 |
| `scripts/check_modularization_boundaries.py` | 282 文件 / 0 错误（两端） |
| `scripts/check_module_boundaries.py` | 通过（两端） |
| Ruff check（WSL） | 新测试文件通过；`decision_arbiter.py` 0 项、`validator.py` 1 项（既有 F402，HEAD 同样 1 项，只是行号随新增 Protocol 后移），没有新增 |
| Ruff format | 新测试文件已格式化、0 偏差；两个改动文件偏差行数与 HEAD 相同（129、284），没有整体重排 |

没有调用真实模型服务，也没有运行性能门、浏览器或覆盖率。

### 台账计数

| 项 | 前（015d 后） | 后 |
| --- | --- | --- |
| 受管文件 | 282 | 282（新增文件只在 `tests/`） |
| 依赖债务 | 14 | 11（移除 3 条；6 条改挂 MOD-027，5 条维持 015d 的归属） |
| 兼容入口 | 7 | 7（全部改挂 MOD-027） |
| 兼容消费记录 | 92 | 94 |
| DB 候选 | 26 | 26 |
| `module_boundaries_v1.json` 例外 | 32 | 32 |

### 偏差

- 类型化 Ready 路径不调用模型，所以“模型异常”一格验证的是“会抛错的模型从未被调用、计划照常完成”，而不是异常传播。
- 旧入口的“工具异常”用 patch `SQLiteNamedQueryAdapter.fetch` 模拟数据源失败。Skill 关闭时没有可重新校验的 Skill，这一格只有工具异常。
- 原计划要求在发现泄漏时最小修复并补回归测试。本批没有发现运行时泄漏，因此没有生产代码修复；测试夹具未关闭 SQLite 连接的问题只记录，不在本批修改。

### 回滚

删除 `tests/test_runtime_convergence_acceptance.py`，恢复 `decision_arbiter.py`、`validator.py` 的原导入和注解，并恢复两份台账（3 条债务、MOD-027 改挂和 2 条消费记录）。不涉及数据迁移。

## MOD-015 总结

MOD-015 分 5 批完成，每批独立验证：

| 批次 | 结果 |
| --- | --- |
| 015a | 删除 6 个转发/facade 模块、两个旧 synthesis facade、`ClientModelSession` 和 `state.endpoint`；修复配置优先级；兼容入口 13→7 |
| 015b | 依赖组、运行状态和 Loop 上下文全部类型化（`agent_runtime/ports.py`），新增 `AuditEventSink`；运行时零变化 |
| 015c | `run_agent_loop` 拆成 6 个职责模块，`LoopRunState` 成为唯一可变状态；37 个场景黄金样本逐项一致 |
| 015d | 存储/身份依赖注入 Port，移除 15 条债务，5 条延后到 MOD-008/025/021 |
| 015e | 三条路径 × Skill 开/关 × 成功/取消/模型异常/工具或 Skill 异常的无泄漏验收；移除最后 3 条可零行为变化退出的债务，其余 MOD-015 台账项改挂 MOD-027 |

| 项 | MOD-015 前（`1c61601`） | MOD-015 后 |
| --- | --- | --- |
| 受管文件 | 278 | 282 |
| 依赖债务 | 29 | 11（MOD-027 ×6、MOD-008 ×2、MOD-025 ×2、MOD-021 ×1） |
| 兼容入口 | 13 | 7（全部为保留的公开/兼容契约，归 MOD-027） |
| 兼容消费记录 | 99 | 94 |
| DB 候选 | 26 | 26 |

总方案对 MOD-015 的验收要求逐项对应：剩余依赖组类型化（015b）、Loop 职责拆分（015c）、事件与状态接口（015b 的 `AuditEventSink`、015c 的 `LoopRunState`）、启用/未启用 Skill 的完整链路 Fake 装配（015e）、旧协议兼容（每批的 live patch 与公开入口保持）、取消/异常无状态泄漏（015c 的真实取消测试和 015e 的验收矩阵）、兼容台账收敛（015a、015d、015e）。默认 HTTP 路径仍未启用 Skill；公司真实接入、Checkpoint 和整体迁移里程碑不因本项完成而完成。
