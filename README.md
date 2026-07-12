# Fab Insight Agent

一个可运行的虚拟半导体制造报表系统，包含 18 个月历史数据、制造 KPI、制程能力分析、设备异常检测、知识库 RAG，以及通过 DeepSeek 工具调用驱动的数据分析 Agent。

## 已实现能力

- 2,480 个制造批次、9,920 条制程记录、设备事件和缺陷记录
- 综合良率、周期时间、Hold、异常数等 KPI
- 周良率趋势、设备健康、缺陷 Pareto、近期异常批次
- CVD 膜厚 Cpk，以及 LITHO / ETCH / CMP 缺陷密度能力
- 内置可复现异常：近期 `CVD-02` 膜厚漂移、`CMP-03` 划伤风险
- DeepSeek Agent 多轮工具调用，支持固定报表和受限只读 SQL
- Agent 可观测性：运行成功率、延迟、Token、工具使用和错误类型
- SQLite FTS5 RAG，回答可引用厂内 SOP 和控制计划章节
- DeepSeek 不可用时自动提供本地规则分析

> 所有数据和知识文档均为演示用途，不代表真实工厂或量产规范。

## 快速启动

项目会自动读取 `D:\modern_agents\.env`，至少需要：

```dotenv
DEEPSEEK_API_KEY=your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
AGENT_LOG_PATH=logs/agent_events.jsonl
AGENT_LOG_MAX_BYTES=5242880
AGENT_LOG_BACKUP_COUNT=5
AGENT_LOG_CONTENT=metadata
```

在 WSL 中运行：

```bash
cd /mnt/d/modern_agents/agents/fab-insight-agent
./run.sh
```

在 Windows 中运行：

```bat
cd /d D:\modern_agents\agents\fab-insight-agent
run.bat
```

浏览器访问 <http://127.0.0.1:8765>，接口文档位于 <http://127.0.0.1:8765/docs>。

如环境缺少依赖：

```bash
python3 -m pip install -r requirements.txt
```

## 常用命令

重新生成相同分布的历史数据：

```bash
python3 -m app.seed --force
```

运行测试：

```bash
python3 -m unittest discover -s tests -v
```

## 架构

```text
浏览器报表 / 对话面板
          |
       FastAPI
      /       \
报表查询工具   DeepSeek Agent loop
      \       /       |
       SQLite     RAG / 受限 SQL
       历史库       FTS5 知识库
```

Agent 不直接访问数据库连接，而是通过 `app/agent.py` 中声明的工具工作。任意 SQL 仅允许单条 `SELECT`，限制在四张制造数据表并最多返回 100 行；数据库写入、DDL、PRAGMA 和系统表访问均被拒绝。

## Agent 日志与监控

前端“Agent 监控”页面每 30 秒刷新一次，也可直接查询：

```text
GET /api/monitor/summary?hours=24
GET /api/monitor/events?limit=100
```

日志默认写入 `logs/agent_events.jsonl`，达到 5 MB 后轮转并保留 5 份。每次 Agent 运行使用同一个 `run_id` 关联以下事件：

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
  rag.py        FTS5 知识检索
  audit.py      脱敏结构化日志、轮转和监控汇总
  seed.py       可复现历史数据生成器
  static/       报表与 Agent 前端
knowledge/      虚拟厂内 SOP / 控制计划
data/           生成的 SQLite 数据库
tests/          关键链路测试
logs/           Agent JSONL 审计日志（不提交）
```

## 接入真实 C# 系统

保留当前 Agent 和前端，只需把 `app/reports.py` 的查询函数替换为 ASP.NET Core API、MCP 工具或 CLI 调用。工具输入输出结构可以保持不变，因此模型侧提示词和前端不必重写。生产接入时还应增加身份认证、行级数据权限、审计日志、查询成本限制和危险操作人工确认。
