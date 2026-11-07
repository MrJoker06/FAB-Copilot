# MOD-015：Runtime 收口、依赖类型化与兼容退出

日期：2026-11-07。基线：`1c61601`（MOD-012）。状态：进行中（015a、015b 已验证，015c～015e 未开始）。

## 分批

用户确认把 MOD-015 拆成 5 个批次，每批独立验证，不一次性改写 Runtime：

| 批次 | 内容 | 状态 |
| --- | --- | --- |
| 015a | 兼容台账收敛：删除纯转发模块与已无生产消费者的旧 facade，修正台账；附带配置优先级修复 | 已验证（2026-11-07） |
| 015b | 依赖组/状态类型化与 EventSink | 已验证（2026-11-07） |
| 015c | Loop 职责拆分 | 未开始 |
| 015d | 存储/身份依赖注入 Port（含 model_gateway → persistence/identity/memory 的 5 条债务） | 未开始 |
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
