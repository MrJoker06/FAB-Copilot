# Fab Insight Agent

- 分类：agents
- 简述：虚拟半导体制造报表、历史数据库、FTS5 RAG 与 DeepSeek 数据分析 Agent。
- 主要入口：`app/main.py`, `app/agent.py`, `run.sh`, `run.bat`
- 关键目录：`app/`, `app/static/`, `knowledge/`, `data/`, `tests/`
- 环境变量：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `FAB_DATABASE_PATH`, `API_TIMEOUT_MS`, `AGENT_LOG_PATH`, `AGENT_LOG_MAX_BYTES`, `AGENT_LOG_BACKUP_COUNT`
- 本地产物：`data/fab_history.db`, `logs/agent_events.jsonl*`, `__pycache__/`
- 检索关键词：semiconductor, fab report, DeepSeek, agent, RAG, SQLite, FTS5, yield, Cpk, equipment health
- 维护建议：真实系统接入时将报表工具替换为受认证的 API/MCP，并补充数据权限与审计。
