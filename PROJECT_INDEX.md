# Fab Insight Agent

- 分类：agents
- 简述：24个月多制程虚拟 FAB、传感器/设备状态/Wafer Map、历史会话、知识/案例双来源 RAG 与 DeepSeek 流式数据分析 Agent。
- 主要入口：`app/main.py`, `app/agent_runtime/service.py`, `app/agent_runtime/tools/`, `app/core/settings.py`, `app/core/identity.py`, `app/personal_knowledge_runtime/service.py`, `app/model_gateway/streaming.py`, `app/intent_runtime/`, `app/planning_runtime/`, `app/manufacturing/playbooks.py`, `app/persistence/database.py`, `app/telemetry/audit.py`, `app/conversation/sessions.py`, `app/agent_runtime/execution/loop_guard.py`, `app/knowledge/rag.py`, `app/evidence/validator.py`, `run.py`（跨平台隔离启动器）, `run.sh`, `run.bat`；`app/` 根目录仅保留包锚点与 HTTP 入口，内部代码只使用领域 canonical 路径
- 关键目录：`app/`, `app/manufacturing/`, `app/persistence/`, `app/telemetry/`, `app/model_gateway/`, `app/conversation/`, `app/agent_runtime/`, `app/knowledge/`（RAG、OCR、检索决策）, `app/evidence/`（语义、验证、答案综合）, `app/static/`, `knowledge/`, `cases/`, `evaluations/`, `scripts/`, `data/`, `tests/`
- 环境变量：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `FAB_DATABASE_PATH`, `FAB_DATABASE_DIR`, `API_TIMEOUT_MS`, `AGENT_LOG_PATH`, `AGENT_RUN_LOG_DIR`, `AGENT_LOG_MAX_BYTES`, `AGENT_LOG_BACKUP_COUNT`
- 本地产物：`data/fab_history.db`, `data/departments/*.db`, `backups/databases/`, `logs/agent_events.jsonl*`, `logs/agent/YYYY-MM-DD/<run_id>.jsonl`, `__pycache__/`
- 检索关键词：semiconductor, fab report, DeepSeek, agent, agent loop guard, tool budget, duplicate call detection, intent router, domain playbook, structured planner, RAG, SQLite, FTS5 trigram, knowledge base, historical cases, yield, Cpk, equipment health
- 维护建议：新增知识或案例时同步更新 catalog 和 `evaluations/rag_gold.json`，先运行 `scripts/evaluate_rag.py`；真实系统接入时将报表工具替换为受认证的 API/MCP，并补充数据权限与审计。

- 启动方式：原生 Windows 使用 `run.bat` + `.venv-win`，Linux/WSL 使用 `bash run.sh` + `.venv-linux` 或既有 Conda；共享 Python 入口 `run.py`，`--check` 为无启动副作用诊断，默认固定源码 snapshot，开发可显式使用 worktree。

- Skill 状态：MOD-016～019 已验证。`app/skills/` 处理声明、依赖、Catalog、渐进加载与进程内不可变发布；`app/bootstrap/skill_assembly.py` 显式装配精确 skill_refs，光刻包复用原 Playbook/Planner 与 Ready/Fake Loop/Dispatcher。完整资源固定、显式激活/禁用/回退已验收，默认 HTTP 未启用。下一项 MOD-009，见 [发布验收报告](docs/reports/mod-019-skill-releases.md)。
