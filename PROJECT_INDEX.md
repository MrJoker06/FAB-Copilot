# Fab Insight Agent

- 分类：agents
- 简述：24个月多制程虚拟 FAB、传感器/设备状态/Wafer Map、历史会话、知识/案例双来源 RAG 与 DeepSeek 流式数据分析 Agent。
- 主要入口：`app/main.py`, `app/agent_runtime/service.py`, `app/agent_runtime/tools/`, `app/core/settings.py`, `app/core/identity.py`, `app/personal_knowledge_runtime/service.py`, `app/model_gateway/streaming.py`, `app/intent_runtime/`, `app/planning_runtime/`, `app/planning_runtime/playbooks.py`, `app/persistence/database.py`, `app/telemetry/audit.py`, `app/conversation/sessions.py`, `app/agent_runtime/execution/loop_guard.py`, `app/knowledge/rag.py`, `app/evidence/validator.py`, `run.py`（跨平台隔离启动器）, `run.sh`, `run.bat`；`app/` 根目录仅保留包锚点与 HTTP 入口，内部代码只使用领域 canonical 路径
- 关键目录：`app/`, `app/tools/`, `app/demo_data/`, `app/persistence/`, `app/telemetry/`, `app/model_gateway/`, `app/conversation/`, `app/agent_runtime/`, `app/knowledge/`（RAG、OCR、检索决策）, `app/evidence/`（语义、验证、答案综合）, `app/static/`, `knowledge/`, `cases/`, `evaluations/`, `scripts/`, `data/`, `tests/`
- 环境变量：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `FAB_DATABASE_PATH`, `FAB_DATABASE_DIR`, `API_TIMEOUT_MS`, `AGENT_LOG_PATH`, `AGENT_RUN_LOG_DIR`, `AGENT_LOG_MAX_BYTES`, `AGENT_LOG_BACKUP_COUNT`
- 本地产物：`data/fab_history.db`, `data/departments/*.db`, `backups/databases/`, `logs/agent_events.jsonl*`, `logs/agent/YYYY-MM-DD/<run_id>.jsonl`, `__pycache__/`
- 检索关键词：semiconductor, fab report, DeepSeek, agent, agent loop guard, tool budget, duplicate call detection, intent router, domain playbook, structured planner, RAG, SQLite, FTS5 trigram, knowledge base, historical cases, yield, Cpk, equipment health
- 维护建议：新增知识或案例时同步更新 catalog 和 `evaluations/rag_gold.json`，先运行 `scripts/evaluate_rag.py`；真实系统接入时将报表工具替换为受认证的 API/MCP，并补充数据权限与审计。

- 启动方式：原生 Windows 使用 `run.bat` + `.venv-win`，Linux/WSL 使用 `bash run.sh` + `.venv-linux` 或既有 Conda；共享 Python 入口 `run.py`，`--check` 为无启动副作用诊断，默认固定源码 snapshot，开发可显式使用 worktree。

- 工具来源：MOD-009 已验证。`app/bootstrap/tool_sources.py` 显式组合七类 Port，覆盖 21 项原生工具；可选设备健康汇总通过注册进入 Ready/Loop，核心执行器未改。101 文件隔离、来源替换及完整离线门已通过，见 [验收报告](docs/reports/mod-009-tool-sources.md)。

- Skill 状态：MOD-016～019 已验证。`app/skills/` 处理声明、依赖、Catalog、渐进加载与进程内不可变发布；`app/bootstrap/skill_assembly.py` 显式装配精确 skill_refs，光刻包复用原 Playbook/Planner 与 Ready/Fake Loop/Dispatcher。完整资源固定、显式激活/禁用/回退已验收，默认 HTTP 未启用，见 [发布验收报告](docs/reports/mod-019-skill-releases.md)。

- 当前进度（2026-11-12）：MOD-031a～e 已实现并按基线对照验收，见 [实施报告](docs/reports/mod-031-validator.md)；默认及显式 Skill 的业务规则、统一报告、编排和答案约束已分开。Windows 全量 1467 项仍有起点同名的 12 失败/10 错误，full 门未通过。受管源码 309（281 Python + 28 静态）、依赖债务 10、兼容入口 7/消费 95；产品统计不变。MOD-031 实施起点为 638f772，完成提交为 7859df9；本轮重审工作分支为 experiment/parallel-platform，提交及远程同步状态以 Git 记录为准。

- local-Qwen Thinking 合并：按模型配置档位与方言、管理端设置、Windows 夹具适配及必要冲突修正已验证，见 [合并报告](docs/reports/local-qwen-thinking-merge.md)。

- 后续计划：MOD-031 已实现，规则版本及未验证范围见 [报告](docs/reports/mod-031-validator.md)。MOD-029 的[重审稿 v2.0](docs/tool-result-offloading-plan.md)已按 MOD-030/031 实施结果更新，待审核、未实施；模块化待做 9 项（020～023、025～029），不自动启动下一项或企业真实接入。

- 当前结构：业务 Tool 与真实来源归 app/tools，Fake/模拟 Provider/seed 归 app/demo_data；规划视图与选择归 planning_runtime，证据声明及业务规则的唯一来源归 app/skills/policies，默认装配归 bootstrap。旧制造/接入目录已退出。历史 v4 参考保留旧成员标识，不代表当前运行依赖旧目录。

- TODO 维护：当前待办见 [TODO](TODO.md)；完成任务的定义和验收统一由[完成索引](docs/todos/completed.md)链接至归档，历史施工顺序见[执行历史](docs/todos/execution-history.md)。核心清单不再展开已完成任务，产品统计仍为 228/183/45。
