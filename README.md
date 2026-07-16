# Fab Insight Agent

一个可运行的虚拟半导体制造报表系统，包含 24 个月历史数据、制造 KPI、制程能力分析、设备异常检测、知识库 RAG，以及通过 DeepSeek 工具调用驱动的数据分析 Agent。

## 已实现能力

- 约 9,500 个制造批次、170,000 条分层工序、100 万条传感器记录、28 台设备及对应状态、事件和缺陷记录
- 综合良率、周期时间、Hold、异常数等 KPI
- 周良率趋势、设备健康、缺陷 Pareto、近期异常批次
- 覆盖光刻、刻蚀、CVD、PVD、扩散、离子注入、CMP、清洗和量测，各站点按自身关键量测与规格计算 Cpk
- 九类制程各有一个可复现异常场景，隐藏根因真值不向 Agent 开放
- DeepSeek Agent 多轮工具调用，支持固定报表和受限只读 SQL
- DeepSeek 瞬时网络错误、429 和 5xx 在首 Token 前自动退避重试；消息使用客户端幂等 ID 防止重复落库
- 工具执行期间实时展开路径；收到最终答案首批 Token 后立即折叠，Markdown 答案流式输出并支持一键复制
- 桌面端可拖动 Fab Copilot 左边缘调整面板宽度，双击恢复默认，宽度偏好保存在当前浏览器
- 会话、消息、运行、工具和来源结构化保存到 AI 运营库；独立“历史会话”工作区可搜索、预览、继续、重命名、归档和恢复会话，右侧助手保留快速入口
- 归档会话会立即移出活跃列表并支持提示条撤销；历史会话支持按筛选结果批量选择、全选和删除，活跃与归档会话可混合处理，删除需要明确确认且不可恢复
- Agent 可观测性：运行成功率、延迟、Token、工具使用和错误类型
- 全 API 请求使用 `request_id` 串联 HTTP、会话、Agent、模型和工具日志，错误响应提供稳定错误码和可重试标记
- 68 个知识章节与 17 个固定格式历史案例
- SQLite FTS5 trigram 双来源 RAG，支持中文检索与引用跳转
- 个人知识库支持私有文件上传、异步解析、分块索引、Agent 三路融合检索、来源跳转、下载、重试和完整删除；未完成功能统一记录在 [TODO](#todo)
- DeepSeek 不可用时自动提供本地规则分析

> 所有数据和知识文档均为演示用途，不代表真实工厂或量产规范。公开数据只用于校准数据形态和统计特征，具体配方、规格与根因均为可复现合成内容。

## 模拟数据依据

数据生成器采用“公开真实数据形态 + 行业指标定义 + 工艺约束”的混合方法：

- [UCI SECOM](https://archive.ics.uci.edu/dataset/179/secom)：校准高维传感器、缺失值、噪声和稀疏异常形态。
- [SEMI E10/E79](https://www.semi.org/en/products-services/standards/step/equipment-performance-metrics)：组织 Productive、Standby、Engineering、Scheduled/Unscheduled Downtime 等设备状态与生产率指标。
- [WM-811K 论文记录](https://scholars.lib.ntu.edu.tw/entities/publication/563e8f2c-74ee-4733-bd62-ba5e409d8424)：校准 None、Center、Donut、Edge、Loc、Random、Scratch 等 Wafer Map 类别和不平衡形态。
- [NIST Control Charts](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc31.htm)：构造稳定基线、缓慢漂移、突变和控制限异常。

默认 Route 包含 18 个重复模块节点，覆盖光刻、刻蚀、CVD、PVD、扩散、离子注入、CMP、清洗和量测。`simulation_scenarios` 保存评测根因，但不在 SQL 白名单和 Agent 工具中。

## 快速启动

项目会自动读取 `D:\modern_agents\.env`，至少需要：

```dotenv
DEEPSEEK_API_KEY=your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseekv4-flash
FAB_DATABASE_PATH=data/fab_history.db
FAB_DATABASE_DIR=data/departments
FAB_SQLITE_JOURNAL_MODE=auto
AGENT_LOG_PATH=logs/agent_events.jsonl
AGENT_RUN_LOG_DIR=logs/agent
AGENT_LOG_MAX_BYTES=5242880
AGENT_LOG_BACKUP_COUNT=5
AGENT_LOG_CONTENT=metadata
MODEL_MAX_RETRIES=2
MODEL_RETRY_BASE_MS=500
FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH=data/personal_knowledge
FAB_PERSONAL_KNOWLEDGE_USER_ID=local-user
FAB_PERSONAL_KNOWLEDGE_API_TOKEN=
FAB_PERSONAL_KNOWLEDGE_MAX_UPLOAD_BYTES=52428800
```

在 WSL 中运行：

```bash
cd /mnt/d/modern_agents/agents/fab-insight-agent
conda create -n fab-insight-agent python=3.11 pip -y
conda run -n fab-insight-agent python -m pip install -r requirements.txt
./run.sh
```

`run.sh` 默认始终通过 Conda 环境 `fab-insight-agent` 启动，不向 `base` 安装项目依赖。需要使用其他环境名时设置 `FAB_CONDA_ENV`。

在 Windows 中运行：

```bat
cd /d D:\modern_agents\agents\fab-insight-agent
run.bat
```

`run.bat` 是 Windows 入口，会通过 `wsl.exe` 调用 `run.sh`，实际运行时仍使用 WSL 中的 `fab-insight-agent` Conda 环境；Windows 端不需要另外安装 Python 或项目依赖。

浏览器访问 <http://127.0.0.1:8765>，接口文档位于 <http://127.0.0.1:8765/docs>。

## 模型切换

点击页面右上角的模型按钮，可以更新 API Key，并在以下模型中切换：

- `deepseekv4-flash`
- `deepseekv4-pro`

界面名称会分别映射到 DeepSeek API 实际要求的 `deepseek-v4-flash` 和 `deepseek-v4-pro`。

也可以直接调用：

```text
GET  /api/settings/model
POST /api/settings/model
```

```json
{
  "model": "deepseekv4-pro",
  "api_key": "your-api-key"
}
```

API Key 只保存在当前服务进程的内存中，响应仅返回掩码，服务重启后重新读取 `.env`。只切换模型时可以省略 `api_key`。服务端使用模型白名单校验，当前样例不接受其他模型名称。

如独立环境缺少依赖：

```bash
conda run -n fab-insight-agent python -m pip install -r requirements.txt
```

## 常用命令

重新生成相同分布的历史数据：

```bash
conda run -n fab-insight-agent python -m app.seed --force
```

运行测试：

```bash
conda run -n fab-insight-agent python -m unittest discover -s tests -v
```

## 架构

```text
浏览器报表 / 对话 / 知识库 / 案例库
          |
       FastAPI
      /       \
报表查询工具   DeepSeek Agent loop
      \       /       |
  部门数据库联邦   联合 RAG / 受限 SQL
      |              /             \
制造/设备/质量库   FTS5 知识库    FTS5 案例库
```

Agent 不直接访问数据库连接，而是通过 `app/agent.py` 中声明的工具工作。任意 SQL 仅允许单条 `SELECT`，限制在四张制造数据表并最多返回 100 行；数据库写入、DDL、PRAGMA 和系统表访问均被拒绝。

## 部门数据库治理

运行时使用五个物理隔离的 SQLite 数据库，默认位于 `data/departments/`：

| 部门所有者 | 数据库 | 负责数据 |
|---|---|---|
| 制造运营 | `manufacturing_operations.db` | 批次、工序履历、模拟场景 |
| 设备工程 | `equipment_engineering.db` | FDC传感器、SEMI E10状态、设备事件 |
| 良率质量 | `yield_quality.db` | 缺陷、晶圆图、缺陷标准目录与别名 |
| 工艺知识管理 | `process_knowledge.db` | 知识文档、章节、历史案例、FTS5索引 |
| AI运营 | `ai_operations.db` | 会话、消息、Agent运行、工具事件、回答来源 |

应用连接会挂载五库并提供只读兼容视图，因此报表与受限SQL仍可使用原有表名。跨部门关系通过启动治理检查验证；各部门库内部继续使用外键和唯一约束。旧单库 `data/fab_history.db` 仅作为迁移源保留，不再承担运行写入。

`FAB_SQLITE_JOURNAL_MODE=auto` 会在 WSL 的 `/mnt/*` Windows 挂载盘上使用 `DELETE` journal，避免 DrvFs 不支持 WAL 共享内存锁而产生 `disk I/O error`；Linux 本地文件系统继续使用 `WAL`。也可以显式设置为 `DELETE` 或 `WAL`。

常用治理命令：

```bash
# 从旧单库迁移；目标库已有数据时不会覆盖
conda run -n fab-insight-agent python -m scripts.manage_databases migrate

# 检查完整性、行数、跨部门孤儿、未来数据、目录和FTS同步
conda run -n fab-insight-agent python -m scripts.manage_databases check

# 在线备份五个部门库并生成manifest.json
conda run -n fab-insight-agent python -m scripts.manage_databases backup

# 回收WAL文件
conda run -n fab-insight-agent python -m scripts.manage_databases checkpoint
```

数据库Schema版本记录在每个部门库的 `schema_migrations` 表中。测试使用临时知识库和AI运营库，不再向演示会话写入测试数据。

## 知识库与历史案例库

个人知识库、权限隔离、上传处理，以及从 SQLite/FTS5、PostgreSQL/pgvector 到独立向量与全文检索集群的分级 RAG 方案，见 [个人知识库与分级 RAG 架构设计](docs/knowledge-base-rag-architecture.md)。第一期上传与检索接口及网页入口已经实现；在“知识库”页面可切换到“我的知识”，上传、查看处理进度、预览、下载、重试或删除个人文档。个人知识不共享，OCR 和生产化能力统一记录在 [TODO](#todo)。

当前样例尚未接入正式登录系统，个人知识所有者由服务端 `FAB_PERSONAL_KNOWLEDGE_USER_ID` 决定，客户端不能传入或修改所有者。配置 `FAB_PERSONAL_KNOWLEDGE_API_TOKEN` 后，个人知识接口必须携带对应 Bearer Token；留空时仅适合本机单用户开发。

第一期上传接口：

```text
POST   /api/knowledge/personal/documents
GET    /api/knowledge/jobs/{job_id}
GET    /api/knowledge/personal/documents
GET    /api/knowledge/personal/documents/{document_id}
GET    /api/knowledge/personal/documents/{document_id}/content
GET    /api/knowledge/personal/documents/{document_id}/file
PATCH  /api/knowledge/personal/documents/{document_id}
DELETE /api/knowledge/personal/documents/{document_id}
POST   /api/knowledge/personal/documents/{document_id}/retry
POST   /api/knowledge/personal/search-preview
GET    /api/knowledge/personal/chunks/{chunk_id}
```

左侧“知识库”包含 17 份制造文档、68 个稳定引用章节，覆盖光刻、刻蚀、CVD、PVD、扩散、离子注入、CMP、清洗、量测、SPC、Hold、Recipe 变更、根因分析、良率和数据治理。

左侧“案例库”包含 17 个结构化案例。案例源文件为 `cases/historical_cases.json`，每条记录必须包含：

```text
case_id, title, process_step, equipment_id, occurred_date, severity,
problem, solution, result, summary, tags
```

其中核心复用格式固定为“问题、解决方案、解决结果、案例总结”。启动时会校验字段并重建 trigram 索引。Agent 内部的 `search_knowledge` 会按当前服务端用户联合检索个人知识、正式知识和历史案例；公共 `/api/rag/search` 仍只返回正式知识与历史案例，避免绕过个人知识鉴权。三类引用分别为：

- `PERSONAL-UUID`：当前用户的个人知识片段，可跳转到个人文档对应页。
- `KB-数字`：正式知识章节，可跳转到知识库对应位置。
- `CASE-...`：历史案例，可跳转到案例详情。

当前 L0 使用关键词检索，并针对九类制程加入中英文术语扩展，例如中文“光刻技术原理”可召回英文 `photolithography` 文档。它不是通用语义翻译；进入 L1 后仍应使用多语种 Embedding 与混合检索覆盖更广泛的跨语言表达。

案例只用于生成根因假设，不能单独证明当前问题具有相同根因。

### 检索治理与重排

知识治理配置位于 `knowledge/catalog.json`，包含版本、生效日期、责任人、状态、权威等级、适用站点和标签。案例治理配置位于 `cases/catalog.json`，包含结构化症状、已验证根因、根因置信度、验证方法、复发状态、审批人和案例状态。

检索流程：

```text
查询实体推断（站点 / 设备 / 缺陷）
  -> Active / Validated / 所有者和确定性元数据前置过滤
  -> 中文 trigram 候选召回（每来源 Top 30）
  -> 站点、设备、缺陷、权威和案例置信度加权
  -> 低置信度案例抑制
  -> 去重、来源配额与多样化
  -> 加载完整 chunk 作为生成上下文
  -> 最终 Top 1-10
```

每个结果包含 `retrieval.lexical_rank`、`final_score`、`confidence`、`score_version`、`selection_reason` 和实际过滤条件。检索到的正文被标记为不可信数据，Agent 在向前端发送回答前会移除不在本轮候选集中的伪造引用。可通过只读调试接口检查：

```text
GET /api/rag/search?q=CMP-03划伤&process_step=CMP&equipment_id=CMP-03&defect_type=Scratch
```

### RAG 回归评测

黄金评测集位于 `evaluations/rag_gold.json`，当前包含 20 个典型问题和 4 个域外负例，覆盖中文、英文、中英混合、短查询、别名推断和无答案拒答。运行：

```bash
python3 scripts/evaluate_rag.py
```

评估输出包括命中率、来源覆盖率、MRR、负例准确率和错误案例命中数。新增知识、案例或修改排序算法后，应先通过该评测再合并代码。当前基线要求全部问题命中、域外负例不召回、所需来源类型完整且错误案例命中为0。

## Agent 日志与监控

前端“Agent 监控”页面每 30 秒刷新一次，也可直接查询：

```text
GET /api/monitor/summary?hours=24
GET /api/monitor/events?limit=100
```

汇总日志默认写入 `logs/agent_events.jsonl`，达到 5 MB 后轮转并保留 5 份；每次请求或运行的完整事件同时写入 `logs/agent/YYYY-MM-DD/<request_id|run_id>.jsonl`。API 响应通过 `X-Request-ID` 返回请求编号，`request_id` 会继续写入该请求触发的 Agent、模型和工具事件。

主要事件：

- `api_request_started` / `api_request_finished`：接口、状态码、耗时和请求编号
- `api_exception`：未预期服务端异常及测试模式下的完整堆栈
- `agent_run_started`：问题长度、问题指纹和历史消息数
- `model_call_finished`：模型、延迟、Token 和状态
- `model_call_retry_scheduled`：重试原因、次数和退避时间
- `tool_call_finished`：工具名、延迟、返回行数和状态
- `agent_run_finished`：总耗时、模式、工具数、来源数和最终状态

默认不记录 API Key、Authorization、完整问题、工具参数、SQL、模型回答或工具返回值。日志目录已加入 `.gitignore`。生产部署时应限制监控 API 权限，并将日志发送到 Loki、ELK、OpenTelemetry Collector 等集中系统。

日志内容模式：

- `metadata`：只记录长度、哈希、状态和指标，适合生产默认配置。
- `redacted`：保留脱敏摘要，适合预发布环境。
- `full`：记录完整问题、历史消息、模型请求/响应、工具参数/结果、RAG 内容、最终答案和错误堆栈，适合受控测试环境。

当前项目的本地 `.env` 已设置 `AGENT_LOG_CONTENT=full`。即使在完整模式下，API Key、Authorization、密码、Secret、Cookie 和访问 Token 字段仍会强制替换为 `<redacted>`。完整日志可能包含批次号、SQL、制造数据和对话内容，因此不得提交 Git，不应暴露监控 API 到公网，测试完成后应删除或切换回 `metadata`。

## 目录

```text
app/
  main.py       FastAPI 接口与静态站点
  agent.py      DeepSeek 工具调用循环与系统约束
  reports.py    制造报表及只读 SQL 保护
  rag.py        FTS5 trigram 知识与案例联合检索
  audit.py      脱敏结构化日志、轮转和监控汇总
  seed.py       可复现历史数据生成器
  static/       报表与 Agent 前端
knowledge/      虚拟厂内 SOP / 控制计划
cases/          固定格式历史案例 JSON
evaluations/    RAG 黄金问题与预期来源
scripts/        RAG 评估脚本
data/           生成的 SQLite 数据库
tests/          关键链路测试
logs/           Agent JSONL 审计日志（不提交）
```

## TODO

README 中所有未完成事项统一在本节维护；完成后勾选并在对应提交中更新说明，不在其他章节建立独立 TODO 清单。

生产目标是保留当前 Agent 和前端，将 `app/reports.py` 的查询函数替换为 ASP.NET Core API 或 MCP 工具，并分离结构化制造数据、非结构化知识和 Agent 分析规则：

```text
Oracle / MES / EAP / SPC / FDC / YMS
                |
        Fab Data MCP Server
  身份映射、权限、参数校验、审计、限流
                |
       领域化 MCP Tools
                |
   Fab Agent + 分析流程 Skills
                |
       RAG（SOP、案例、个人知识）
```

### P0：身份、安全与数据边界

- [ ] 接入 FAB SSO/OIDC，使用登录上下文中的稳定 `user_id` 替换全局 `FAB_PERSONAL_KNOWLEDGE_USER_ID`，完成个人知识多用户隔离。
- [ ] 在 FAB 内网部署独立的 `Fab Data MCP Server`，由服务端持有 Oracle 连接池和凭证，Agent 与浏览器均不得直接连接 Oracle。
- [ ] 为 MCP Server 建立最小权限 Oracle 应用账号和角色，只授权经过治理的 View、Materialized View 或 Package，不直接开放基础生产表。
- [ ] 将用户、部门、产品、设备和厂区权限传递给 MCP，在 Oracle View/VPD/RLS 与 MCP 工具层同时执行行列级过滤。
- [ ] 为工具调用记录用户、工具名、参数摘要、数据时间范围、返回行数、耗时和错误码；日志不得记录 Oracle 凭证、敏感配方或未脱敏正文。
- [ ] 增加危险操作人工确认；当前阶段继续保持所有 Agent 数据工具只读。

### P1：Oracle MCP 与受控查询

- [ ] 将 `reports.py` 中的固定报表函数迁移为领域化 MCP 工具，例如 `get_lot_history`、`get_equipment_events`、`get_spc_violations`、`get_yield_trend` 和 `get_wafer_defect_summary`。
- [ ] MCP 工具只接受类型化业务参数；SQL 由服务端固定模板、存储过程或查询编译器生成，不提供通用 `execute_sql(sql)` 工具。
- [ ] 用受控语义查询替换当前 `safe_select` Text-to-SQL：模型只输出指标、维度、过滤条件、聚合粒度和限制，服务端负责参数化 SQL、允许的 JOIN 路径和成本控制。
- [ ] 仅在隔离的分析副本中保留受限 Text-to-SQL 作为兜底，并增加 SQL AST 校验、`EXPLAIN PLAN`、超时、最大扫描量、最大行数和只读事务保护。
- [ ] 建立查询限流、并发配额、熔断和缓存；优先查询只读报表库或同步副本，避免 Agent 查询影响 MES 等生产事务系统。
- [ ] 保持 MCP 工具输入输出结构与当前 Agent 工具兼容，使 ASP.NET Core、MCP 或 CLI 适配不要求重写模型提示词和前端。

### P1：RAG 与个人知识生产化

- [ ] 从 SQLite L0 迁移到 PostgreSQL、pgvector 和对象存储，使用多语种 Embedding、关键词召回、RRF 与重排组成混合检索。
- [ ] 将进程内 `BackgroundTasks` 替换为可认领、可重试、可观测的独立 Worker，并防止多实例重复处理同一文档。
- [ ] 为扫描型 PDF 增加隔离 OCR Worker、资源限制和恶意文件防护；OCR 完成前继续稳定返回 `OCR_REQUIRED`。
- [ ] 增加引用忠实度、无答案拒答、权限泄漏、删除残留、提示注入和真实用户查询评测，并为检索指标建立版本化基线。
- [ ] 保持两条数据路径：Oracle MCP Tools 负责实时结构化事实，RAG 负责 SOP、控制计划、历史案例和个人知识；历史案例只能用于提出和排序根因假设。

### P2：Skills、可观测性与上线验收

- [ ] 创建 `fab-analysis` Skill，规定良率、Cycle Time、OEE、Cpk、SPC 等指标口径，以及“固定报表 → 下钻数据 → RAG 知识 → 人工复核”的工具调用顺序。
- [ ] Skill 只保存业务规则、工具选择和结果解释方式，不保存 Oracle 密码、连接串、任意 SQL 或可绕过权限的指令。
- [ ] 将日志接入 OpenTelemetry 和集中存储，补充模型、MCP、Oracle、全文召回、向量召回和重排各阶段 P50/P95/P99。
- [ ] 建立上线验收：权限越权测试通过率 100%、写操作阻断率 100%、删除残留率 0、查询超时可回收、审计链路可追踪、MCP 故障不会影响生产数据库可用性。
