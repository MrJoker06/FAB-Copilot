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

> 如果模型在管理端声明了 `native_multimodal = true`，兼容性探针会发送一张图片。
> 此时必须用 `-Vision` 启动；否则 llama.cpp 会返回 HTTP 500
> `image input is not supported`，兼容性检查会提示“模型服务未加载多模态投影”。

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

`.env` 被 `.gitignore` 忽略（含密钥，不入库），可参考 `.env.local.example`。同名变量以进程环境变量优先，其次为项目 `.env`，最后才是上两级目录的工作区 `.env`，因此工作区里残留的旧密钥不会覆盖项目配置：

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
    model_id       = "qwen38-27b-q4km"
    display_name   = "Local Qwen3.8-27B"
    provider       = "openai-compatible"
    provider_model = "Qwen3.8-27B-Q4_K_M"
    base_url       = "http://127.0.0.1:8080/v1"
    capabilities   = @{ streaming = $true; tool_calls = $true; thinking = $false; native_multimodal = $false }
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8899/api/admin/models" -Method Post -Headers $headers -Body $body
```

然后在用户端右上角的模型按钮里选择它，或调用 `POST /api/settings/model`。

### 模型编号命名约定

后续发布的模型统一按 `<家族><版本>-<参数规模>-<量化>` 命名，全部使用小写 ASCII、以连字符分隔：

| 可读名称 | model_id |
| --- | --- |
| Qwen3.8-27B-Q4_K_M | `qwen38-27b-q4km` |
| Qwen3.8-14B-Q4_K_M | `qwen38-14b-q4km` |
| Llama3.2-8B-Q5_K_M | `llama32-8b-q5km` |

- 版本号去掉小数点：Qwen3.8 → `qwen38`。
- 参数量写成数字加 `b`：27B → `27b`。
- 量化值小写并去掉下划线：Q4_K_M → `q4km`。
- `display_name` 和 `provider_model` 继续写原始可读名称，不参与编号。
- 历史内置编号 `deepseekv4-flash` / `deepseekv4-pro` 保持不变。

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

> 不要省略上面的四个环境变量。直接 `uvicorn app.main:app` 会回退到仓库默认的
> `data/departments`，那是一个独立的新库：里面只有内置的 DeepSeek 条目，
> 已发布的本地模型、聊天记录和模型偏好都留在 `runtime/local/data` 里，看起来就像
> "本地模型不见了"。如果模型列表突然只剩 DeepSeek，先检查 `GET /api/health` 返回的
> `database_departments.*.path` 是否指向 `runtime/local/data/departments`。

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

## 证据裁剪（上下文保护）

诊断类计划会一次执行 7 个工具，其中 `get_sensor_summary`、`get_recent_excursions`、
`get_equipment_excursion_history` 各返回 100 行。完整 JSON 约 10.7 万字符（≈41.7k token），
超过双槽配置下每请求 40960 的上限，llama-server 会直接 500，表现为「模型综合服务不可用」。

因此合成前会按工具裁剪**提示词视图**（`app/evidence/evidence_truncation.py`）：

| 工具 | 保留 | 排序 |
| --- | ---: | --- |
| `get_sensor_summary` | 15 | 异常点从多到少 |
| `get_recent_excursions` | 20 | 按发生时间倒序 |
| `get_equipment_excursion_history` | 20 | 按发生时间倒序 |
| `get_equipment_event_timeline` | 20 | 按事件时间倒序 |
| `get_equipment_health` | 10 | Critical 优先 |
| `get_equipment_productivity` | 10 | 利用率从低到高 |
| `search_knowledge` | 3 | 检索得分顺序（仅保留关键字段） |

裁剪只影响提示词：`agent_tool_events`、运行记录、API 返回仍然是完整行数，证据校验
（样本量、覆盖率）也不受影响。

**提示信息**会在两处出现：

- 每条被裁剪的证据带 `truncation: {total_rows, shown_rows, sort, note}`，模型据此知道是部分视图；
- 最终答案的「证据限制」里追加一行，例如
  `为控制上下文，以下工具结果已裁剪：get_sensor_summary 15/100、get_recent_excursions 20/100；完整结果保留在运行记录中。`

本机实测（同一个七步设备诊断问题）：

| | 输入 token | 耗时 |
| --- | ---: | ---: |
| 裁剪前 | 41,756 | 166 s（双槽下 500） |
| 裁剪后 | **12,635** | **85 s** |

### 本地与云端模型并存

模型目录可以同时保留本地 llama-server 模型和 DeepSeek 云端模型，切换入口在设置里的模型
下拉框；选择结果按用户保存在 `agent.user_model_preferences`。切换已发布模型不需要重启。

凭据与模型一一对应，保存在服务器本地的 `runtime/local/model_credentials.json`（可用
`FAB_MODEL_CREDENTIALS_PATH` 改位置；该文件不在数据库、不在 git、不返回浏览器）。管理端
「模型目录 → 凭据 → 配置」可以按模型新增、替换或清除 key；本地模型没有鉴权要求时填
`local` 即可。文件通过临时文件 + 原子替换写入，权限尽量设为 `0600`。

解析顺序（`app/core/model_credentials.py::resolve_model_api_key`）：

1. 本地凭据文件中该模型的条目：存在即**唯一来源**，不会再借用其他模型的 key；
2. `FAB_MODEL_API_KEY__<模型编号>`：环境变量覆盖，编号转大写、非字母数字字符替换为
   `_`（`qwen38-27b-q4km` → `FAB_MODEL_API_KEY__QWEN38_27B_Q4KM`）；
3. provider 为 `deepseek` 时优先 `DEEPSEEK_API_KEY`；
4. 最后回退全局 `FAB_MODEL_API_KEY`，再回退 `DEEPSEEK_API_KEY`。

因此既可以在管理端逐模型配置，也可以继续用 `.env` 作为兼容回退：

```dotenv
# 本地 llama-server：不校验密钥，但必须非空
FAB_MODEL_API_KEY=local
FAB_MODEL_BASE_URL=http://127.0.0.1:8080/v1
FAB_MODEL_NAME=Qwen3.8-27B-Q4_K_M

# 云端 DeepSeek：与本地 key 并存
DEEPSEEK_API_KEY=sk-your-deepseek-key

# 可选：只覆盖某个模型
FAB_MODEL_API_KEY__QWEN38_27B_Q4KM=another-local-key
```

管理端的「兼容性检查」使用同一解析规则，所以 DeepSeek 条目不会因为本地 key 而得到
**401**。保存或清除某个模型的本地凭据会立即使其兼容性结果变为 `unverified`，随后重新
执行探针即可；本地凭据文件改动无需重启 API。修改 `.env` 后仍需重启 API 才能让进程读到
新的环境变量。密钥不写入数据库，也不下发给前端。

## 证据匹配与 V1/V2 同步

原生工具分发桥（`app/agent_runtime/execution/tool_result_bridge.py`）在成功调用后，会用适配器
上报的**结果 scope** 覆盖提交参数：设备级查询可能只保留 `equipment_id`，丢掉计划里的
`process_step`。旧证据校验器按"计划参数逐字相等"匹配步骤与调用，于是这类调用被误判为
`scope_mismatch`、结果不计入证据，`TOOL:Sxx` 也不在 `permitted_source_refs` 里；而
`source_semantics` 仍然列出它，模型引用后反被拒绝。

修复后：

- `app/planning_runtime/scope.py::call_scope` 是唯一的"参数 → 结果 scope"规则，计划与校验器共用；
- `validator._step_matches` 比较**声明的结果 scope**与执行参数推导出的 scope，不再要求参数逐字相等；
- `permitted_source_refs` 包含 `source_semantics` 的全部 `TOOL:Sxx`；未计入证据的步骤会以
  "引用 TOOL:Sxx 没有可追溯的证据检查"明确拒绝，不再误报成"只能引用 TOOL:Sxx"；
- 风险按**调用**归属（`ValidationIssue.source_ref`）：同一证据要求下"异常为空"不再拖累
  "缺陷 Pareto 有行"的另一个调用。

`search_knowledge` 的结果 scope 描述的是命中文档本身而非检索过滤器，所以检索步骤在过滤参数被
桥接丢弃时仍会判为未计入证据；历史案例事实按安全约束继续留在「待验证」。

## 空结果事实

工具返回 0 行时，`empty_result` 仍是 critical、结论强度照旧降级，但允许直接陈述"未检索到"：

- 只有陈述是"未检索到、未发现、未检出、无异常、返回空、为空"等缺失语义时才放行；
- 同一事实不能既引用空结果又引用有数据的调用；
- 该事实标记为 `limited`，并在「证据限制」追加
  `空结果仅表示该查询范围内未检索到记录，不代表该现象绝对不存在。`

## 结论的推测与受限标注

带"可能/若…/可能由…"的推断和事实会进入「待验证」，不会出现在「已确认事实/分析推断」。
被采纳的结论若含推测措辞或只受有限证据支撑，会加前缀并披露：

- `推测（未经证实）：…`（结论含非断言措辞）
- `证据有限：…`（结论 support=`limited`）

对应限制写入「证据限制」，`brief` / `compact` / `report` / `table` 四种模式一致。

## 本地复跑（修复后）

同一台本机，`FAB_PRESENTATION_MODE=model`，四个回归问题各跑一次（模型输出有随机性，数值是当次结果）：

| 用例 | 事实通过 | 结论 | 结论标记 | 耗时 |
| --- | ---: | --- | --- | ---: |
| 缺陷类型占比 + 关联设备 | 7/7，另有 2 条受限推断 | `limited`，已采纳 | `证据有限：` | 70.5 s |
| ETCH-04 故障报警 | 4/5（传感器被 EQP-03 `partial` 卡住，历史案例留待验证） | 推断被拒，结论替换 | 无 | 59.5 s |
| 最近四周良率下降 | 5/6（空异常"未检索到"通过，案例原文仍留待验证） | 推断被拒，结论替换 | 无 | 71.8 s |
| CMP-03 Cpk 不合格 | 2/3（Cpk 为工序级 `context_only`，不能作设备级事实） | 推断被拒，结论替换 | 无 | 38.1 s |

四个用例的 `invalid_source_refs` 均为空，不再出现"直接事实只能引用调用级 TOOL:Sxx 证据"这类误报。

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

## 回答格式由模型选择

`submit_analysis` 新增可选字段 `presentation`，取值为 `brief` / `compact` / `report` / `table`；
模型按问题意图与证据量自行选择，服务端按该模式渲染。

```ini
FAB_PRESENTATION_MODE=model   # 默认；rule 表示使用关键词启发式（旧行为）
```

即使模型选择，服务端仍按模式裁剪条目，避免一次“report”渲染成小作文：

| 模式 | 事实/推断/待验证/建议 | 单条 | 限制 |
| --- | --- | --- | --- |
| `brief` | 事实 2、限制 3 | 事实 90 字、限制 120 字 | 保留（截断） |
| `compact` | 8 / 5 / 5 / 4 | 240 字 | 全部保留，截断 |
| `report` | 各 8 | 240 字 | 全部保留，截断 |
| `table` | 各 8 | 200 字 | 全部保留，截断 |

被裁掉的条目会在「证据限制」里提示“已省略 N 条声明”。

选择指引写在 system prompt 中 `answer_contract=` 之前，使角色说明、协议与指引构成稳定的
前缀，便于 llama.cpp 的 slot 级 prompt cache 命中；每次请求变化的部分只留在最后。

`answer_synthesis.presentation` 与 `answer_synthesis.presentation_source`
（`model` / `rule` / `fallback`）会随 API 返回，便于核对实际渲染模式。
