# Fab Insight Agent 企业化并行方案

状态：并行实验分支，默认端口 `8888`。本方案保持现有 FastAPI、静态 SPA、部门 SQLite 和 Agent 工具接口，先建立企业级边界，再允许逐项替换基础设施。

## 1. 本期目标

- 请求具备明确的 `tenant_id` 和 `user_id`。
- 个人知识与历史会话按租户、用户隔离。
- 在没有测试数据接口时，提供可复现、可分页、无需全量落盘的大规模模拟接口。
- 页面布局、报表、知识库、历史会话和 Fab Copilot 交互保持原样。
- 数据提供器边界保持可替换，接入 MES、EDA、FDC、YMS 或 Lakehouse 时不改变上层 API。
- 用户工作区与企业管理控制台分离，模型发布和运行监控不再暴露在用户导航中。

## 2. 身份边界

演示环境从以下请求头解析身份：

```text
X-Tenant-ID: fab-a
X-User-ID: engineer-001
X-Roles: analyst,process-engineer
```

未提供请求头时使用 `demo-fab/local-user`，保证现有网页无需登录即可运行。设置 `FAB_REQUIRE_IDENTITY=true` 后，缺少租户或用户请求头会返回 `401`。

前端统一请求函数会读取浏览器本地存储中的 `fabInsightTenantId` 与 `fabInsightUserId` 并注入上述请求头；默认不写入这两个键，因此仍使用服务端演示身份。

请求头模式只是 SSO 接入前的适配层，不应作为生产认证方案。生产部署应由 API Gateway 验证 OIDC/JWT，将签名声明映射为服务端可信 Principal，并移除客户端直接声明身份的能力。

当前隔离规则：

- 会话表保存 `tenant_id` 与 `owner_user_id`，所有列表、读取、修改和删除都附带作用域条件。
- 默认租户的个人知识 owner 保持旧格式 `local-user`，兼容已有资料。
- 其他租户使用 `tenant_id:user_id` 作为个人知识 owner，避免不同租户的同名用户共享索引。
- 工厂正式知识与历史案例暂为全局演示数据；生产版应增加站点、组织、保密级别和 ACL 过滤。

管理端使用独立的 `FAB_ADMIN_API_TOKEN` Bearer Token，入口为 `/admin`。管理工作区在认证成功前保持隐藏。该令牌只适合本地和集成测试；生产环境仍应由 OIDC/SSO、管理员角色声明和 API Gateway 策略替代。模型目录与用户模型偏好持久化在 AI 运营库，用户端只能选择已发布模型，模型凭据由服务端统一管理。

## 3. 企业模拟数据接口

```text
GET /api/enterprise/context
GET /api/enterprise/data/manifest
GET /api/enterprise/data/summary
GET /api/enterprise/data/lots
GET /api/enterprise/data/process-runs
GET /api/enterprise/data/sensor-events
```

分页示例：

```bash
curl -H 'X-Tenant-ID: fab-a' -H 'X-User-ID: engineer-001' \
  'http://127.0.0.1:8888/api/enterprise/data/process-runs?process_step=ETCH&limit=100'
```

响应中的 `page.next_cursor` 用于下一页。游标包含租户、实体、筛选指纹和位置，并由 HMAC 签名；修改游标、跨租户使用或变更筛选条件都会被拒绝。接口不支持 offset，避免深分页随数据量增长而退化。

默认虚拟规模：

| 实体 | 虚拟记录数 | 用途 |
|---|---:|---|
| lots | 25,000,000 | MES 批次接口与分页测试 |
| process-runs | 450,000,000 | 工序、设备与量测接口测试 |
| sensor-events | 3,600,000,000 | FDC 时序数据接口测试 |

记录由固定 seed、租户、筛选条件和游标位置确定性生成。相同请求会得到相同业务记录；服务只生成当前页，不会在 SQLite 中物化几十亿行。所有响应和记录都标记 `simulated=true`，Agent 不得将其描述为真实生产数据。

`/api/enterprise/data/summary` 在提供器内部完成聚合，支持日期、制程和设备筛选，返回规模、制造 KPI、设备风险和数据血缘。当前模拟实现使用 `aggregation.semantics=deterministic_projection` 且 `exact=false`，用于验证亿级聚合契约和 Agent 分析流程，不代表扫描真实明细得到的精确生产指标。

Agent 工具 `get_enterprise_data_manifest` 可读取目录和规模，`get_enterprise_fab_summary` 用于全量语义的服务端聚合，`query_enterprise_data` 可抽取最多 50 条当前租户样本。样本工具只用于接口、字段和数据形态分析，不承担全量统计。

## 4. 数据提供器替换契约

`app.enterprise_data.EnterpriseDataProvider` 定义三项能力：

```python
def manifest(principal: Principal) -> dict: ...
def summary(principal: Principal, filters: dict) -> dict: ...
def page(entity: str, principal: Principal, limit: int, cursor: str | None, filters: dict) -> dict: ...
```

接入真实系统时新增实现，例如 `LakehouseFabProvider`，并通过 `FAB_DATA_PROVIDER` 选择。真实实现必须保持：

- 服务端强制租户过滤，不能只依赖调用方传入 SQL 条件。
- 使用 keyset cursor，不暴露数据库 offset。
- 返回稳定主键、UTC 时间、数据分类、血缘和新鲜度。
- 每页最多 500 行；Agent 优先读取聚合结果，不把原始大页直接塞入模型上下文。
- 对 MES/EDA/FDC 分别设置超时、熔断、重试和限流，失败时返回数据源级错误，不静默混用模拟数据。

## 5. 环境数据边界

上层 API 和 Agent 工具接口保持不变。SQLite 是开发和测试环境的可复现 surrogate；Oracle 是生产制造事实来源，但只能经用户已有的接口或适配器访问，不要求也不允许开发环境直连 Oracle。

企业制造数据与应用自有状态必须区分治理：前者后续按 MES、EDA/FDC、YMS 等业务域逐一映射到既有生产接口；后者是否保留在应用存储或迁移到其他受管服务另行确定。不默认所有 SQLite 表都应直接搬入 Oracle。

生产接口切换、回滚及其配置仅能在获授权的生产或集成环境验证；默认开发和测试保持离线，并使用脱敏固定夹具和契约回放。生产配置缺失或接口不可用时必须 fail-closed，不能静默回退到模拟数据。

## 6. 任务跟踪

本文只维护企业数据边界、模拟契约和提供器替换原则，不重复维护演进任务状态。相关任务统一记录在：

- [企业数据 TODO](todos/enterprise-data.md)
- [身份与权限 TODO](todos/identity-security.md)
- [RAG 与知识库 TODO](todos/rag-knowledge.md)
- [部署与服务拆分 TODO](todos/deployment-architecture.md)

## 7. 运行隔离

- 当前分支默认监听 `127.0.0.1:8888`，与 `8765` 路线并行。
- 数据、个人知识和日志默认位于本 worktree 的 `data/` 与 `logs/`，不会复用另一 worktree 的运行文件。
- `FAB_MOCK_CURSOR_SECRET` 在本地可以使用演示值；共享或生产环境必须使用密钥管理系统生成的随机密钥。
