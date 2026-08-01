# 测试策略与质量门

## QA-001 审计基线（2026-08-01）

审计前有 166 个 Python 测试、19 个 JavaScript 断言和 15 条 RAG 黄金集。完整宿主 Python 回归当时有 2 个失败；`app` 分支覆盖率为 81%。低覆盖重点为 `seed.py`（25%）、`database.py`（76%）、`agent.py`（77%）、`context_resolver.py`（78%）和 `personal_knowledge.py`（80%）。在 coverage run 中，`scripts/evaluate_rag.py`、`scripts/manage_databases.py` 和 `scripts/smoke_stream.py` 均为 0%；其中 RAG 评估另以独立命令实际通过 15/15，`smoke_stream.py` 会触发真实模型，不能进入自动门。

`test_system.py` 有约 49 项、耗时约 340 秒，且共享类级数据库；后续应按领域拆分并使用独立 fixture。前端约 99 个事件绑定目前仅有 19 个 JS 纯函数断言，尚无 DOM 或浏览器链路覆盖。

## 分层与原则

- 单元测试覆盖纯规则、解析、计划、RAG 决策和质量门命令构造。
- HTTP 契约测试覆盖公开 API 的成功、认证、脱敏和输入边界；系统测试覆盖跨库与后台任务工作流。
- RAG 黄金集独立评估召回、来源覆盖和禁止命中；不访问真实模型。
- 测试必须确定、隔离和可重复，负向路径与边界值和正常路径同等重要。测试日志可记录完整轨迹，但 API Key、Authorization、Password、Secret、Cookie 和 Token 始终脱敏。

在受限沙箱中，FastAPI 的同步端点会由 `anyio.to_thread` 调度；测试应避免把该调度限制误判为 API 契约失败，并不得以真实模型或浏览器依赖绕过隔离。

## 本地质量门

先安装测试依赖：

```bash
python -m pip install -r requirements-test.txt
```

快速门运行非 `test_system` Python、全部 Node 测试、全部静态 JS 语法检查和 RAG 黄金集：

```bash
python scripts/run_quality_gate.py quick
```

完整门运行全部 Python 的 `coverage --branch --source=app`，要求 `app/*` 至少 80%，然后执行同一组 Node、语法和 RAG 检查：

```bash
python scripts/run_quality_gate.py full
```

质量门在执行前以 AST 统计 unittest 风格测试方法，避免导入测试时污染环境；发现 0 个或少于当前 170 个下限即失败，命令首次失败即非零退出。覆盖数据写入 `runtime/quality/`。

## 完整审计触发条件

在发布或打标签前必须运行完整审计；以下变更也必须触发：依赖或 Python/FastAPI/SQLite 升级、Schema/API/认证/RAG/流式链路重大变化，或上次审计后累计约 5 个 feature/fix 任务。
