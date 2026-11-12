# 部署与服务拆分 TODO

本文件仅维护未完成任务和未激活的可选候选。已完成 11 项，定义与验收见[归档](archive/deployment-architecture.md)；[完成索引](completed.md)。

## 企业级暂缓

- [ ] `DEPLOY-008` 将用户前端和管理前端拆成可独立构建、部署和版本化的工程。

- [ ] `DEPLOY-009` 将用户 API、管理 API、Agent Runtime 和 Retrieval Service 拆成独立部署单元。

- [ ] `DEPLOY-010` 依赖 `DATA-017`，实施 Oracle 生产接口切换、配置与回滚流程，并在适用时维护迁移账本；不将 SQLite 笼统直迁为生产库，开发环境仍使用 SQLite。

- [ ] `DEPLOY-011` 提供容器镜像、Compose 或 Kubernetes 本地集成环境。

- [ ] `DEPLOY-013` 建立 CD、配置分层、密钥注入、健康检查和滚动回滚。

- [ ] `DEPLOY-014` 建立多实例、高可用、备份恢复和灾难恢复方案。

- [ ] `DEPLOY-015` 为用户端、管理端和数据端配置独立网关路由与网络策略。

- [ ] `DEPLOY-018` 依赖 `DEPLOY-017`，将首批源码单元升级为独立版本化包，并逐步抽取模型协议、制造数据 Provider、知识检索 Adapter、Agent Runtime 和 API 部署单元。
