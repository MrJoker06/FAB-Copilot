# RAG 与知识库 TODO

本文件仅维护未完成任务和未激活的可选候选。已完成 16 项，定义与验收见[归档](archive/rag-knowledge.md)；[完成索引](completed.md)。

## 企业级暂缓

- [ ] `RAG-013` 迁移到 PostgreSQL/pgvector，并引入多语种 Embedding 与 HNSW。

- [ ] `RAG-014` 将原始文件迁移到 MinIO 或兼容 S3 的对象存储。

- [ ] `RAG-015` 将解析、分块、向量化和删除迁移到异步 Worker。

- [ ] `RAG-017` 支持大文件分片和预签名上传。

- [ ] `RAG-018` 达到数据量阈值后引入 OpenSearch 与 Qdrant 的混合检索。

- [ ] `RAG-019` 增加独立 Retrieval Service、RRF、去重、重排和来源配额。

- [ ] `RAG-020` 为工厂知识与案例实现 ACL 过滤，并保证过滤发生在召回阶段。

## 可选候选（不一定需要）

- `RAG-024` `OPTIONAL`：评估是否接入 Ragas 体系。保留现有确定性 Hit Rate、MRR、Source Coverage、Forbidden Hits、ACL 与引用页码门；候选增加 Context Precision/Recall、Faithfulness/Response Groundedness、Answer Relevancy、Factual Correctness、Noise Sensitivity。评审模型和 embedding 必须固定并显式配置，禁止隐式联网；先仅观察报告，稳定后才可成为阻断门。只有后续需求明确激活时才执行、计数和排期。
