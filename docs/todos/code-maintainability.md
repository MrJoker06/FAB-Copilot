# 代码可维护性 TODO

本文件仅维护未完成任务和未激活的可选候选。已完成 33 项，定义与验收见[归档](archive/code-maintainability.md)；[完成索引](completed.md)。

当前没有已排期的未完成产品任务。

## 可选候选（不一定需要）

- `REF-025` `OPTIONAL`：建立 `answer_synthesis_runtime/{contracts,tool_schema,parsing,claim_guard,rendering,service}.py`，保留 `app/answer_synthesizer.py` 兼容门面。冻结 `SUBMIT_ANALYSIS_TOOL` 完整 Schema 哈希、`AnswerContract`/报告/结果身份、source ref 规范化、结构化语义验证、范围/因果过度声明降级、模型知识披露、章节顺序、中文措辞和 legacy answer。验收覆盖 Answer Synthesizer、Evidence Validator/Semantics、Agent synthesis、Ready 与 Trace 回放；任何安全降级差异均回退。

- `REF-026` `OPTIONAL`：建立 `database_runtime/{schema,migrations,connections,departments,defect_catalog}.py`，保留 `app/database.py` 所有兼容导出。只重排现有 SQLite 实现，保持 `SCHEMA`/部门 Schema 执行结果、迁移顺序和幂等性、Row factory、Journal、busy timeout、ATTACH/TEMP VIEW、事务、legacy 搬迁、FTS rebuild、校验和缺陷别名完全不变。该任务不创建通用数据库抽象、不接入 MySQL/Oracle、不改 Schema，必须与 `DATA-019` 的 Provider 边界协调；验收至少覆盖 Database Manager、系统隔离快照、Schema/迁移等价、RAG/Session/模型持久化和宿主 full。

候选源自历史结构审计；其中目录和兼容入口为当时基线，启用前按当前源码重新核对。
