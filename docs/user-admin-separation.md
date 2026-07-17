# 用户端与管理端分离设计

## 1. 产品入口

| 入口 | 访问者 | 能力 |
|---|---|---|
| `/` | FAB 分析用户 | 制造报表、Fab Copilot、个人知识上传、知识与案例预览、历史会话、已发布模型选择 |
| `/admin` | 平台管理员 | 用户运行状态、最近 Agent Runs、Token 与失败统计、模型发布、停用和重新发布 |

两个入口使用独立的 HTML、JavaScript 和 CSS。用户端不再显示 Agent 监控视图，管理端不加载制造分析工作区或个人知识内容。

## 2. 管理认证

本地管理 API 要求：

```text
Authorization: Bearer <FAB_ADMIN_API_TOKEN>
```

受保护接口：

```text
GET   /api/admin/overview
GET   /api/admin/models
POST  /api/admin/models
PATCH /api/admin/models/{model_id}
GET   /api/monitor/summary
GET   /api/monitor/events
```

管理端令牌只存放在浏览器 `sessionStorage`，关闭标签页会话后失效。管理工作区默认隐藏，只有令牌校验成功后才显示；登出、令牌失效或认证失败会立即重新隐藏。当前 Bearer Token 是本地过渡方案，不能替代生产 SSO；生产环境必须由可信网关验证 JWT，并从签名声明映射管理员角色。

## 3. 模型生命周期

`model_catalog` 保存：

- 稳定的 `model_id` 和显示名称。
- Provider、Provider Model 与 API Base URL。
- Streaming、Tool calls 等能力声明。
- `published` 或 `retired` 状态、发布人与时间。

管理员发布后，模型立即进入用户端选择列表。停用后新请求不能再选择该模型；已有用户偏好会自动回退到其他已发布模型。系统阻止停用最后一个已发布模型。

`user_model_preferences` 使用 `(tenant_id, user_id)` 作为主键。用户切换模型不会影响其他用户。用户端只能选择管理端已发布的 `model_id`，不能提交模型名称、API 地址或 API Key；模型凭据由服务端环境或模型网关统一管理。

## 4. 用户运行状态

同步和流式 Agent 请求都会维护当前用户的运行状态：

- `running`：至少一个 Agent 任务正在执行。
- `idle`：最近 15 分钟内完成过任务。
- `error`：最近任务异常结束。
- `offline`：没有活跃任务且超过 15 分钟没有活动。

管理端把内存实时状态与 AI 运营库中的会话、Agent Runs、耗时和 Token 统计合并。进程重启后实时状态会清空，但已完成运行仍可从数据库恢复；生产多实例部署时应把实时状态迁移到 Redis 或事件流。

## 5. 生产演进约束

- 使用 OIDC/SSO 和 RBAC 代替请求头身份与静态管理令牌。
- API Key 进入企业 Secret Manager，由后台模型目录保存受管凭据引用，用户端始终不接触密钥。
- 模型发布增加审批、连通性测试、工具调用兼容测试、限额和灰度范围。
- 运行状态通过 Redis、Kafka 或 OpenTelemetry 汇聚，避免单进程内存视图。
- 管理 API 与用户 API 使用不同网关路由、审计策略和网络访问控制。
