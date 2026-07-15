# Fab Insight Agent

一个可运行的虚拟半导体制造报表系统，包含 24 个月历史数据、制造 KPI、制程能力分析、设备异常检测、知识库 RAG，以及通过 DeepSeek 工具调用驱动的数据分析 Agent。

## 已实现能力

- 约 9,500 个制造批次、170,000 条分层工序、100 万条传感器记录、28 台设备及对应状态、事件和缺陷记录
- 综合良率、周期时间、Hold、异常数等 KPI
- 周良率趋势、设备健康、缺陷 Pareto、近期异常批次
- 覆盖光刻、刻蚀、CVD、PVD、扩散、离子注入、CMP、清洗和量测，各站点按自身关键量测与规格计算 Cpk
- 九类制程各有一个可复现异常场景，隐藏根因真值不向 Agent 开放
- DeepSeek Agent 多轮工具调用，支持固定报表和受限只读 SQL
- 工具执行期间实时展开路径；收到最终答案首批 Token 后立即折叠，Markdown 答案流式输出并支持一键复制
- 会话、消息、运行、工具和来源结构化保存到 AI 运营库；独立“历史会话”工作区可搜索、预览、继续、重命名、归档和恢复会话，右侧助手保留快速入口
- 归档会话会立即移出活跃列表并支持提示条撤销；归档管理区可恢复会话，永久删除需要明确确认且不可恢复
- Agent 可观测性：运行成功率、延迟、Token、工具使用和错误类型
- 68 个知识章节与 17 个固定格式历史案例
- SQLite FTS5 trigram 双来源 RAG，支持中文检索与引用跳转
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
AGENT_LOG_PATH=logs/agent_events.jsonl
AGENT_RUN_LOG_DIR=logs/agent
AGENT_LOG_MAX_BYTES=5242880
AGENT_LOG_BACKUP_COUNT=5
AGENT_LOG_CONTENT=metadata
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

左侧“知识库”包含 17 份制造文档、68 个稳定引用章节，覆盖光刻、刻蚀、CVD、PVD、扩散、离子注入、CMP、清洗、量测、SPC、Hold、Recipe 变更、根因分析、良率和数据治理。

左侧“案例库”包含 17 个结构化案例。案例源文件为 `cases/historical_cases.json`，每条记录必须包含：

```text
case_id, title, process_step, equipment_id, occurred_date, severity,
problem, solution, result, summary, tags
```

其中核心复用格式固定为“问题、解决方案、解决结果、案例总结”。启动时会校验字段并重建 trigram 索引。`search_knowledge` 会同时检索正式知识和历史案例，并返回：

- `KB-数字`：正式知识章节，可跳转到知识库对应位置。
- `CASE-...`：历史案例，可跳转到案例详情。

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

## Agent 日志与监控

前端“Agent 监控”页面每 30 秒刷新一次，也可直接查询：

```text
GET /api/monitor/summary?hours=24
GET /api/monitor/events?limit=100
```

汇总日志默认写入 `logs/agent_events.jsonl`，达到 5 MB 后轮转并保留 5 份；每次运行的完整事件同时写入 `logs/agent/YYYY-MM-DD/<run_id>.jsonl`。每次 Agent 运行使用同一个 `run_id` 关联以下事件：

- `agent_run_started`：问题长度、问题指纹和历史消息数
- `model_call_finished`：模型、延迟、Token 和状态
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

## 接入真实 C# 系统

保留当前 Agent 和前端，只需把 `app/reports.py` 的查询函数替换为 ASP.NET Core API、MCP 工具或 CLI 调用。工具输入输出结构可以保持不变，因此模型侧提示词和前端不必重写。生产接入时还应增加身份认证、行级数据权限、审计日志、查询成本限制和危险操作人工确认。
