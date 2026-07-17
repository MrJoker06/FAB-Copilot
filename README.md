# Fab Insight Agent

一个可运行的虚拟半导体制造报表系统，包含 24 个月历史数据、制造 KPI、制程能力分析、设备异常检测、知识库 RAG，以及通过 OpenAI 兼容模型工具调用驱动的数据分析 Agent。

## 已实现能力

- 约 9,500 个制造批次、170,000 条分层工序、100 万条传感器记录、28 台设备及对应状态、事件和缺陷记录
- 企业模拟数据适配器按签名游标提供 2,500 万虚拟批次、4.5 亿工序和 36 亿传感器事件，无需在本地物化全部记录
- 企业聚合接口按租户、日期、制程和设备返回确定性投影 KPI、风险排序及数据血缘，Agent 不再从明细样本外推全量结论
- 请求级租户与用户上下文隔离个人知识和历史会话；默认演示身份兼容现有单用户页面
- 用户端与管理端分离：用户端保留个人知识上传和模型选择，管理端集中查看用户运行状态、运行记录并发布或停用模型
- 模型目录和用户偏好持久化到 AI 运营库；模型凭据由服务端统一管理，不向用户端开放填写入口
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
- 个人知识库支持私有文件上传、异步解析、分块索引、Agent 三路融合检索、来源跳转、下载、重试和完整删除；扫描件会明确返回 `OCR_REQUIRED`
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
FAB_ENTERPRISE_MODE=true
FAB_DATA_PROVIDER=synthetic
FAB_DEFAULT_TENANT_ID=demo-fab
FAB_DEFAULT_USER_ID=local-user
FAB_REQUIRE_IDENTITY=false
FAB_MOCK_SEED=20260717
FAB_MOCK_VIRTUAL_LOTS=25000000
FAB_MOCK_CURSOR_SECRET=replace-with-a-long-random-secret
FAB_ADMIN_API_TOKEN=replace-with-a-long-random-admin-token
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

本并行方案默认使用独立端口。用户端访问 <http://127.0.0.1:8876>，管理端访问 <http://127.0.0.1:8876/admin>，接口文档位于 <http://127.0.0.1:8876/docs>。

企业模拟数据接口、租户请求头和真实数据源替换契约见 [企业化并行方案](docs/enterprise-transition.md)。
用户端、管理端、模型发布和管理认证边界见 [用户端与管理端分离设计](docs/user-admin-separation.md)。
项目已完成项和后续任务按工作流维护在 [TODO 总清单](TODO.md)。

## 模型切换

点击用户端右上角的模型按钮，可以在管理端已发布模型中切换。用户不能自行填写模型名称、API 地址或 API Key。新数据库默认发布：

- `deepseekv4-flash`
- `deepseekv4-pro`

管理员可以在 `/admin` 发布新的 DeepSeek 或 OpenAI Compatible 模型。模型目录持久化保存 `model_id`、显示名称、Provider Model、Base URL、能力与发布状态；停用模型会立即从用户选择列表移除。

也可以直接调用：

```text
GET  /api/settings/model
POST /api/settings/model
```

```json
{
  "model": "deepseekv4-pro"
}
```

模型偏好按租户和用户写入 AI 运营库。接口只接受已发布的 `model_id`，额外提交 `api_key` 等字段会被拒绝。当前样例由服务端 `.env` 的 `DEEPSEEK_API_KEY` 提供模型凭据；生产环境应替换为企业 Secret Manager 或受管模型网关。

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
用户端 /                  管理端 /admin
报表·对话·个人知识·模型选择   用户状态·运行记录·模型发布
            \              /
                 FastAPI
              /            \
       报表与 Agent 工具      管理 API
              \            /
        部门数据库联邦 · 模型目录 · 联合 RAG
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
| AI运营 | `ai_operations.db` | 会话、消息、Agent运行、工具事件、回答来源、模型目录、用户模型偏好 |

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

个人知识库、权限隔离、上传处理，以及从 SQLite/FTS5、PostgreSQL/pgvector 到独立向量与全文检索集群的分级 RAG 方案，见 [个人知识库与分级 RAG 架构设计](docs/knowledge-base-rag-architecture.md)。当前网页可在“知识库”页面切换到“我的知识”，上传、查看处理进度、预览、下载、重试或删除个人文档。个人知识不共享；实现状态统一维护在 [RAG 与知识库 TODO](docs/todos/rag-knowledge.md)。

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
中文 trigram 候选召回（每来源 Top 30）
  -> 查询实体推断（站点 / 设备 / 缺陷）
  -> Active / Validated 状态过滤
  -> 站点、设备、缺陷、权威和案例置信度加权
  -> 低置信度案例抑制
  -> 知识与案例来源多样化
  -> 最终 Top 1-10
```

每个结果包含 `retrieval.lexical_rank`、`final_score`、`confidence`、`selection_reason` 和实际过滤条件。可通过只读调试接口检查：

```text
GET /api/rag/search?q=CMP-03划伤&process_step=CMP&equipment_id=CMP-03&defect_type=Scratch
```

### RAG 回归评测

黄金评测集位于 `evaluations/rag_gold.json`，当前覆盖10类典型问题。运行：

```bash
python3 scripts/evaluate_rag.py
```

评估输出包括命中率、来源覆盖率、MRR 和错误案例命中数。新增知识、案例或修改排序算法后，应先通过该评测再合并代码。当前基线要求全部问题命中、所需来源类型完整且错误案例命中为0。

## Agent 意图路由

每次 Agent 运行会在首次模型调用前执行确定性 Intent Router。路由结果随接口结果保存在 `intent_route`，包括 `intent`、`candidate_intents`、`process_steps`、`equipment_ids`、`time_range`、`data_requirements`、`risk_level` 和需要澄清的问题。路由只限定分析范围和推荐取证工具，不作为制造事实；未知或相近的多意图问题会要求澄清，不会静默猜测查询目标。

Router 之后会为制程能力异常、良率下降、设备故障、批次追踪和 SOP 查询选择版本化 Domain Playbook。接口结果中的 `domain_playbook` 保存模板编号、Schema 版本、Playbook 版本、必需/可选证据、字段契约、验收条件、分析问题、答案结构和安全约束。歧义问题只返回候选模板，澄清前不会混合执行；未覆盖意图继续使用通用 Agent 规则。

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
- `intent_routed`：结构化意图、制程、设备、时间范围、数据需求和风险等级
- `playbook_selected`：模板选择状态、Playbook 编号、版本和歧义候选
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
  intent_router.py  确定性问题分类、范围抽取与风险路由
  domain_playbooks.py  五类版本化领域证据与回答契约
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

## 接入真实 C# 系统

保留当前 Agent 和前端，只需把 `app/reports.py` 的查询函数替换为 ASP.NET Core API、MCP 工具或 CLI 调用。工具输入输出结构可以保持不变，因此模型侧提示词和前端不必重写。生产接入时还应增加身份认证、行级数据权限、审计日志、查询成本限制和危险操作人工确认。
