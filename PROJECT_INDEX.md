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

- 工具来源：MOD-009 已验证。`app/bootstrap/tool_sources.py` 显式组合七类 Port，覆盖 21 项原生工具；可选设备健康汇总通过注册进入 Ready/Loop，核心执行器未改。101 文件隔离、来源替换及完整离线门已通过，见 [验收报告](docs/reports/mod-009-tool-sources.md)。

- Skill 状态：MOD-016～019 已验证。`app/skills/` 处理声明、依赖、Catalog、渐进加载与进程内不可变发布；`app/bootstrap/skill_assembly.py` 显式装配精确 skill_refs，光刻包复用原 Playbook/Planner 与 Ready/Fake Loop/Dispatcher。完整资源固定、显式激活/禁用/回退已验收，默认 HTTP 未启用，见 [发布验收报告](docs/reports/mod-019-skill-releases.md)。

- 当前进度（2026-11-08 核对；源码基线 `c8d44cd`，MOD-015e）：MOD-001～019 均已验证，包含 MOD-012 模型网关与 MOD-015a～e Runtime 收口；受管源码 282 文件、依赖债务 11 条、兼容入口 7 个。MOD-020～023（Checkpoint/只读恢复）与 MOD-024～028（模块交付/内网集成）仍待完成，保留的兼容 facade 与配置锚点归 MOD-027。产品 TODO 为完成 183（含 2026-11-09 `DEPLOY-019` 跨平台本地模型启动器）、待做 45（用户暂缓 2、企业级暂缓 43），另有 4 项 OPTIONAL。当前任务状态见 [模块化追踪](docs/todos/modularization.md) 和 [产品执行计划](docs/todos/execution-plan.md)，实际验证范围、既有环境失败及 MOD-015d 历史统计待核实项见 [Runtime 收口报告](docs/reports/mod-015-runtime-convergence.md)。后续纯文档提交不改变该源码基线。
