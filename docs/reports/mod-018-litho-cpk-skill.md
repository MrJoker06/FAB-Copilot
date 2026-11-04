# MOD-018：光刻 Cpk Skill 与显式装配

日期：2026-11-04。状态：已验证。基线：`bff4ecc`。本项按用户要求独立提交并同步；具体提交和远程状态以 Git 记录为准。

## 实现与调用链

`assemble_agent` 现在通过显式 `skill_configuration` 和 `skill_request` 支持单个精确版本的非空 `AgentDefinition.skill_refs`。未提供配置时仍拒绝非空引用；无 Skill 的既有调用保持原行为。默认 HTTP/Coordinator 没有自动启用此试点。

```text
AgentDefinition.skill_refs + 显式包根 / 受控 Workflow / 已确认请求
  → Skill Catalog → 精确选择 → Loader
  → LithoCpkWorkflow → 既有 named Playbook / Planner
  → AgentApplication.new_run → Ready 或 Fake Loop
  → 同一 Dispatcher / Policy / Guard → 原生 ToolBinding
  → 精确 Fake Data Adapter → ToolResult / SourceScope
  → 既有结果转换 → 显式版本的证据策略
```

| 文件 | 职责 |
| --- | --- |
| `app/bootstrap/skill_assembly.py` | 根据实际 ToolBinding 和受控 Workflow 构造依赖清单，发现并加载精确 Skill，核对计划工具及服务端能力；新 Run 前重新校验声明。 |
| `app/bootstrap/litho_cpk_workflow.py` | 固定 Workflow/Policy 身份，确认单一 LITHO 范围，调用现有命名 Playbook 和 Planner。 |
| `app/bootstrap/litho_cpk_demo.py` | 真实 opt-in 装配、Ready/Fake Loop 与原生 Fake 来源的离线演示。 |
| `app/evidence/skill_policy.py` | 复用完整证据校验流程，仅扩展知识检索焦点的匹配方式。 |
| `app/skills/lithography/cpk_diagnostic/` | Manifest、SKILL.md、参考资料及验收场景四个文本资产，不含可执行插件。 |

Skill 引用为 `litho-cpk-diagnostic@1.0.0`，Workflow 为 `litho-cpk-workflow@2.0.0`，复用 `PB-CAPABILITY-001@2.0.0` 和 schema 1.2 的原计划。四个步骤保持原依赖：Cpk、最近异常、可选传感器摘要、知识检索；必需证据仍为 CAP-01/02/04。包里不另写一套 Cpk 阈值、SQL 或执行步骤。

工具权限来自 Agent 声明、服务端能力和每次调用的主体 Policy；加载说明不授予权限。Runtime 只接收模型消息和不可变基础元数据，不导入 Skill、具体 Workflow 或业务模块。预算仍由调用方工厂提供，演示为每次 Run 新建 Guard，并将同一实例交给 Dispatcher 与 Ready/Loop。

## 证据策略的兼容边界

默认 `validate_evidence` 保持 **1.2.0** 行为。新的显式策略 `capability-evidence@1.3.0` 用于本试点。

原结果转换以真实 `ToolSource.scope` 替换来源范围；知识搜索的 process/equipment 是检索焦点，不能伪装成来源 ACL。旧匹配器因此无法把本次知识结果匹配到 CAP-04。新策略核对实际 observation 的 query/source_types/limit，以及每条返回记录的原生 `retrieval.filters`。缺失、冲突或不匹配时拒绝；其他工具沿用原匹配器。覆盖率、风险与结论规则仍调用原校验流水线，没有复制或降低标准，也没有改写来源范围。

## 查看效果

在仓库根目录使用 Windows 或 Linux 各自的 Python 环境：

```bash
python -m app.bootstrap.litho_cpk_demo --mode ready
python -m app.bootstrap.litho_cpk_demo --mode loop --resource references/cpk_context.md
python -m app.bootstrap.litho_cpk_demo --mode ready --role viewer
```

成功路径运行四个原生工具；Ready 不调用模型，Fake Loop 调用固定响应模型两次，第二次保留 user、assistant/tool_calls 和实际 tool 消息历史。显式请求的参考资料确实进入模型上下文。输出包含安全的版本/资源路径、类型、字节数、计划依赖、结果来源范围、Guard 预算及调用计数和证据结果，不打印资源正文或宿主包根。viewer 被真实 Policy 拒绝，退出码 2；操作输入错误也返回脱敏错误，禁止静默改用其他来源或版本。所有业务事实均为 Fake 夹具，不证明公司数据库、生产 ACL 或目标量化小模型的效果。

## 验收记录

实现计划、基线、失败轮次及最终主审日志保存在 `runtime/quality/mod-018-20261103-r1/`。按 AGENTS 流程先规划、委派 terra_worker 实现，再由主代理独立审查代码与实际结果。

| 主审验证 | 结果 |
| --- | --- |
| WSL 新试点与既有装配/Ports/Registry/默认原生/Ready/Loop/Planner/证据/Skill、旧隔离回归 | 139 项，137 通过、2 个 Windows 专用项跳过；其中新增 20 项 |
| WSL Dispatcher、边界与旧 37 文件真实隔离安装 | 另 27 项全部通过 |
| 原生 Windows 新试点与六个既有 Skill 模块 | 51 项，50 通过、1 个 POSIX 专用项跳过；其中新增 20 项 |
| 两端主审 CLI | 各 5 组：Ready、Loop/显式参考资料、viewer、错误包根、越界资源，退出码/来源调用数/证据结果符合预期 |
| 95 文件与 4 资产的完整隔离切片 | 两端通过，计入上述专项；原包锚点不改写，所有实际 app 模块来源均在显式清单内 |
| 默认证据策略与 Git 基线独立对照 | 5 组结果一致，默认仍为 1.2.0 |
| 仓库检查、两套边界、默认 v2 迁移检查、显式 legacy-v1 历史契约 | 通过 |

原生 Windows 扩大检查的 44 项旧测试有 4 个旧隔离项失败、1 个旧 SQLite 演示清理错误和 1 个平台跳过。将三个受修改模块替换为 Git 基线源码，并在旧隔离切片复制时使用相同基线，复现了相同失败集合：旧子进程/Windows 运行约束与错误输出编码问题，以及 SQLite 句柄清理的 WinError 32。原始输出和对照记录保留；本项没有修改旧测试，也不把这组结果记为通过。

新增测试重点为实际 Manifest 依赖与绑定版本、未知 Workflow/Policy/Skill 引用、服务端缺能力、资源越界、缺少时间输入、新 Run 前禁用声明复核、每次 Run 独立 Registry/预算、真实模型消息历史和 viewer 零读取。证据反例覆盖 query/source_types/limit、缺失或冲突焦点；单独制造规格冲突，确认原冲突检测和 hypothesis_only 限制仍生效。

完整切片以无关 cwd、`-I -S` 和标准库执行真实装配及双路径，持续拒绝配置/默认服务/旧全局注册入口、业务环境读取、SQLite、DNS、进程启动和业务网络调用，实际负控验证拦截有效。Windows 只放行标准库 `_make_self_pipe` 内部的 Proactor 回环唤醒连接，并额外验证协程中的业务连接仍被拒绝。原 runtime 包锚点带入的 Coordinator/stages 有限源码依赖如实保留，因此 95 文件隔离通过不代表旧协调器已完全退出，也不是正式可组合 wheel。

边界逐字段审查确认，仅增加四个文件归属和装配层到 skills 的允许依赖。现为 **271 文件（243 Python/28 静态）**；四个 Skill 文本资产另计，29 条依赖债务、25 个 DB 候选、13 个兼容入口/97 个消费者不变。MOD-016/017 九个核心源码文件逐字节保留，冻结七单元、旧 37 文件安装清单及默认原生工具链未改。无新依赖或 SHA-256 校验。

这是显式 opt-in 扩展，运行必要的离线专项与兼容检查，不重复完整浏览器、覆盖率或 1000×2 性能门。既有阈值和历史失败保留，没有公司接口或真实模型调用。

## 后续与回退

下一项 MOD-019 才实现发布、禁用管理、同版本覆盖拒绝、回退和完整 Run 内容固定。本项的新 Run 声明复核与已加载字符串快照不等于完整发布生命周期，也不承诺进程重启恢复。MOD-009/012/015 及整体迁移验收仍待后续。

回退涉及本项 opt-in 接缝、新增模块、资产、测试、精确边界登记和文档；无数据库迁移或业务数据改写。用户工作簿不属于本项提交。
