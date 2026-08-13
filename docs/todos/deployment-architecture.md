# 部署与服务拆分 TODO

## 已完成

- [x] `DEPLOY-001` 使用独立 Conda 环境运行项目，保持 base 环境干净。
- [x] `DEPLOY-002` 提供 WSL `run.sh` 和 Windows `run.bat` 启动入口。
- [x] `DEPLOY-003` 使用独立 Git 分支和同名 worktree 开发并行方案。
- [x] `DEPLOY-004` 使用 8888 独立端口运行并行版本。
- [x] `DEPLOY-005` 将用户页面和管理页面分离为独立前端入口。
- [x] `DEPLOY-006` 将运行数据按部门拆分为独立数据库文件。
- [x] `DEPLOY-007` 提供用户、管理、企业模拟数据和个人知识 API 边界。
- [x] `DEPLOY-016` 建立多 worktree 本地治理规则：修复跨 Windows/WSL worktree 链接，统一 LF，并提供带进程锁检测、保留周期、dry-run 和显式 apply 的运行快照清理工具。

## 待做

- [ ] `DEPLOY-008` 将用户前端和管理前端拆成可独立构建、部署和版本化的工程。
- [ ] `DEPLOY-009` 将用户 API、管理 API、Agent Runtime 和 Retrieval Service 拆成独立部署单元。
- [ ] `DEPLOY-010` 依赖 `DATA-017`，实施 Oracle 生产接口切换、配置与回滚流程，并在适用时维护迁移账本；不将 SQLite 笼统直迁为生产库，开发环境仍使用 SQLite。
- [ ] `DEPLOY-011` 提供容器镜像、Compose 或 Kubernetes 本地集成环境。
- [ ] `DEPLOY-012` 建立 CI，包括格式、静态检查、单元测试、集成测试和浏览器测试。
- [ ] `DEPLOY-013` 建立 CD、配置分层、密钥注入、健康检查和滚动回滚。
- [ ] `DEPLOY-014` 建立多实例、高可用、备份恢复和灾难恢复方案。
- [ ] `DEPLOY-015` 为用户端、管理端和数据端配置独立网关路由与网络策略。
