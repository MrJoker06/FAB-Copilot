# 领域模块归属与兼容基线

`evaluations/module_boundaries_v1.json` 是可执行的根模块清单。它列出每个
`app/*.py` 的目标、兼容理由、退出条件，以及生产、脚本、测试和 patch 的实际路径列表；清单与实际根文件必须一一对应。`REF-028`
至 `REF-033` 可以移动实现，但只有满足清单中的退出条件后，`REF-034` 才能删除旧入口。

| 当前根模块 | 目标归属 | 现有消费者与退出条件 |
|---|---|---|
| `main`, `agent`, `personal_knowledge` | 长期兼容入口 | `run.sh`/uvicorn、API 服务、评测和高频 patch 测试；外部调用和实时 patch 命名空间仍需保留 |
| `config`, `identity`, `__init__` | 包级锚点 | 启动、配置、认证和跨领域服务；没有领域迁移退出条件 |
| `agent_tools`, `assistant_capabilities`, `loop_guard` | `agent_runtime/` | 工具、Turn 与 Ready 测试；capabilities/guard 已在 REF-032 迁入 canonical，旧入口保留至 REF-034 审计 |
| `context_resolver`, `decision_arbiter`, `sessions`, `turn_decision` | `conversation/` | Agent facade、重放、API chat 与会话测试；已在 REF-032 迁入 canonical，旧入口保留至 REF-034 审计 |
| `model_registry`, `model_compatibility`, `model_health`, `model_streaming` | `model_gateway/` | 生产、脚本和非 health 测试已使用 canonical 路径；旧入口仅保留兼容边界测试及 `model_health.db_session` 必需 patch，REF-034 审计后退役 |
| `evidence_semantics`, `evidence_validator`, `answer_synthesizer` | `evidence/` | Validator、Synthesis、Ready 和回放；REF-033 更新消费者后退役 |
| `rag`, `knowledge_decision`, `ocr`, `ocr_quality` | `knowledge/` | 知识/上传、OCR、RAG 评测；REF-033 验证 OCR 外部模型资源定位后退役 |
| `processes`, `domain_playbooks`, `reports`, `enterprise_data`, `seed` | `manufacturing/` | 实现迁入 `manufacturing/`；旧入口保留为兼容门面，`python -m app.seed` CLI 行为保持 |
| `database`, `department_schemas`, `execution_store` | `persistence/` | SQLite 服务、管理脚本和系统 fixture；REF-029 已迁入，旧入口保留至 REF-034，数据库路径、事务和脚本不变 |
| `audit`, `observability`, `runtime_status` | `telemetry/` | 实现迁入 `telemetry/`；旧入口保留为兼容门面，日志、Trace、请求关联与运行状态契约不变 |
| `intent_router`, `planner` | 已有运行时 facade | 领域模块、评测和私有 helper 测试；现有 facade patch/import 契约迁出后才评估 |

`assistant_capabilities` 的 canonical 实现是纯模块边界；根路径仅作 import/re-export 门面。能力目录中的 `MODULE:app.context_resolver` 是冻结的用户可见标识，不随文件归档改写。

清单中逐项登记的消费者用于迁移决定；执行 `conda run -n fab-insight-agent python
scripts/check_module_boundaries.py --print-inventory` 会从当前树重新输出每个根入口的生产、
脚本、测试导入及字面量 patch 路径，作为可复查、只读的审计证据，避免静态报告过期。
运行时 facade 的 `FunctionType` 命名空间会在调用时从旧入口读取依赖；
它是已验证的兼容机制，不能作为领域反向依赖的先例。

## 依赖规则

API 和协调器可以装配领域服务。领域模块不得导入 `app.main`、`app.agent` 或
`app.agent_runtime.coordinator`。纯 contracts、规则和制造计算模块不得导入数据库、入口
或协调器。当前树的 26 条既有跨领域遗留边逐条登记在 `existing_edge_exceptions`；每项均为精确
源/目标、迁移理由和退出条件，并非运行时或整个领域的白名单。未来例外同样必须逐项登记，
守卫拒绝空泛、通配或已失效的例外。

`scripts/check_module_boundaries.py` 用 AST 读取绝对、相对、函数内导入，以及字面量
`importlib.import_module`、别名 `import_module` 和 `__import__`。变量拼接的动态导入不能
静态证明，故仍由本清单和 facade 边界测试审计。它随 `scripts/check_repository.py` 进入
quick/full 质量门。

已人工核实的动态 patch 合同包括 `app.agent.*`、`app.main.*`、
`app.personal_knowledge.*` 和 `app.model_health.db_session`（`tests/test_model_health.py`）：
其具体测试路径同时记录在清单的 `patches` 列表中。`run.sh` 使用
`python -m app.seed` 与 `uvicorn app.main:app`；`app.config` 用 `__file__` 定位项目根目录；
`app.ocr` 从 `rapidocr.__file__` 定位第三方模型资源。迁移这些模块时必须逐项复验。
