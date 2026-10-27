# 部署与服务拆分 TODO

## 已完成

- [x] `DEPLOY-001` 使用独立 Conda 环境运行项目，保持 base 环境干净。
- [x] `DEPLOY-002` 提供 WSL `run.sh` 和 Windows `run.bat` 启动入口。
- [x] `DEPLOY-003` 使用独立 Git 分支和同名 worktree 开发并行方案。
- [x] `DEPLOY-004` 使用 8888 独立端口运行并行版本。
- [x] `DEPLOY-005` 将用户页面和管理页面分离为独立前端入口。
- [x] `DEPLOY-006` 将运行数据按部门拆分为独立数据库文件。
- [x] `DEPLOY-007` 提供用户、管理、企业模拟数据和个人知识 API 边界。
- [x] `DEPLOY-012` 建立远程 CI 质量门：GitHub Actions 在固定 Ubuntu 24.04、Python 3.11、Node 22 和 Noto 字体环境执行仓库治理、单元/系统、评测与 Playwright 测试；`experiment/parallel-platform` 要求由 GitHub Actions App 产生的 `Full quality gate` 检查，并且要求分支与基线严格同步。
- [x] `DEPLOY-016` 建立多 worktree 本地治理规则：修复跨 Windows/WSL worktree 链接，统一 LF，并提供带进程锁检测、保留周期、dry-run 和显式 apply 的运行快照清理工具。
- [x] `DEPLOY-017` 建立首批可搬迁源码单元：`memory_core`、`decision_core`、仅覆盖 SSE 协议的 `model_transport`、仅含数据 Provider/租户主体契约的 `enterprise_data_contract`、候选排序和证据降级规则的 `retrieval_policy`、工厂知识/案例检索与目录契约的 `factory_search_contract`，以及不可变 Claims 与演示 Header 解析策略的 `identity_contract`，均通过显式清单打包，能够在仓库外的临时目录中完成隔离导入与离线验收；交付物仍保留 `app.*` 兼容导入，不是独立服务。ZIP 按显式清单验收，不使用 SHA-256 内容校验。应用侧已提供显式数据 Provider、检索/目录 Backend 与身份 Claims 解析接缝，但真实数据 Adapter、可信认证和生产 ACL 未纳入交付物；个人知识库仍在应用内。`DATA-019`、`RAG-019`、`DEPLOY-018` 未完成。

## 当前队列

当前无非企业级部署任务。

## 企业级暂缓

- [ ] `DEPLOY-008` 将用户前端和管理前端拆成可独立构建、部署和版本化的工程。
- [ ] `DEPLOY-009` 将用户 API、管理 API、Agent Runtime 和 Retrieval Service 拆成独立部署单元。
- [ ] `DEPLOY-010` 依赖 `DATA-017`，实施 Oracle 生产接口切换、配置与回滚流程，并在适用时维护迁移账本；不将 SQLite 笼统直迁为生产库，开发环境仍使用 SQLite。
- [ ] `DEPLOY-011` 提供容器镜像、Compose 或 Kubernetes 本地集成环境。
- [ ] `DEPLOY-013` 建立 CD、配置分层、密钥注入、健康检查和滚动回滚。
- [ ] `DEPLOY-014` 建立多实例、高可用、备份恢复和灾难恢复方案。
- [ ] `DEPLOY-015` 为用户端、管理端和数据端配置独立网关路由与网络策略。
- [ ] `DEPLOY-018` 依赖 `DEPLOY-017`，将首批源码单元升级为独立版本化包，并逐步抽取模型协议、制造数据 Provider、知识检索 Adapter、Agent Runtime 和 API 部署单元。
