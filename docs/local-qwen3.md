# 本地模型接入（Qwen3.8-27B / llama.cpp）

Fab Insight Agent 默认按 OpenAI 兼容协议调用模型。本机已经部署了 Qwen3.8-27B 的 GGUF 版本，
通过 `llama-server` 暴露 `/v1`，因此不需要任何云端凭据，也不需要 WSL。

## 机型与模型

| 项 | 值 |
| --- | --- |
| GPU | NVIDIA A10 / 23 GB |
| 模型（主） | `models/Qwen3.8-27B-Q4_K_M-GGUF/Qwen3.8-27B-Q4_K_M.gguf`（15.66 GB） |
| 模型（备） | `models/Qwen3.8-27B-Ridge-3.7bpw/Qwen3.8-27B-Ridge-3.7bpw.gguf`（11.73 GB） |
| 运行时 | `runtimes/llama-cpp/llama-server.exe`（CUDA 构建） |

这两个 GGUF 的架构是 `qwen35`：65 层、`full_attention_interval=4`（只有约 17 层带 KV，其余是 SSM）、
4 个 KV 头、key/value 长度 256。因此长上下文比同尺寸 dense 模型便宜得多：

```
KV/token ≈ 2 × 17 × 4 × 256 × (q8 ≈ 1 B) ≈ 34 KB
81920 tokens ≈ 2.8 GB
```

再加上 15.66 GB 权重与约 1–2 GB 计算缓冲，总计约 20–21 GB，A10 可以装下。

## 启动

```powershell
# 默认：Q4_K_M + 80K 上下文 + 2 并发槽
.\scripts\start-local-model.ps1

# 备选：Ridge 3.7bpw + 32K 单槽，显存更宽松
.\scripts\start-local-model.ps1 -Model ridge -Profile 32k -Port 8081

# 需要图片输入时加载 mmproj
.\scripts\start-local-model.ps1 -Vision
```

脚本会等待 `/v1/models` 就绪后打印模型 id，并给出需要写进 `.env` 的四行配置。

默认关闭 Qwen 的 thinking（`--reasoning off`）：在本机实测，开启时单次回答会多出约
6–7k 输出 token、耗时从约 60 秒涨到约 200 秒。需要推理过程时加 `-Thinking`。

等价的手工命令（与 `records.txt` 中的配置一致）：

```powershell
& ".\runtimes\llama-cpp\llama-server.exe" `
    --model ".\models\Qwen3.8-27B-Q4_K_M-GGUF\Qwen3.8-27B-Q4_K_M.gguf" `
    --mmproj ".\models\Qwen3.8-27B-Q4_K_M-GGUF\mmproj-F16.gguf" `
    --host 127.0.0.1 --port 8080 --gpu-layers all `
    --ctx-size 81920 --parallel 2 --batch-size 1024 --ubatch-size 256 `
    --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on --jinja `
    --no-context-shift --fit off --spec-type draft-mtp --spec-draft-n-max 2 `
    --reasoning off
```

`--jinja` 不能省：没有它，Qwen3 的 chat template 不会套用，工具调用直接失效。

## 应用侧配置

`.env` 被 `.gitignore` 忽略（含密钥，不入库），可参考 `.env.local.example`：

```ini
FAB_MODEL_PROVIDER=openai-compatible
FAB_MODEL_BASE_URL=http://127.0.0.1:8080/v1
FAB_MODEL_NAME=Qwen3.8-27B-Q4_K_M
FAB_MODEL_API_KEY=local
FAB_ADMIN_API_TOKEN=local-admin-token
API_TIMEOUT_MS=120000
MODEL_CONTEXT_TIMEOUT_MS=30000
# Qwen 模板要求 system 消息在最前（llama.cpp --jinja）
FAB_CHAT_TEMPLATE_COMPAT=merge-system
```

该变量由 `Settings.chat_template_compat` 读取，并在模型网关（`app/model_gateway/gateway.py`）发送请求前合并 system 消息；直接调用 `streaming.stream_completion` 不再读取该变量。

注意：**`base_url` 与模型名以数据库 `model_catalog` 为准**，`.env` 只提供 api_key。
`ensure_model_catalog()` 只在首次建库时按当时的 `.env` 种子两条内置模型
（`deepseekv4-flash` / `deepseekv4-pro`），之后不会再改。因此已有数据库需要显式处理。

### 方式一：发布一个本地模型（推荐）

```powershell
$headers = @{ Authorization = "Bearer local-admin-token"; "Content-Type" = "application/json" }
$body = @{
    model_id       = "local-qwen38-27b"
    display_name   = "Local Qwen3.8-27B"
    provider       = "openai-compatible"
    provider_model = "Qwen3.8-27B-Q4_K_M"
    base_url       = "http://127.0.0.1:8080/v1"
    capabilities   = @{ streaming = $true; tool_calls = $true; thinking = $false; native_multimodal = $false }
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8899/api/admin/models" -Method Post -Headers $headers -Body $body
```

然后在用户端右上角的模型按钮里选择它，或调用 `POST /api/settings/model`。

### 方式二：复用内置条目

启动时加 `--alias deepseek-v4-flash`，并把目录里的地址改成本地：

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect(r'runtime\local\data\departments\ai_operations.db');c.execute(\"UPDATE model_catalog SET base_url='http://127.0.0.1:8080/v1'\");c.commit();print(c.total_changes)"
```

## 启动应用

```powershell
$env:FAB_DATABASE_PATH = "D:\Fab_Insight\FAB-Copilot\runtime\local\data\fab_history.db"
$env:FAB_DATABASE_DIR  = "D:\Fab_Insight\FAB-Copilot\runtime\local\data\departments"
$env:AGENT_LOG_PATH    = "D:\Fab_Insight\FAB-Copilot\runtime\local\logs\agent_events.jsonl"
$env:AGENT_RUN_LOG_DIR = "D:\Fab_Insight\FAB-Copilot\runtime\local\logs\agent"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8899
```

（`run.bat` 也可以，它会用 `.venv-win` / `.venv` 并创建独立的 `runtime/<实例ID>/`。）

## 验收

| 检查 | 期望 |
| --- | --- |
| `GET /api/health` | `agent_configured: true`，`model` 指向本地模型 |
| `GET /api/settings/model` | `base_url` 为 `http://127.0.0.1:8080/v1` |
| 发一句「今天良率多少」 | 流式输出，执行路径中出现 `get_yield_trend` 等工具 |
| `logs/agent_events.jsonl` | 有 `model_call_started` / `tool_call_started`，无 `error_type` |

## 兼容性探针

管理端「模型管理 → 兼容性检查」会对每个模型跑 5 项有界探针：连通性与流式、工具调用契约、
上下文负载、结构化上下文、限额。默认超时 12 秒；本机 27B 实测合计约 **17.6 秒**，因此需要放宽：

```ini
MODEL_COMPATIBILITY_TIMEOUT_SECONDS=60     # 上限 60
MODEL_COMPATIBILITY_CONTEXT_CHARS=32768
```

探针要求模型空闲：如果两个 llama-server 槽位正被长问答占用，子探针会排队到超时。
探针结果只做记录，不影响发布与使用；`compatibility.status` 为 `passed` 表示当前配置可用。

> 内置的 `deepseekv4-flash` / `deepseekv4-pro` 共用全局 `FAB_MODEL_API_KEY`，本地部署下该值为
> `local`，因此探针会得到 **401**。不需要云端模型时在管理端把它们「停用」即可；需要时把
> `FAB_MODEL_API_KEY` 换成真实 DeepSeek Key（llama-server 不校验该头，两边可共用）。

## 已知问题

| 现象 | 原因与处理 |
| --- | --- |
| `404 model not found` | `.env`/`model_catalog` 里的模型名与 `/v1/models` 返回的不一致 |
| 始终返回规则分析 | `FAB_MODEL_API_KEY` 为空 → `agent_configured=false` |
| 请求打到 `api.deepseek.com` | `model_catalog.base_url` 未更新（见「方式一/二」） |
| 工具从不被调用 | `llama-server` 缺 `--jinja` |
| 500 / `System message must be at the beginning` | Qwen 模板约束；设置 `FAB_CHAT_TEMPLATE_COMPAT=merge-system`（Agent 会在历史与证据之后追加 system 指令） |
| 长会话被硬截断 | `--no-context-shift` 生效中，需要在客户端压缩历史 |
| 首 token 超时 | 80K 上下文 prefill 较慢，调大 `API_TIMEOUT_MS` |
| `/api/reports/capability` 返回 500（`no such function: SQRT`） | 本地 SQLite 构建未启用数学函数，见 issue 草稿 `fab-copilot-issue-sqrt.md` |

## 显存档位参考

| Profile | ctx | parallel | KV（q8） | 权重 | 估算总计 |
| --- | --- | --- | --- | --- | --- |
| `80k` | 81920 | 2 | ~2.8 GB | 15.7 GB | ~20–21 GB |
| `32k` | 32768 | 1 | ~1.1 GB | 15.7 GB | ~18–19 GB |

如果出现 OOM，先降 `-Profile 32k`，再考虑换 Ridge 3.7bpw。
