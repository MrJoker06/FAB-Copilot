# MOD-001 便携单元基线记录

构建 ID：`mod-001-20261021-r1`。父提交：`0c93cf6075e181caf1e61dfbcc6c616ff3a0f7e4`。构建来源是有意保留的未提交工作树；该提交只能识别 Git 基线，不能代表本次已审查的全部本地改动。

## 范围与发现

本工作包收口七个既有的隔离源码单元：`memory_core`、`decision_core`、`model_transport`、`enterprise_data_contract`、`retrieval_policy`、`factory_search_contract`、`identity_contract`。源文件、测试和清单由 `portable_units_v1.json` 显式列出；完整审查分组、环境、产物路径和验证记录在 [机器可读记录](../../evaluations/mod_001_portable_baseline_v1.json)。用户工作簿 `fab_litho_agent_gantt_boss.xlsx` 不属于本次交付，未修改或打包。

审查发现 `IdentityClaims` 是冻结 dataclass，但直接传入可变角色列表会保留同一列表；直接传入字符串会被按字符迭代而被错误接受。现已在构造时复制为 tuple，拒绝 `str`、`bytes`、非序列、空角色与无效角色元素；`valid_identifier` 也会为非字符串返回 `False`，认证 scheme 的非字符串输入得到稳定的 `ValueError`。现有 Header 解析、`Principal` API 和 middleware 的 401/400 合约保持不变。

## 交付与验收

产物位于被忽略目录 `runtime/portable/mod-001-20261021-r1/`，共七个 ZIP。每个 ZIP 由现有构建器在临时目录解压，检查清单、静态 `app.*` 导入和该单元的离线 smoke test。`model_transport` 的唯一外部要求是 `httpx>=0.28,<1`；本次环境为 WSL Ubuntu-24.04、Linux x86_64、Python 3.11.15、httpx 0.28.1。

实际执行结果：

- `python -m unittest tests.test_portable_units tests.test_enterprise_data_contract_portable tests.test_enterprise_provider_boundary tests.test_factory_search_contract_portable tests.test_factory_search_backend_boundary tests.test_identity_contract_portable tests.test_identity_boundary tests.test_model_transport_portable tests.test_retrieval_policy_portable tests.test_refactor_contracts tests.test_module_boundaries`：75 项通过。
- `python scripts/build_portable_unit.py --verify --output-dir runtime/portable/mod-001-20261021-r1`：7 个 ZIP 构建并在仓库外验证通过。
- `python scripts/check_repository.py`：仓库检查与模块边界基线通过。
- `python -m unittest -v tests.system.test_http_contracts.HttpContractsSystemTests.test_enterprise_context_resolves_request_identity tests.system.test_sessions_streaming.SessionsStreamingSystemTests.test_sessions_are_isolated_by_tenant_and_user tests.system.test_knowledge_uploads.KnowledgeUploadsSystemTests.test_rag_returns_cited_source tests.system.test_knowledge_uploads.KnowledgeUploadsSystemTests.test_rag_infers_chinese_process_and_defect_aliases tests.system.test_knowledge_uploads.KnowledgeUploadsSystemTests.test_rag_uses_database_managed_defect_aliases tests.system.test_knowledge_uploads.KnowledgeUploadsSystemTests.test_rag_gold_dataset tests.system.test_knowledge_uploads.KnowledgeUploadsSystemTests.test_knowledge_documents_support_chunk_navigation tests.system.test_knowledge_uploads.KnowledgeUploadsSystemTests.test_historical_cases_keep_validated_catalog_and_missing_case_404`：8 项通过。
- `python scripts/evaluate_rag.py`：15/15 通过，hit rate、source coverage 和 MRR 均为 1.0。
- `git diff --check`：通过。

主审另在 `/tmp/mod-001-primary-review/` 独立构建全部七个 ZIP，并以 `diff -qr` 与 `runtime/portable/mod-001-20261021-r1/` 比较，文件内容完全一致；这是可复现构建证据，不引入内容哈希校验。

系统测试初始化会写入共用 SQLite 演示库，因此 8 项系统回归与 RAG 评测必须串行执行。曾在并行运行时观察到 `database is locked`，属于测试夹具的写锁竞争；串行重跑后两组验收均通过，不作为产品回归失败。

## 已知限制与后续

这些 ZIP 是隔离源码包，不能作为可并装的 wheel 或服务直接组合发布。`app/__init__.py`、`app/manufacturing/__init__.py`、`app/manufacturing/processes.py` 和 `app/knowledge/__init__.py` 在多个单元重复，后续组合交付前须在 `MOD-003` 明确唯一发布所有者或版本一致 Bundle。

本工作包未完成生产模型接入、真实企业数据 Adapter、生产 ACL/SSO、统一 Tool Dispatcher、Runtime 解耦或 Checkpoint 恢复。未收录数据库、日志、`.env` 或凭据，也未增加 SHA-256 或其他内容哈希校验。下一项为 `MOD-002`，用于冻结更完整的行为和性能基线。

## 后续清单版本说明

本报告的历史证据固定为 MOD-001 r1 的七个 1.0.0 单元。后续 MOD-002 在 `decision_core` 中新增等价序列化 helper，当前清单将该单元标为 1.0.1；这不是对本报告的历史验收重写。r5 的七单元仓库外 verify 已通过，但不替代 MOD-002 的性能门结论。
