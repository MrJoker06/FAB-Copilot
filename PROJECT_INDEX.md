# Fab Insight Agent

- 分类：agents
- 简述：24个月多制程虚拟 FAB、传感器/设备状态/Wafer Map、历史会话、知识/案例双来源 RAG 与 DeepSeek 流式数据分析 Agent。
- 当前主架构：V2 模块化服务；`app/` 保留为 V1 回归与迁移兼容实现。
- V2 入口：`services/api/`, `services/data-mcp/`, `web/`, `run-v2.sh`, `run-v2.bat`, `compose.yaml`
- V2 公共包：`packages/fab-contracts/`, `packages/fab-core/`, `packages/fab-agent/`
- V1 兼容入口：`app/main.py`, `app/agent.py`, `run.sh`, `run.bat`
- 内容与评测：`knowledge/`, `cases/`, `evaluations/`, `scripts/`, `tests_v2/`, `tests/`
- 环境变量：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `FAB_API_ADMIN_API_TOKEN`, `FAB_DATABASE_PATH`, `FAB_DATABASE_DIR`, `FAB_API_DATABASE_PATH`, `FAB_MCP_DATABASE_DIR`
- 本地产物：`data/`, `backups/databases/`, `logs/`, `web/dist/`, `web/node_modules/` 和各类 Python 缓存；均不纳入版本控制。
- 检索关键词：semiconductor, fab report, DeepSeek, agent, MCP, RAG, SQLite, FTS5 trigram, knowledge base, historical cases, yield, Cpk, equipment health
- 维护建议：新增能力遵循 `web -> API -> MCP` 依赖方向；新增知识或案例时同步更新 catalog 和 `evaluations/rag_gold.json`，先运行 `scripts/evaluate_rag.py` 和 `scripts/check_v2.sh`。
