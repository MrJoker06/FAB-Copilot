# 个人知识库与分级 RAG 架构设计

状态：第一期上传 API 已按 L0 本地架构实现；三端分离与 L1 PostgreSQL/pgvector 迁移待实施
适用项目：Fab Insight Agent  
最后更新：2026-07-16

## 1. 已确认决策

1. 知识来源分为工厂知识库、历史案例库和个人知识库，三者逻辑隔离，检索时按策略融合。
2. 个人知识永不共享。产品不提供共享给其他用户、部门或全厂的入口。
3. 个人文档只能被上传者检索、预览、引用、导出和删除；其他业务用户及其 Agent 均不可访问。
4. OCR 标记为待做，不进入第一期实现范围。第一期只接收能够直接提取文本的文件。
5. 历史案例继续使用“问题、解决方案、解决结果、案例总结”的固定结构，不按普通文档处理。
6. 原始文件、文档元数据、文本块、向量和索引均需支持完整删除，并保留可审计的删除事件。
7. 前端不直接连接文件存储、数据库或向量库；所有访问必须经过后端身份认证和数据服务权限校验。

“个人知识不共享”指业务访问层面的严格隔离。运维人员仅可按受审计的故障处理流程接触底层存储，不得通过普通检索接口查看个人内容。

## 2. 当前基线与目标

当前项目使用 SQLite FTS5 trigram 检索正式知识和历史案例，再依据制程、设备、缺陷、权威等级和案例置信度重排。个人知识上传 API 已使用独立文档、任务、文本块和 FTS 表实现本地闭环，并通过服务端固定用户或可选 Bearer Token 隔离。它是进入三端分离前的 L0 兼容实现，不替代 L1 的 PostgreSQL、pgvector 和正式登录体系。

目标形态：

```text
Frontend
  上传、任务进度、文档预览、检索测试、引用跳转
      |
Backend API
  登录身份、会话、Agent 编排、流式回答、访问令牌
      |
Data Service
  文件管理、解析、分块、索引、权限过滤、混合检索、删除
      |------------------|-------------------|
Object Storage       Metadata Store      Retrieval Index
原始文件              文档/权限/任务        全文/向量索引
```

第一期即使只有一个用户，也必须从登录上下文生成 `user_id`。客户端不得在上传或检索请求中自行声明所有者。

## 3. 知识来源与隔离

| 来源 | 所有者 | 可见范围 | 数据形态 | 用途 |
|---|---|---|---|---|
| 工厂知识库 | 工艺知识管理 | 授权用户 | SOP、OCAP、设备手册、规范 | 权威依据 |
| 历史案例库 | 良率/工艺治理 | 授权用户 | 固定结构案例 | 根因假设与经验复用 |
| 个人知识库 | 单一用户 | 仅上传者 | 用户文档、表格、笔记 | 个人上下文补充 |

三个来源使用独立的来源类型和索引命名空间。不能通过修改个人文档元数据将其升级为部门或工厂知识，也不设计共享审批流程。

检索前必须先确定访问主体，再构造不可被模型或客户端覆盖的服务端过滤条件：

```text
factory: 当前用户具备工厂知识读取权限
case:    当前用户具备案例读取权限
personal: owner_user_id = 当前登录用户
```

个人权限过滤必须同时应用于元数据查询、全文召回、向量召回、缓存、引用详情和文件下载，不能只在最终结果阶段过滤。

## 4. 建议数据模型

### 4.1 文档与任务

```text
knowledge_documents
- document_id             UUID
- source_type             factory / personal
- owner_user_id           个人文档必填，工厂文档为空
- filename
- title
- mime_type
- checksum_sha256
- version
- process_steps
- equipment_ids
- authority_level
- effective_date
- parser_version
- embedding_model
- status                  uploaded / parsing / indexing / ready / failed / deleting
- storage_key
- created_at / updated_at

knowledge_ingestion_jobs
- job_id
- document_id
- stage
- progress
- attempt
- error_code
- error_message
- started_at / completed_at
```

### 4.2 文本块

```text
knowledge_chunks
- chunk_id                UUID
- document_id
- owner_user_id           冗余权限字段，便于检索层强制过滤
- source_type
- page_number
- section_path
- chunk_index
- content
- content_hash
- token_count
- metadata_json
- embedding
- created_at
```

历史案例继续存放在独立的 `historical_cases` 结构中，保留治理状态、验证方法、根因置信度和审批信息。

### 4.3 去重与版本

- 同一用户下以 `checksum_sha256` 识别完全重复文件。
- 相同文件的新版本创建新 `document_id`，旧版本进入不可检索状态，不覆盖原记录。
- 每个文本块保存解析器版本和向量模型版本，便于定向重建索引。
- 工厂文档与个人文档不跨所有者去重，避免通过重复检测泄露他人是否上传过某份文件。

## 5. 文件接入与异步处理

第一期支持：

- PDF，仅限可直接提取文本的 PDF
- DOCX
- Markdown
- TXT
- CSV
- XLSX

处理流程：

```text
上传初始化
  -> MIME、扩展名、大小和文件签名校验
  -> 保存原始文件并计算 SHA-256
  -> 创建异步任务
  -> 提取文本和结构
  -> 按章节、步骤和表格语义分块
  -> 元数据提取与用户确认
  -> 生成向量
  -> 写入全文与向量索引
  -> 检索质量检查
  -> ready
```

上传请求只负责安全落盘和创建任务，不等待解析与向量生成完成。任务必须可重试且保持幂等。

### OCR：待做

OCR 不属于第一期：

- 扫描版 PDF 或图片不执行 OCR。
- 若 PDF 无法提取有效文本，状态标记为 `failed`，错误码为 `OCR_REQUIRED`。
- 前端明确提示“该文件需要 OCR，当前版本暂不支持”。
- 不生成空文本块，不允许无内容文档进入 `ready`。

后续 OCR 需要单独评估中文、英文、表格、公式、设备截图的识别质量，并建立带页码的人工抽检集后再启用。

## 6. 分块策略

FAB 文档包含编号步骤、参数表、告警代码和规格限制，不能仅按固定字符数切分。

- 优先按标题层级、段落、列表和分页边界切分。
- SOP 连续操作步骤保持完整，避免拆开前置条件与处置动作。
- 表格转为包含表名、表头和行上下文的结构化文本。
- 每块目标约 400 至 800 tokens，重叠约 10% 至 15%。
- 超长章节采用父子块：小块用于召回，父块用于交给模型。
- 每块保留文档、版本、页码、章节路径、制程和设备元数据。
- 历史案例以完整案例为主召回单元，同时对问题、根因和解决方案建立独立检索字段。

## 7. 统一检索流程

```text
用户问题与登录身份
  -> 服务端权限过滤
  -> 制程/设备/缺陷/日期实体识别
  -> 各来源并行关键词召回
  -> 各来源并行向量召回
  -> RRF 融合
  -> 元数据与治理状态过滤
  -> 跨编码器或模型重排
  -> 来源配额与去重
  -> Top 5-8 上下文
  -> 带文档、页码、章节和 chunk_id 的回答引用
```

默认来源配额应防止个人重复文档挤占全部上下文。建议候选阶段分别召回工厂知识、案例和个人知识，最终答案至少保留一个高权威工厂来源；若没有合适来源，应明确表示证据不足。

引用必须能跳转到用户有权访问的文档位置。引用链接不能作为权限凭据，打开时仍需再次鉴权。

## 8. 面向不同数据量级的 RAG 方案

以下区间按“可检索文本块”数量估算，文档数量仅作参考。阈值是容量规划起点，不是产品承诺；实际升级由延迟、吞吐、索引大小和召回质量共同决定。

### L0：演示与离线样例

适用范围：

- 小于 10,000 个文档
- 小于 100,000 个文本块
- 单用户或极低并发
- 检索负载低于 5 QPS

方案：

- SQLite 保存知识、案例和 FTS5 trigram 索引。
- 原始文件存本地目录。
- 可不生成向量，使用关键词召回和元数据重排。
- 进程内任务队列，仅用于开发和测试。

优点是零额外服务、部署简单。缺点是并发写入、后台任务、权限隔离、向量检索和横向扩容能力弱。

当前项目处于该级别。它只作为兼容基线，不作为个人上传功能的正式落点。

### L1：个人知识库正式起步，推荐目标

适用范围：

- 约 10,000 至 100,000 个文档
- 约 100,000 至 2,000,000 个文本块
- 5 至 50 QPS
- 单机或主从数据库可满足容量

方案：

- PostgreSQL 保存用户、文档、任务、权限和文本块元数据。
- `pgvector` 保存向量，使用 HNSW；批量冷数据可评估 IVFFlat。
- PostgreSQL 全文检索负责关键词召回。
- 原始文件通过存储适配器落本地目录，生产环境切换到 MinIO 或兼容 S3 的对象存储。
- Redis 负责短期任务状态、限流和按用户隔离的结果缓存。
- 独立 Worker 执行解析、分块和向量生成。
- PostgreSQL Row Level Security 作为个人数据隔离的第二道防线。

这是第一期推荐方案。即使初始数据很少，也避免把用户上传写入现有 SQLite 后再做高风险迁移。

索引建议：

- 全文索引按语言和字段建立。
- 向量索引携带 `owner_user_id`、`source_type` 和治理状态过滤条件。
- 缓存键必须包含 `user_id`、知识版本和检索策略版本。
- 大用户可按 `owner_user_id` 哈希分区，但不要为每个普通用户创建独立表。

### L2：中大型企业知识平台

适用范围：

- 约 100,000 至 1,000,000 个文档
- 约 2,000,000 至 20,000,000 个文本块
- 50 至 500 QPS
- 索引无法稳定驻留单机内存，或索引维护明显影响事务数据库

方案：

- PostgreSQL 继续保存权威元数据、权限、任务和版本。
- Qdrant 集群承载向量召回；按租户哈希分片，超大用户使用专属分片。
- OpenSearch 承载 BM25、中文分词、字段权重和关键词过滤。
- MinIO/S3 保存原始文件和解析产物。
- Redis 保存短期缓存、分布式锁和任务进度。
- 消息队列负责解析、向量化、索引和删除事件，建议使用 Kafka 或 RabbitMQ。
- 独立 Retrieval Service 并行请求 OpenSearch 与 Qdrant，执行 RRF、去重、重排和来源配额。

迁移到该级别时，不改变后端对数据服务的检索接口。向量和全文索引都是可重建派生数据，PostgreSQL 与对象存储仍是事实来源。

个人知识隔离策略：

- Qdrant payload 和 OpenSearch 文档都必须包含 `owner_user_id`。
- 服务端统一注入 owner filter，调用方不能删除或覆盖该过滤器。
- 不使用“每用户一个 collection/index”，避免大量小索引造成集群元数据膨胀。
- 对极少数超大用户采用专属 shard 或 index，并由路由表透明选择。

### L3：超大规模与多区域部署

适用范围：

- 超过 1,000,000 个文档
- 超过 20,000,000 个文本块
- 高于 500 QPS，或有多区域低延迟与容灾要求
- 每日持续大批量增量更新和重建索引

方案：

- PostgreSQL 分片或分布式元数据方案保存控制面数据。
- Qdrant、Milvus 或同类分布式向量集群承载多副本向量索引。
- OpenSearch 多集群承载全文检索，并按区域复制工厂知识索引。
- Kafka 作为文档变更日志，解析、嵌入、索引、删除均由幂等消费者处理。
- 对象存储启用版本、生命周期和跨区域复制。
- 在线索引与离线重建索引分离，通过别名原子切换。
- Retrieval Gateway 根据用户归属、数据驻留区域和负载路由请求。
- 热查询按用户和知识版本缓存，禁止跨用户复用个人检索结果。

此级别需要专门的容量管理、索引成本控制、数据驻留策略、灾难恢复演练和在线召回评测，不应在当前阶段提前建设。

## 9. 何时升级 RAG 架构

不能只依据文本块数量升级。满足以下任一持续性条件时进入容量评审：

- 检索服务 P95 延迟连续一周高于 300 ms，P99 高于 800 ms。
- PostgreSQL CPU 连续高于 70%，且主要开销来自向量或全文检索。
- 向量索引与活跃数据总量超过可用内存的约 70%。
- 索引构建、VACUUM 或备份明显影响在线请求。
- 新文档从上传到可检索的 P95 时间超过 5 分钟。
- 删除事件在 10 分钟内无法从所有索引完成清理。
- 峰值 QPS 下错误率超过 1%，或连接池长期超过 80%。
- 黄金评测集 Recall@10、MRR 或引用正确率因候选规模扩大而持续下降。

升级顺序建议：

1. 先优化分块、查询过滤、索引参数、连接池和缓存。
2. 再把向量召回从 PostgreSQL 迁到 Qdrant。
3. 然后把全文召回迁到 OpenSearch。
4. 最后才引入消息流、多区域和分布式控制面。

## 10. 个人知识库 API 契约

所有公开接口位于 Backend API。浏览器不能直接调用 Data Service，也不能直接访问 PostgreSQL、向量库或文件目录。

所有接口都要求登录：

```http
Authorization: Bearer <access_token>
```

L0 本地实现尚未接入正式登录系统：配置 `FAB_PERSONAL_KNOWLEDGE_API_TOKEN` 时按上述 Bearer Token 强制鉴权；未配置时使用服务端固定的 `FAB_PERSONAL_KNOWLEDGE_USER_ID=local-user`，只允许本机单用户开发。进入 L1 前必须替换为正式登录身份，API 路径和数据模型不变。

后端从访问令牌取得 `user_id`。以下任何请求都不接受 `owner_user_id`、`visibility`、`department_id` 或共享对象。新建文档的所有者永远是当前登录用户。

### 10.1 第一期：直接上传接口

第一期采用 `multipart/form-data`，适合不超过 50 MiB 的 PDF、DOCX、Markdown、TXT、CSV 和 XLSX。

```http
POST /api/knowledge/personal/documents
Authorization: Bearer <access_token>
Idempotency-Key: <UUID>
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | binary | 是 | 原始文件 |
| `metadata` | JSON string | 否 | 用户可编辑元数据，不包含所有者和可见范围 |

`metadata` 示例：

```json
{
  "title": "CMP-03 Pad 更换记录",
  "process_steps": ["CMP"],
  "equipment_ids": ["CMP-03"],
  "effective_date": "2026-07-01",
  "tags": ["pad", "maintenance"]
}
```

调用示例：

```bash
curl -X POST http://127.0.0.1:8765/api/knowledge/personal/documents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -F 'file=@CMP-03-pad-record.docx' \
  -F 'metadata={"process_steps":["CMP"],"equipment_ids":["CMP-03"]};type=application/json'
```

成功响应为 `202 Accepted`。上传完成只表示文件已经安全接收，解析和索引在后台继续执行。

```json
{
  "document_id": "23b2a160-3f13-4bf5-a65d-b2a45968c616",
  "job_id": "37dd3495-830a-47a5-8770-8020ad099476",
  "status": "uploaded",
  "filename": "CMP-03-pad-record.docx",
  "status_url": "/api/knowledge/jobs/37dd3495-830a-47a5-8770-8020ad099476"
}
```

上传约束：

- 默认单文件上限 50 MiB，通过服务端配置调整，前端限制不能替代服务端校验。
- `Idempotency-Key` 在当前用户范围内生效，重复请求返回同一个 `document_id` 和 `job_id`。
- 服务端同时校验扩展名、MIME、文件签名和 SHA-256。
- 用户不能指定 storage key、所有者、状态、权威等级或可见范围。
- 完全重复的文件只在当前用户自己的文档中检查，不进行跨用户去重探测。

### 10.2 处理状态与失败重试

查询任务：

```http
GET /api/knowledge/jobs/{job_id}
```

```json
{
  "job_id": "37dd3495-830a-47a5-8770-8020ad099476",
  "document_id": "23b2a160-3f13-4bf5-a65d-b2a45968c616",
  "status": "indexing",
  "stage": "embedding",
  "progress": 72,
  "attempt": 1,
  "error": null,
  "updated_at": "2026-07-16T15:21:08Z"
}
```

状态机：

```text
uploaded -> parsing -> chunking -> embedding -> indexing -> ready
                    \-> failed
ready / failed -> deleting -> deleted
```

失败任务由用户手动重试：

```http
POST /api/knowledge/personal/documents/{document_id}/retry
```

仅 `failed` 状态允许重试。重试创建新的 `job_id`，不会重复创建文档。

扫描版 PDF 在异步解析时进入 `failed`，任务返回：

```json
{
  "error": {
    "error_code": "OCR_REQUIRED",
    "detail": "该文件需要 OCR，当前版本暂不支持",
    "retryable": false
  }
}
```

第一期前端每 1 至 2 秒轮询任务接口。后续任务量增加时可增加 `GET /api/knowledge/jobs/{job_id}/events` SSE 接口，不改变任务数据结构。

### 10.3 个人文档管理

```text
GET    /api/knowledge/personal/documents
GET    /api/knowledge/personal/documents/{document_id}
PATCH  /api/knowledge/personal/documents/{document_id}
DELETE /api/knowledge/personal/documents/{document_id}
GET    /api/knowledge/personal/documents/{document_id}/content
GET    /api/knowledge/personal/documents/{document_id}/file
```

列表接口支持：

```http
GET /api/knowledge/personal/documents?status=ready&q=CMP&limit=20&cursor=<cursor>
```

返回内容必须限定为当前用户的个人文档。分页采用不透明 cursor，不使用高偏移量分页。

允许修改的字段只有：

```json
{
  "title": "CMP-03 Pad 更换与检查记录",
  "process_steps": ["CMP"],
  "equipment_ids": ["CMP-03"],
  "effective_date": "2026-07-01",
  "tags": ["pad", "maintenance"]
}
```

`PATCH` 不接受 owner、scope、visibility、status、storage key 或索引版本。

删除接口返回 `202 Accepted`，因为对象存储、全文索引、向量索引和缓存需要异步清理：

```json
{
  "document_id": "23b2a160-3f13-4bf5-a65d-b2a45968c616",
  "job_id": "70512683-977e-4584-a8c5-f8775b379809",
  "status": "deleting"
}
```

文档进入 `deleting` 后立即停止检索和下载。删除任务完成前，列表可以展示处理状态，但内容不可访问。

### 10.4 检索预览与引用跳转

用户可在知识库页面验证自己的文档能否被正确召回：

```http
POST /api/knowledge/personal/search-preview
Content-Type: application/json

{
  "query": "CMP-03 最近一次 Pad 更换后的检查结果",
  "limit": 10,
  "document_ids": []
}
```

`document_ids` 为空表示检索当前用户全部 `ready` 个人文档；非空时服务端仍逐一验证所有权。

引用跳转：

```http
GET /api/knowledge/personal/chunks/{chunk_id}
```

返回文档标题、页码、章节路径和文本块上下文。该接口必须重新鉴权，不能因为 `chunk_id` 出现在历史回答中就放行。

### 10.5 后续：大文件预签名上传

文件超过直接上传阈值或部署到对象存储后，增加三段式接口：

```text
POST /api/knowledge/personal/upload-sessions
PUT  <response.upload_url>
POST /api/knowledge/personal/upload-sessions/{upload_id}/complete
```

初始化请求：

```json
{
  "filename": "equipment-manual.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 83886080,
  "checksum_sha256": "<64-character hex>",
  "metadata": {
    "process_steps": ["ETCH"],
    "equipment_ids": ["ETCH-01"]
  }
}
```

响应：

```json
{
  "upload_id": "52f9a13d-d792-4986-993c-650c7698659e",
  "upload_url": "<short-lived presigned URL>",
  "method": "PUT",
  "required_headers": {"Content-Type": "application/pdf"},
  "expires_at": "2026-07-16T15:40:00Z"
}
```

对象上传完成后调用 `complete`。后端验证对象大小和 SHA-256，再创建 `document_id`、`job_id` 并返回与直接上传相同的 `202` 响应。仅向对象存储上传文件不会创建知识文档。

### 10.6 标准错误

所有错误使用统一结构：

```json
{
  "error_code": "UNSUPPORTED_FILE_TYPE",
  "detail": "当前不支持该文件类型",
  "retryable": false,
  "request_id": "req-..."
}
```

| HTTP 状态 | 错误码 | 场景 |
|---|---|---|
| 400 | `INVALID_METADATA` | 元数据格式或字段值不合法 |
| 401 | `AUTHENTICATION_REQUIRED` | 未登录或令牌失效 |
| 404 | `DOCUMENT_NOT_FOUND` | 文档不存在或不属于当前用户 |
| 409 | `DUPLICATE_DOCUMENT` | 当前用户已上传完全相同文件 |
| 409 | `INVALID_DOCUMENT_STATE` | 当前状态不允许修改、重试或删除 |
| 413 | `FILE_TOO_LARGE` | 超过直接上传或租户限制 |
| 415 | `UNSUPPORTED_FILE_TYPE` | 扩展名、MIME 或文件签名不支持 |
| 422 | `INVALID_FILE_CONTENT` | 文件损坏或无法解析 |
| 429 | `KNOWLEDGE_QUOTA_EXCEEDED` | 用户存储量、文档量或速率超限 |
| 500 | `INGESTION_FAILED` | 可重试的内部解析或索引错误 |

访问他人的 `document_id`、`chunk_id` 或 `job_id` 一律返回与不存在相同的 `404`，避免泄露资源存在性。

### 10.7 Backend 与 Data Service 内部接口

公开接口完成身份认证、配额和请求校验后，通过内部服务接口执行数据操作：

```text
POST   /internal/v1/knowledge/ingestions
GET    /internal/v1/knowledge/jobs/{job_id}
POST   /internal/v1/knowledge/retrieval
GET    /internal/v1/knowledge/chunks/{chunk_id}
DELETE /internal/v1/knowledge/documents/{document_id}
```

内部请求携带后端签名的主体信息和 `request_id`，不信任来自浏览器的身份字段。Data Service 仍需执行所有者过滤，不能只依赖 Backend 已经鉴权。

## 11. 前端交互要求

- 知识库页区分“工厂知识”“历史案例”“我的知识”，不出现部门共享入口。
- “我的知识”支持拖放上传、文件校验、处理进度、失败重试、预览、重命名和删除。
- 上传时允许补充标题、制程、设备和生效日期，但所有者不可编辑。
- 扫描件需要 OCR 时展示明确的待支持提示。
- 文档未达到 `ready` 前不可被 Agent 召回。
- 提供“测试检索”，展示命中的来源、页码、章节、分数和过滤原因。
- 对话引用点击后跳转到相应文档和文本块；没有权限时统一返回不可访问，不泄露文档是否存在。

## 12. 安全与隐私

- 校验文件签名、MIME、扩展名、大小和压缩包膨胀比例。
- 解析器在隔离 Worker 中运行，限制 CPU、内存、执行时间和网络访问。
- 文档内容始终视为不可信数据，不能执行其中的命令或把它当作系统提示。
- 原始文件使用不可预测的 storage key，不使用用户文件名作为路径。
- 下载使用短时效授权，日志不得记录文档正文和预签名地址。
- PostgreSQL RLS、数据服务过滤和引用接口鉴权形成多层隔离。
- 删除操作写审计日志，并异步确认对象、文本块、向量、全文索引和缓存均已清理。
- 备份中的个人文档按明确的保留周期到期清除。

## 13. 评测与可观测性

每次调整解析器、分块、嵌入模型、索引或排序算法都必须运行离线评测：

- Recall@5 / Recall@10
- MRR / NDCG
- 引用页码与章节正确率
- 权限泄露用例通过率，目标 100%
- 删除后残留检索率，目标 0
- 无答案问题的拒答准确率
- 工厂知识、案例和个人知识的来源覆盖率

在线监控至少包括：

- 上传成功率、解析失败类型和任务积压
- 文档可检索时间 P50/P95/P99
- 关键词、向量、重排和总检索延迟
- 各来源候选量、最终入选量和空召回率
- 每用户限流、存储量和文本块数量
- 权限过滤拒绝次数和异常跨用户访问尝试
- 删除任务完成时间和索引残留检查

## 14. 分阶段落地建议

### 阶段 A：三端边界和身份

- 建立 Frontend、Backend、Data Service 独立目录与接口契约。
- 引入登录身份和稳定 `user_id`。
- 保持现有 SQLite 工厂知识与案例只读，完成兼容适配。

### 阶段 B：L1 个人知识库

- 建立 PostgreSQL、pgvector、对象存储适配器和异步 Worker。
- 实现文本型文件上传、解析、分块、索引、预览和删除。
- 完成个人知识隔离、RLS 和权限回归测试。
- OCR 保持 `TODO`，扫描件返回 `OCR_REQUIRED`。

### 阶段 C：混合检索和治理

- 将工厂知识与历史案例导入统一检索协议。
- 实现全文加向量召回、RRF、重排、来源配额和引用跳转。
- 建立黄金集、权限集和删除残留评测。

### 阶段 D：按指标扩容

- 达到升级条件后再依次引入 Qdrant、OpenSearch、消息队列和分布式检索。
- 每次替换检索组件都保持 Data Service API 兼容，并支持索引双写、回放、对比和回滚。

## 15. 第一期开工前的验收约束

- 个人知识没有共享按钮、共享 API 或可修改可见范围字段。
- 任意用户无法通过列表、搜索、引用、下载、缓存或错误信息发现其他用户的个人文档。
- 支持的文本型文件能够异步进入 `ready`，失败任务可以重试。
- 扫描件稳定返回 `OCR_REQUIRED`，OCR 明确标记为待做。
- 删除后原始文件、元数据、文本块、向量、全文索引和缓存均不可再访问。
- RAG 回答中的每个个人来源都能跳转到本人文档的准确章节或页码。
- 当前 SQLite 知识库与案例库在迁移期间仍可正常检索和引用。
