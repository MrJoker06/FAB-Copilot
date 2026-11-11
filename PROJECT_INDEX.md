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

- 当前进度（2026-11-11）：MOD-030a～e 已完成；按本轮允许既有失败的方案验收，双平台定向/启动/仓库外交付通过、Linux 浏览器 17/17 通过；Windows 全量保留起点可复现失败，full 质量门未通过，详见 [阶段报告](docs/reports/mod-030e-acceptance.md)。当前受管源码 303（275 Python + 28 静态）、依赖债务 9、兼容入口 7；产品统计不变。应用源码基线 0829d8c，起点 5239c04，本轮仅本地提交、不推送。

- local-Qwen Thinking 合并：按模型配置档位与方言、管理端设置、Windows 夹具适配及必要冲突修正已验证，见 [合并报告](docs/reports/local-qwen-thinking-merge.md)。

- 后续计划：MOD-030 标准与迁移已交付，见 [标准计划](docs/skill-tool-standardization-plan.md)。Validator 职责由 MOD-031 单独讨论；MOD-029 暂缓待重审，MOD-025～028 与 MOD-020～023 保持原依赖，不自动开启。模块化台账未完成 9 项，产品任务统计不变。

- MOD-030 当前结构：业务 Tool 与真实来源归 app/tools，Fake/模拟 Provider/seed 归 app/demo_data；Playbook 结构、原样声明与选择分属 planning_runtime。旧制造/接入目录已退出。历史 v4 参考元数据和构建脚本保留旧成员标识，原因见阶段报告；不代表当前运行依赖旧目录。
