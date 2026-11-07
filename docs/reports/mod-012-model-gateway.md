# MOD-012：ModelGatewayPort、Provider 适配与客户端生命周期收口

日期：2026-11-07。基线：`d98b203`。状态：已验证（定向回归、边界门和两端平台测试见下文）。

## 范围

把默认 Loop、Ready 综合、上下文解析三条模型调用路径上的 HTTP 客户端构造/关闭、Chat Completions URL、凭据头和聊天模板消息整形，从 Runtime 收进 `app/model_gateway/gateway.py`。Runtime 只保留自己的重试、熔断健康记录和本地回退策略，行为和事件不变。

不在本项范围：模型目录/注册表、健康存储、真实端点或密钥发布、`model_gateway/compatibility.py` 的兼容性探测，以及性能门。本轮未运行配对性能、浏览器全量或覆盖率。

## 接口

```python
@dataclass(frozen=True)
class ModelEndpoint:                       # api_key 不进入 repr
    provider: str; model: str; base_url: str; api_key: str; chat_template: str | None = None
    @classmethod
    def from_connection(cls, connection, *, chat_template=None) -> ModelEndpoint
    chat_completions_url: str              # property
    def headers(self) -> dict[str, str]
    merges_system_messages: bool           # property
    def prepare_payload(self, payload: dict) -> dict   # 启用时返回新 dict，不修改调用方请求

class ModelSessionPort(Protocol):          # runtime_checkable
    endpoint: ModelEndpoint | None
    async def stream(self, payload, progress, stream_state=None) -> tuple[dict, dict, str | None]

class ModelGatewayPort(Protocol):          # runtime_checkable
    def endpoint_for(self, connection, *, chat_template=None) -> ModelEndpoint
    def open(self, endpoint, *, timeout_seconds) -> AbstractAsyncContextManager[ModelSessionPort]

class HttpModelGateway:                    # 默认 Adapter
    def __init__(self, *, stream_completion, client_factory=None)   # None → httpx.AsyncClient
class HttpModelSession                     # 绑定一个自有客户端和一个 endpoint
class ClientModelSession(client, url, headers, stream_completion)  # 旧 (client, endpoint, headers) 调用方适配，不整形
```

`open()` 以 `async with client_factory(timeout=timeout_seconds)` 持有客户端，成功、HTTP 错误和取消时都会关闭。`endpoint_for` 放在 Port 上，调用方不必导入 gateway 模块；这让只复制 `stages/ready.py` 的可迁移切片不需要额外依赖。

## 调用方变化

| 位置 | 变化 |
| --- | --- |
| `execution/agent_loop.py` | 不再导入 httpx；`AgentLoopContext.stream_completion` 换为 `model_gateway`，重试/健康/回退逻辑不变 |
| `stages/ready.py`、`synthesis/ready.py` | `request_ready_synthesis(session, connection, settings, messages, run_id, thinking, retry_budget, *, deps)`；`request_synthesis_correction(session, connection, ...)` |
| `preparation/context.py` | `ResolverDependencies.model_gateway` 取代 `stream_completion`/`async_client`；httpx 仅用于 ReadTimeout 分类 |
| `dependencies.py` | `ReadyDependencies.async_client`、`LoopDependencies.stream_completion` → `model_gateway` |
| `model_gateway/streaming.py` | 删除对 `FAB_CHAT_TEMPLATE_COMPAT` 的直接读取；整形只在 gateway 中进行 |
| `core/settings.py` | 新增 `chat_template_compat: str | None = None`，由 `FAB_CHAT_TEMPLATE_COMPAT` 加载 |

## 兼容

- 旧 service live patch 保持有效：`legacy_agent_assembly` 每次组装时从 service 命名空间读取 `HttpModelGateway`、`httpx.AsyncClient` 和 `_stream_completion`，Loop 与 Ready 共用同一个网关实例；`_agent_preparation_dependencies` 同样每次读取。patch `app.agent_runtime.service._stream_completion` 或 `httpx.AsyncClient` 仍会作用于下一次 Run。
- 旧 facade `_request_ready_synthesis(client, endpoint, headers, ...)` 与 `_request_synthesis_correction(client, endpoint, headers, ...)` 签名不变，内部用 `ClientModelSession` 包装；新增 `_request_ready_synthesis_session` / `_request_synthesis_correction_session` 供新装配使用。
- 聊天模板：环境变量名和取值不变，改为经 `Settings` 读取；直接调用 `streaming.stream_completion` 不再按环境变量整形（有测试覆盖）。

## 验证

| 检查 | 结果 |
| --- | --- |
| `tests.test_model_gateway_port`（新增） | 20/20 通过（Windows / WSL） |
| WSL 定向 25 模块（Py 3.11，测试用 PIL 桩） | 313 项通过 |
| WSL `tests.system.test_model_governance` | 17 项通过 |
| Windows 定向同 25 模块（Py 3.13） | 313 项：19 failures / 11 errors，均为既有环境问题：`test_module_boundaries` 反斜杠路径（19 个子测试）、临时 SQLite WinError 32（9）、symlink WinError 1314（2） |
| `scripts/check_modularization_boundaries.py` | 278 文件 / 0 错误（两端） |
| WSL `run_quality_gate.py quick`（借用 Linux venv，无 PIL） | 与合并前基线逐项对比无新增失败；唯一差异为新测试模块因该 venv 缺 PIL 无法导入（加 PIL 桩后 20/20 通过） |
| Windows 定向 12 模块（含新增专项、上下文解析、旧装配、意图路由、流式诊断） | 166 项通过 |
| DeepSeek 实测 | 未完成：本机所有可用 DeepSeek key 均返回 401（key 无效）。仅确认 Ready 综合遇 401 走既有本地回退、Loop 遇 401 按既有逻辑上抛；需有效 key 后补测 |
| Ruff | 改动文件的 check 结果与 HEAD 相同（28 项既有问题，无新增）；新文件与原已格式化文件通过 format 检查 |

边界清单：文件 277 → 278（新增 `gateway.py`），债务 29、兼容入口 13 不变，兼容消费者 97 → 99（新增测试对 service 的导入和 patch）。`portable_units_v1.json` 中 `model_transport` 升至 1.1.0 并包含 `gateway.py`。

## 遗留事项的后续处理（2026-11-08 核对）

- 已在 015a 解决：`state.endpoint`（`stages/model.py`、`coordinator_state.py`）已删除。
- 已在 015a 解决：旧 `(client, endpoint, headers)` facade 和 `ClientModelSession` 已删除，测试改用会话 facade 和 `ModelSessionPort` 替身。
- 015a 部分解决：`model_gateway/compatibility.py` 的探针 URL 与凭据头改由 `ModelEndpoint` 提供；它是管理端探针，仍按设计自建 `httpx.AsyncClient`（`follow_redirects=False`），不经过 Run 的 Port。
- 本项没有退出 model_gateway → memory/persistence/identity 的 5 条依赖债务。015a（`e442df9`）将其 exit_task 从 MOD-012 改为 MOD-015，计划由 015d 承接；015d（`3cbed1d`）实际移除了 `model_gateway.health → persistence.database`、`model_gateway.registry → persistence.database` 与 `model_gateway.registry → core.identity` 三条债务；`model_gateway.compatibility → memory_system.context.history/protocol` 两条保留并改挂 MOD-025。
- 另行区分：015d 将 `manufacturing.enterprise_data → core.identity`、`manufacturing.reports → persistence.database` 改挂 MOD-008，将 `persistence.execution_store → core.identity` 改挂 MOD-021。这三条不属于上述原归 MOD-012 的五条债务。015e 将其余保留的 MOD-015 台账项改挂 MOD-027；当前台账已无 exit_task 为 MOD-015 的条目。

见 [MOD-015 报告](mod-015-runtime-convergence.md)。

## 回滚

回滚只需撤销本项提交（恢复上述文件并删除 `app/model_gateway/gateway.py` 和 `tests/test_model_gateway_port.py`），不涉及数据或配置迁移；`FAB_CHAT_TEMPLATE_COMPAT` 的部署值无需改动。
