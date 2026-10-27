# 可搬迁模块（v1）

本项目当前仍是模块化单体。`portable_units_v1` 的 ZIP 是为“分块带入公司内网、在干净环境中验证”建立的过渡性交付物：它们保留现有的 `app.*` 导入路径和模块身份，以避免破坏既有调用方；它们不是独立 wheel、服务，亦不代表整个项目已经可独立迁移。

## 当前单元与验收

| 单元 | 包含能力 | 独立验收 |
| --- | --- | --- |
| `memory_core` | 上下文记忆契约、规则、协议与 use case | 在临时目录解压后运行历史窗口单元测试；所有 `app.*` 导入必须来自 ZIP。 |
| `decision_core` | 确定性 Router、Planner、Playbook、制造工序词表与证据语义 | 在临时目录解压后执行随包的 12 条 Playbook Golden Set；所有 `app.*` 导入必须来自 ZIP。 |
| `model_transport` | OpenAI 兼容 SSE 解析、工具调用拼装、推理审计脱敏与重试分类 | 在临时目录解压后，使用 `httpx.MockTransport` 完成无网络流式验收；所有 `app.*` 导入必须来自 ZIP。 |
| `enterprise_data_contract` | 制造数据 Provider 与仅含 `tenant_id` 的数据主体契约 | 在临时目录解压后使用假 Provider 与假主体完成无数据库、无网络的离线契约测试；真实 Adapter 不包含在 ZIP 中。 |
| `retrieval_policy` | 检索候选重排、来源选择与证据不足时的确定性降级判定 | 在临时目录解压后对固定候选集验证元数据筛选、排序和 grounding/fallback 语义；不连接数据库或网络。 |
| `factory_search_contract` | 工厂知识/历史案例的检索与目录查询主体、请求、候选/目录响应契约和查询分词 | 在临时目录解压后以假 Provider 验证 tenant、user、roles、检索与目录请求/响应完整性；无数据库、无网络。 |
| `identity_contract` | 不可变身份 Claims 与演示 API Header 解析策略 | 在临时目录解压后验证默认主体、必需 Header、标识格式和长度、角色过滤及 demo/header scheme；无 HTTP、配置、数据库或网络。 |

构建命令（先激活项目 Conda 环境；`model_transport` 的离线验收前提是目标环境已安装 `httpx>=0.28,<1`）：

```bash
conda activate fab-insight-agent
python scripts/build_portable_unit.py --verify
```

默认产物位于被 Git 忽略的 `runtime/portable/`。可用 `--output-dir <目录>` 指向交付目录。每个 ZIP 内的 `portable-unit.json` 固定记录单元名、版本、显式文件列表及（如需要）外部依赖；构建器保持可复现 ZIP，并拒绝缺失文件、不安全路径、数据/日志/密钥类路径、未声明 ZIP 成员，以及未在单元清单中声明的 `app.*` 静态导入。它不使用内容哈希作为验收条件。

这些 ZIP 不能共同安装：当前清单的重复文件为 `app/__init__.py`、`app/manufacturing/__init__.py`、`app/manufacturing/processes.py` 和 `app/knowledge/__init__.py`。它们仅用于各自解压后的隔离验收；组合发布前必须在 `MOD-003` 指定唯一文件所有者或采用版本一致 Bundle。

## 迁移使用方式

1. 在本仓库修改一个单元，并运行它自己的测试和 `--verify`。
2. 将生成 ZIP 复制到内网测试机，解压到空目录；此时不需要原仓库、SQLite 演示数据、日志或 `.env`。
3. 用该单元的验收命令确认行为，再由内网侧把它接到后续 Adapter 或应用层。
4. 主仓库仍通过相同 `app.*` 路径使用代码，直至后续切换为独立包或服务。

## 尚未可单独搬迁的部分

- `model_transport` 仅覆盖流式协议与重试策略；完整模型网关的目录、配置、健康检查、真实端点、密钥与模型发布仍不能随该单元迁移。它要求目标环境自行安装 `httpx>=0.28,<1`，且不应在验收时调用网络。
- `enterprise_data_contract` 仅交付 Provider 契约；`enterprise_data.py` 中现已提供显式注册接缝，内网装配代码可注册实际 Adapter 后用 `FAB_DATA_PROVIDER` 选择它。Oracle 表、DSN、驱动、网络客户端和报表仍不在该单元中，也尚未完成 `DATA-017`、`DATA-018` 或 `DEPLOY-018`。
- `factory_search_contract` 交付候选检索、知识文档/历史案例目录查询的可替换契约与分词规则。应用现在可用 `FAB_FACTORY_SEARCH_BACKEND` 选择显式注册的非 SQLite Adapter；目录调用必须由同一 Adapter 实现，缺少方法、未知名称、构造失败和畸形候选/目录响应都会失败关闭，绝不静默退回 SQLite。目录验证只允许 Active 文档和 Validated 案例，并校验 detail 的请求 ID 与文档—章节来源一致性。默认 `sqlite` 仍是本地演示实现，未完成生产 ACL 声明或强制执行。
- `identity_contract` 仅交付 Header Claims 的解析与校验策略；它不是可信认证、SSO/JWT、权限/ACL 强制执行，也不会迁移个人知识 owner。`PrincipalContextMiddleware` 仍是 HTTP/API 装配层，读取当前配置、保留请求关联 ID 和既有 401/400 JSON 合约；内网部署必须以受信任身份 Adapter 替换该演示 Header 路径。
- `retrieval_policy` 仅交付候选元数据排序和 grounding/fallback 规则。个人知识存储、生产用户 ACL 与身份隔离仍在应用路径中，尚不可随该单元独立迁移；`RAG-019`、`DATA-019` 和 `DEPLOY-018` 均未完成。
- 知识检索仍关联 OCR、个人知识存储与检索后端；需拆出检索与引用契约。
- Agent Runtime 仍是上述能力的装配与工具本地函数注册点；应在 Provider/模型/检索边界稳定后再抽取。
- API、身份、会话持久化、前端和监控仍依赖应用装配；它们是最后的部署单元，而不是当前 ZIP 的一部分。

后续切片、依赖次序和验收门由 [总方案](architecture-modularization-master-plan.md) 与 [模块化工作包追踪](todos/modularization.md) 管理。本轮 P0 的七单元基线、工作树范围和构建记录见 [MOD-001 便携基线报告](reports/mod-001-portable-baseline.md)。每片仍需提供显式文件清单、离线验收、隔离解压验证和可回滚的兼容接入。

## decision_core 1.0.1 增量

`decision_core` 从 1.0.0 升至 1.0.1，仅将 `app/evidence/serialization.py` 纳入显式文件清单，以服务于 Evidence/Answer 域的等价序列化 helper；其余六个单元仍为 1.0.0。`python scripts/build_portable_unit.py --verify --output-dir runtime/portable/mod-002-20261022-r5` 已验证全部七个单元（含 `decision_core-1.0.1.zip`），全部新 ZIP 成员均为普通 100644 模式。该结构验证不替代 MOD-002 尚未通过的墙钟性能门。
