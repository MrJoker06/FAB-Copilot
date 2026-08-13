# RAG 与知识库 TODO

## 已完成

- [x] `RAG-001` 建立工厂知识、历史案例和个人知识三类来源。
- [x] `RAG-002` 历史案例使用问题、解决方案、解决结果和案例总结的固定格式。
- [x] `RAG-003` 支持 PDF、DOCX、Markdown、TXT、CSV 和 XLSX 文本型文件上传。
- [x] `RAG-004` 支持个人文档上传、处理状态、预览、下载、重试和删除。
- [x] `RAG-005` 按租户和用户隔离个人文档、分块和检索结果。
- [x] `RAG-006` 使用 SQLite FTS5、术语扩展、元数据过滤和三路融合重排。
- [x] `RAG-007` 回答来源可以跳转到对应知识分块或历史案例。
- [x] `RAG-008` 对低置信度检索结果限制确定性结论。
- [x] `RAG-009` 扫描件不会以空文本静默入库。
- [x] `RAG-010` 建立 RAG 黄金数据集与召回测试。
- [x] `RAG-011` 使用 RapidOCR/ONNX Runtime 的 wheel 内置模型离线识别扫描 PDF 与 PNG/JPEG/TIFF 设备截图；保留原生 PDF 文本和页码，以检测框阅读顺序重组成行并以制表符保留列；输入有真实格式、EXIF、页数和像素边界，失败分别标记为 `OCR_UNAVAILABLE`、`OCR_FAILED` 或 `INVALID_FILE_CONTENT`。
- [x] `RAG-012` 建立固定离线 OCR 黄金集、版本化质量策略与按类别报告；低质量 OCR 以 `OCR_QUALITY_LOW` 拒绝入库，RAG-024 的可选 Ragas 候选保持未激活。
- [x] `RAG-016` 使用 owner 隔离的 SSE 推送每文档最新处理快照；断线重发当前 SQLite 真值，有限重连失败才降级轮询，终态自动释放连接。
- [x] `RAG-021` 知识型问题在模型调用前分别检索个人与工厂知识，按证据等级执行混合补充或模型兜底，并记录可审计的降级状态。
- [x] `RAG-022` 中文制程查询优先保留领域实体及中英文别名，再执行通用分词；英文个人文档可被对应中文问题召回，中等置信结果仍需语义或元数据证据。
- [x] `RAG-023` 在个人文档完成文本解析后自动生成可检索 Tag，并记录自动解析与用户修订的来源状态；人工 Tag 在重试、重新分块或索引刷新时不会被覆盖。

## 待做

- [ ] `RAG-013` 迁移到 PostgreSQL/pgvector，并引入多语种 Embedding 与 HNSW。
- [ ] `RAG-014` 将原始文件迁移到 MinIO 或兼容 S3 的对象存储。
- [ ] `RAG-015` 将解析、分块、向量化和删除迁移到异步 Worker。
- [ ] `RAG-017` 支持大文件分片和预签名上传。
- [ ] `RAG-018` 达到数据量阈值后引入 OpenSearch 与 Qdrant 的混合检索。
- [ ] `RAG-019` 增加独立 Retrieval Service、RRF、去重、重排和来源配额。
- [ ] `RAG-020` 为工厂知识与案例实现 ACL 过滤，并保证过滤发生在召回阶段。

## 可选候选（不一定需要）

- `RAG-024` `OPTIONAL`：评估是否接入 Ragas 体系。保留现有确定性 Hit Rate、MRR、Source Coverage、Forbidden Hits、ACL 与引用页码门；候选增加 Context Precision/Recall、Faithfulness/Response Groundedness、Answer Relevancy、Factual Correctness、Noise Sensitivity。评审模型和 embedding 必须固定并显式配置，禁止隐式联网；先仅观察报告，稳定后才可成为阻断门。只有后续需求明确激活时才执行、计数和排期。
