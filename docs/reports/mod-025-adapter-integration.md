# MOD-025 · 值班助手模块接入与替换

执行基线为 `feat/pe-ee-duty-workspace` 的 `cc52529`，实施日期 2026-11-21。实际入口、接入资料与状态迁移成员见[接入说明附录 B](../adapter-integration-plan.md#附录-b--内网接入与迁移清单)。

| 批次 | 实施结果 |
| --- | --- |
| a · 基线 | 已核对五组消费者。起点较方案编制时的 `0dbbcf6` 多了状态分库、路由、双平台测试修复和值班回答依据四个提交。保留工作区原有 MOD-025 草稿。WSL 基线 82 项通过。 |
| b · 来源 | 复用 `ToolSources`、具名操作和工厂后端注册。自定义知识后端装配只构造已选工厂实现及个人知识入口，移除无消费者的本地工厂库会话构造。Fake 的检索命中、目录和详情核对同一原文。现有参数/范围拒绝、空结果、超时和畸形响应由当前 Adapter、Dispatcher 和 Ready/Loop 回归验证。 |
| c · 状态 | 使用现有状态绑定、SQLite 和结果库工厂。通过真实持久化及新进程验证写入、回读、归属和结果撤销。报表目录文件、共享资料、独立结果库、个人原文和模型配置的配套关系已列入迁移清单。 |
| d · 模型 | `check_model_transport` 负责有界协议探查，纯传输结果标记 `scope=model_transport`。`bootstrap.model_compatibility_assembly.check_model_compatibility` 使用同一受控发送执行 Context 协议，保持检查顺序和管理端入口。HTTP 用例证明通用探针通过后，畸形 Context 仍产生 422 并保存失败报告。传输报告写入被拒绝，已存失败仍可读。 |
| e · 交付 | Windows 与 WSL 分别构建，使用仓库外新 venv 安装制品。双端工具与 Skill 组合通过 44 个工具场景、2 个光刻执行方式和禁用验证。独立 `model_transport` 仅安装本 Profile，MockTransport 核对通用检查、请求约束和自建客户端关闭，过程中禁止导入 Memory、初始化数据库和连接网络。双端 `application_storage` 的交付测试验证仓库外实际存储。 |

## 可复现验证

- WSL 3.11.15 的来源、存储和健康专项共 83 项通过。设备旧报表的首轮定向调用有 9 个缺存储绑定的子用例错误，给测试进程安装已有默认绑定后通过。Windows 3.13.5 的来源、存储、模型与制品专项 60 项通过。首轮制品测试捕获源码并集的旧计数未更新。按单一新增网关文件核对后，将源码并集从 165 改为 166，资源总计从 169 改为 170，定向复跑通过。
- 两平台均以 `scripts/build_module_release.py` 构建，再用 `scripts/verify_module_release.py --wheelhouse` 从仓库外安装运行。模型切片由 5 个文件扩展至 6 个，源码归属共 325 项，随包另有 4 份 Skill 资源。发布锁与已有依赖版本沿用。
- `tests.test_persistence_separation` 构建并安装 `application_storage`，从隔离解释器检查数据库实际导入来源、状态新进程回读和结果库撤销。业务表以及模拟源码在该切片中不可访问。
- `tests.test_model_compatibility` 验证流式、工具参数、最低上下文负载、完整 Context、Thinking 往返及已声明的多模态检查。原内部导入 `app.model_gateway.compatibility.check_model_compatibility` 迁移到 bootstrap，`app.main.check_model_compatibility` 仍可作为集成入口。

## 完整回归

| 环境 | Python 与系统 | 后续检查 |
| --- | --- | --- |
| WSL · Python 3.11.15、Node 22 | `run_quality_gate.py full` 退出 0。发现 1570 项，1491 项非系统含 2 项跳过，79 项系统通过，系统阶段 159.8 秒 | 覆盖率 89%，Node 65/65，Playwright 27/27 |
| Windows · Python 3.13.5 | 原生隔离检出发现 1570 项。1491 项非系统首轮有 1 项制品计数失败，4 项跳过。修正预期后该项通过，接续同一质量门的 79 项系统均通过，系统阶段 91.1 秒。未整体重跑非系统集合 | 覆盖率 89%，Node 65/65，Playwright 27/27。上一轮的会话恢复失败本轮未出现 |

两端的 RAG、OCR、Playbook、Ready 和 Trace 离线评估通过。仓库检查、两套模块边界检查及 diff 检查通过，MOD-003 实扫 325 个文件、0 错误。精确依赖债务由 10 条减为 8 条。

现有验收使用合成数据、隔离状态目录、测试主体和 MockTransport。公司后端选型、权限、真实 Qwen 验收与完整应用组合独立安排。
