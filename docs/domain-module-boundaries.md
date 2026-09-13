# 领域模块归属与兼容基线

`evaluations/module_boundaries_v1.json` 是可执行的根模块清单。它列出每个
`app/*.py` 的目标、兼容理由、退出条件，以及生产、脚本、测试和 patch 的实际路径列表；清单与实际根文件必须一一对应。实现已迁入领域目录，但在缺少外部消费者迁移证据时，旧入口仍是受保护的公开兼容合同，不会仅因内部导入归零而删除。

| 当前根模块 | 目标归属 | 现有消费者与退出条件 |
|---|---|---|
| `main`, `agent`, `personal_knowledge` | 长期兼容入口 | `run.sh`/uvicorn、API 服务、评测和高频 patch 测试；外部调用和实时 patch 命名空间仍需保留 |
| `config`, `identity`, `__init__` | 包级锚点 | 启动、配置、认证和跨领域服务；没有领域迁移退出条件 |
| `agent_tools`, `assistant_capabilities`, `loop_guard` | `agent_runtime/` | 内部生产、脚本和普通回归均使用 canonical；`agent_tools` 对象身份边界测试仍保护公开目录/注册表。外部导入和 patch 合同有迁移证据后才可退役 |
| `context_resolver`, `decision_arbiter`, `sessions`, `turn_decision` | `conversation/` | 内部调用已使用 canonical；须先取得外部导入与私有 patch 点迁移证据 |
| `model_registry`, `model_compatibility`, `model_health`, `model_streaming` | `model_gateway/` | 旧入口保留兼容边界测试及 `model_health.db_session` 必需 patch；只有替代该实时 patch 合同并取得外部迁移证据后退役 |
| `evidence_semantics`, `evidence_validator`, `answer_synthesizer` | `evidence/` | Validator、Synthesis、Ready 和回放已使用 canonical；须先取得外部消费者迁移证据 |
| `rag`, `knowledge_decision`, `ocr`, `ocr_quality` | `knowledge/` | 知识/上传、OCR、RAG 评测已使用 canonical；OCR 继续从 `rapidocr.__file__` 定位本地模型，须先取得外部消费者迁移证据 |
| `processes`, `domain_playbooks`, `reports`, `enterprise_data`, `seed` | `manufacturing/` | 实现迁入 `manufacturing/`；旧入口保留为兼容门面，`python -m app.seed` CLI 行为保持 |
| `database`, `department_schemas`, `execution_store` | `persistence/` | SQLite 服务、管理脚本和系统 fixture；数据库路径、事务和脚本不变，须先取得外部消费者迁移证据 |
| `audit`, `observability`, `runtime_status` | `telemetry/` | 实现迁入 `telemetry/`；旧入口保留为兼容门面，日志、Trace、请求关联与运行状态契约不变 |
| `intent_router`, `planner` | `intent_runtime/`, `planning_runtime/` | 所有内部生产、脚本和普通回归均使用 canonical；仅 identity 边界测试保留旧入口。检查器以 AST 拒绝这些入口重新进入内部消费者清单；外部导入和私有 helper patch 合同迁出并有证据后才评估退役 |

`assistant_capabilities` 的 canonical 实现是纯模块边界；根路径仅作 import/re-export 门面。能力目录中的 `MODULE:app.context_resolver` 是冻结的用户可见标识，不随文件归档改写。

清单中逐项登记的消费者用于迁移决定；执行 `conda run -n fab-insight-agent python
scripts/check_module_boundaries.py --print-inventory` 会从当前树重新输出每个根入口的生产、
脚本、测试导入及字面量 patch 路径，作为可复查、只读的审计证据，避免静态报告过期。对 29 个已无内部 Python 生产/脚本消费者的过渡 facade，清单的 `internal_facades` 策略要求其实际 AST 清单与登记值完全一致，并明确拒绝新增生产或脚本消费者；相对、`from app import a, b`、函数内和字面量动态导入（包括带 `package` 的相对 `import_module`）都会被发现，字符串 fixture 不会被当作导入。`main`、`agent`、`personal_knowledge`、`config`、`identity` 是长期锚点；`seed` 的 shell CLI 和 `model_health.db_session` 的 live patch 作为非 AST 合同单独登记。
运行时 facade 的 `FunctionType` 命名空间会在调用时从旧入口读取依赖；
它是已验证的兼容机制，不能作为领域反向依赖的先例。

## 依赖规则

API 和协调器可以装配领域服务。领域模块不得导入 `app.main`、`app.agent` 或
`app.agent_runtime.coordinator`。纯 contracts、规则和制造计算模块不得导入数据库、入口
或协调器。当前树的 28 条既有跨领域遗留边逐条登记在 `existing_edge_exceptions`；每项均为精确
源/目标、迁移理由和退出条件，并非运行时或整个领域的白名单。未来例外同样必须逐项登记，
守卫拒绝空泛、通配或已失效的例外。

`scripts/check_module_boundaries.py` 用 AST 读取绝对、相对、函数内导入，以及字面量
`importlib.import_module`、别名 `import_module` 和 `__import__`。变量拼接的动态导入不能
静态证明，故仍由本清单和 facade 边界测试审计。它随 `scripts/check_repository.py` 进入
quick/full 质量门。

已人工核实的动态 patch 合同包括 `app.agent.*`、`app.main.*`、
`app.personal_knowledge.*` 和 `app.model_health.db_session`（`tests/test_model_health.py`）：
其具体测试路径同时记录在清单的 `patches` 列表中。`run.sh` 使用
`python -m app.seed` 与 `uvicorn app.main:app`；启动脚本测试覆盖 seed 后再启动 uvicorn，浏览器隔离服务测试通过 `app.main:app` 验证真实装配；`app.config` 用 `__file__` 定位项目根目录；
`app.ocr` 从 `rapidocr.__file__` 定位第三方模型资源。迁移这些模块时必须逐项复验。
