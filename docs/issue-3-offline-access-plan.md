# Issue #3 离线身份与部门授权

基线为 `feat/pe-ee-duty-workspace` 的 `b19b245`。企业身份源与真实组映射属于内网验收。本地沿用已实现的报表、共享资料、Tool 和 Skill 部门规则，使用受信 ASGI 身份夹具、合成部门和合成资料验证实际请求。

1. `AUTH-LOCAL-01` 明确 Web 身份边界。保留演示入口。通过显式配置启用仅接受上游 ASGI 中间件经服务端写入的已验证声明，部门成员关系由声明提供。缺失、无效或客户端伪造的身份进入 401。
2. `AUTH-LOCAL-02` 使用同一身份核对 Tool、Skill、RAG 召回和引用资源。工厂知识后端负责资料权限，前台引用和模型召回使用同一身份。内置演示库只用于通用合成资料。
3. `AUTH-LOCAL-03` 核对会话及快照的访问。跨用户和会话的测试保留，增加权限缩小后的已保存工具结果、旧引用和缓存模型上下文测试。
4. `AUTH-LOCAL-04` 以本地系统链路验收成功、伪造、跨部门、撤权和拒绝原因。记录各改动及证据，按测试策略执行完整门。企业 LDAP、组映射、刷新及报表平台认证在内网验证。

## 接入契约与现有路径

- 部署方在 FastAPI 外层接入经过审核的 ASGI 认证中间件。它在每个已认证请求的 scope 键 `fab.verified_identity` 写入 `IdentityClaims(authentication_scheme="verified", ...)`，包括租户、用户、角色与部门。启用 `FAB_REQUIRE_VERIFIED_IDENTITY=true` 后，缺失受信声明的 API 请求返回 401。调用者请求头提供的身份、角色和部门均不参与该模式授权。默认启动沿用演示身份。
- Tool 实际执行及 Skill 工作流沿用现有目录和 Dispatcher。资料正文和下载继续使用共享资料区的权限。工厂知识接入使用已有 FactorySearchBackend 接口，授权由其检索及目录实现共同提供。认证模式下的自定义后端必须具有可授权的详情接口。检索结果在进入排序或模型前通过同一身份重新检查引用。内置 SQLite 仍使用通用样例。
- 已保存 Tool 结果读取前同时检查主体、会话和当前能力规则。已保存的知识搜索结果也重检原引用，任一引用撤权时整份快照返回不可用。聊天会话、模型历史与幂等重试检查保存回答的 Tool、Skill 和引用，派生回答记录继承的引用标识。认证模式的会话列表仅按标题查询且不发回原回答预览。
- 当前负向验收绑定两个合成部门。不同身份访问同一资料时，HTTP 检索、目录详情、原生检索适配及旧结果分页行为一致。同一用户移出部门后，实际 Tool 调用、已保存快照和缓存回答均被拒绝。
- 部署阶段的认证适配器负责重新获取可信组关系以及会话过期和撤销。该模式的 Web 请求、管理端、个人知识令牌和健康探针接入由 [Issue #6](https://github.com/MrJoker06/FAB-Copilot/issues/6) 核对。部门检索测试使用合成后端。

## 追溯与验证

| 编号 | 位置 | 验证 |
| --- | --- | --- |
| AUTH-LOCAL-01 | `app/core/identity.py`、`identity_contracts.py`、`settings.py` 与 `.env.example` | 拒绝客户端自报角色和部门，传递受信成员关系。 |
| AUTH-LOCAL-02 | `app/knowledge/rag.py`、`search_contracts.py`、`app/tools/knowledge_search/` | 同一引用的 HTTP 搜索、详细读取与原生检索范围一致。 |
| AUTH-LOCAL-03 | `app/bootstrap/result_access_assembly.py`、会话 API、运行时结果读取与 `app/persistence/tool_result_store.py` | 跨用户拒绝、原权限撤回、旧答案与衍生缓存拒绝。 |
| AUTH-LOCAL-04 | `tests/system/test_sessions_streaming.py` 的 `test_verified_department_applies_to_tool_skill_retrieval_and_saved_results` | 通过实际 ASGI 中间件、路由与工具执行链验证正反例。 |

本地验收完成。Windows 定向 34/34。WSL 完整离线门退出 0，发现 1639 项 Python（3 项按条件跳过），系统 106/106、覆盖率 88%、Node 85/85 和 Chromium 47/47。RAG、OCR、Playbook、Ready、Trace 和仓库边界检查通过。首次完整门通过后补测了中文部门、审计回读撤权和直接快照读取，最终完整门重跑通过。测试环境使用合成身份与资料。LDAP 和公司资料由 Issue #6 保留现场验收。
