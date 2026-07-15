# Fab Insight Agent

- 分类：agents
- 简述：24个月多制程虚拟 FAB、传感器/设备状态/Wafer Map、历史会话、知识/案例双来源 RAG 与 DeepSeek 流式数据分析 Agent。
- 主要入口：`app/main.py`, `app/agent.py`, `run.sh`, `run.bat`
- 关键目录：`app/`, `app/static/`, `knowledge/`, `cases/`, `evaluations/`, `scripts/`, `data/`, `tests/`
- 环境变量：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `FAB_DATABASE_PATH`, `FAB_DATABASE_DIR`, `API_TIMEOUT_MS`, `AGENT_LOG_PATH`, `AGENT_RUN_LOG_DIR`, `AGENT_LOG_MAX_BYTES`, `AGENT_LOG_BACKUP_COUNT`
- 本地产物：`data/fab_history.db`, `data/departments/*.db`, `backups/databases/`, `logs/agent_events.jsonl*`, `logs/agent/YYYY-MM-DD/<run_id>.jsonl`, `__pycache__/`
- 检索关键词：semiconductor, fab report, DeepSeek, agent, RAG, SQLite, FTS5 trigram, knowledge base, historical cases, yield, Cpk, equipment health
- 维护建议：新增知识或案例时同步更新 catalog 和 `evaluations/rag_gold.json`，先运行 `scripts/evaluate_rag.py`；真实系统接入时将报表工具替换为受认证的 API/MCP，并补充数据权限与审计。
