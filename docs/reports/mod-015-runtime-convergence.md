# MOD-015：Runtime 收口、依赖类型化与兼容退出

日期：2026-11-07。基线：`1c61601`（MOD-012）。状态：进行中（015a 已验证，015b～015e 未开始）。

## 分批

用户确认把 MOD-015 拆成 5 个批次，每批独立验证，不一次性改写 Runtime：

| 批次 | 内容 | 状态 |
| --- | --- | --- |
| 015a | 兼容台账收敛：删除纯转发模块与已无生产消费者的旧 facade，修正台账；附带配置优先级修复 | 已验证（2026-11-07） |
| 015b | 依赖组/状态类型化与 EventSink | 未开始 |
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
