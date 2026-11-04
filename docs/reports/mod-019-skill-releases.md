# MOD-019：Skill 发布、版本固定、禁用和回退

日期：2026-11-04。状态：已验证。基线：`86f6c96`。本项按用户要求独立提交并同步；提交及远程状态以 Git 记录为准。

## 行为与边界

发布入口把显式作者目录中的 Manifest 和全部声明资源读入不可变的内存制品。后续装配与延迟资源加载使用发布内容，不再读取作者目录。已有精确版本不能原地覆盖，禁用后也不能重发同一版本。

`SkillReleaseStore` 是显式创建的进程内管理对象；没有默认全局注册表、环境目录扫描、HTTP 管理接口或持久化发布数据库。进程重启后需由受信装配重新构建，不提供 Checkpoint 或跨进程发布事务。

| 操作 | 语义 |
| --- | --- |
| publish | 校验并冻结完整声明内容，不自动激活；明确发布可将 draft 转为内存中的 published，作者文件不改写。 |
| activate / active_reference | 显式激活精确版本，供调用方构建新 AgentDefinition；不自动选择 latest。 |
| disable | 阻止该版本的新 Run；若正在激活则清除入口，不隐式选择其他版本。 |
| enable | 恢复该版本的准入资格，不自动激活。 |
| rollback | 显式指定已发布且启用的目标版本作为入口；未知或禁用版本拒绝。 |

AgentDefinition 仍使用精确引用。已构建的 Application 不随激活入口漂移；调用方读取显式入口引用后装配新 Application，才能开始使用新版本。发布新版、回退入口或禁用版本均不改写已有 Run 的 Skill 文本和 Skill/Workflow/Policy 引用。

禁用控制新 Run 的准入，不强杀已准入 Run。紧急撤销业务能力仍由每次工具调用的当前 Policy 执行，预算也继续由原 Guard/Dispatcher 执行。固定 Skill 内容不冻结 Python Handler 的历史 patch 语义，不把发布状态当作工具权限。

## 实现方式

`app/skills/releases.py` 管理不可变发布内容和显式生命周期。发布复用原 Manifest/依赖校验、安全文本读取和资源限制；已发布 Loader 复用原有精确选择、渐进扩展、token 和预算逻辑，仅把正文来源替换为内存制品。

模型上下文继续渐进加载：选择后先提供 SKILL.md，仅在明确请求时加入参考资料或场景。发布入口读取完整包用于固定制品内容，模型上下文按每次请求的资源范围形成。

发布前冻结全部资源，单资源仍最多 256 KiB、总资源最多 1 MiB、最多 64 项。失败不留下部分版本。通过有界的再次读取及直接文本比较检测可观察到的作者修改，不增加 SHA-256 或其他内容散列。作者应在发布期间停止修改目录；这些检查不宣称操作系统提供了跨文件原子快照。

`app/bootstrap/skill_assembly.py` 的可选发布配置与文件目录配置互斥。实际装配仍根据真实 ToolBinding 和受控 Workflow 重新构造依赖清单；发布时的 inventory 不能授予运行权限。新 Run 在预算工厂和数据访问前检查版本是否启用。文件路径装配保留 MOD-018 的声明复核行为。

Runtime 继续只接收基础元数据和模型消息，没有新增 Skill/业务依赖。旧 95 文件光刻切片、默认 HTTP、既有文件 Catalog/Loader 和旧工具 patch 兼容保持各自行为。

## 查看效果

在 Windows 或 Linux 使用对应 Python 环境：

```bash
python scripts/demo_skill_releases.py --package evaluations/skills/release_lifecycle_v1/v1 --upgrade-package evaluations/skills/release_lifecycle_v1/v2 --inventory evaluations/skills/catalog_discovery_inventory_v1.json --resource references/release.md
```

这是声明发布的中性夹具。命令按发布/激活 v1、发布/激活 v2、旧加载器扩展资源、拒绝重复发布、禁用 v2、显式回退 v1 输出安全 JSON。它不调用模型或数据库；真实光刻装配、双执行路径及运行期间版本变化由集成验收另外证明。

## 验收与后续

计划、基线、复核问题和主审结果保存在 `runtime/quality/mod-019-20261104-r1/`。按 AGENTS 流程先完成方案，委派 terra_worker 实现，再独立复核代码和执行结果。复核修正了激活/禁用的并发窗口、CLI 显式资源参数重复及测试夹具的 Windows 换行；补齐了旧 Run 真正跨越发布继续执行、回退不改写已有 v2 Run 和实际装配拒绝伪造依赖的证明。

| 主审验证 | 实际结果 |
| --- | --- |
| 起始 WSL 基线 | 61 项，59 通过、2 个 Windows 专用项跳过 |
| WSL 新增专项 | 13/13 通过，包括生命周期、真实装配及 96 文件隔离执行 |
| 原生 Windows 新旧 Skill 专项 | 64 项，63 通过、1 个 POSIX 专用项跳过；含相同 13 项新测试 |
| 两端 CLI | 各 5 组通过：直接入口、模块入口、无关 cwd、越界资源、错误包根；核对精确状态、错误码和安全输出 |
| 完整离线阶段门 | `python scripts/run_quality_gate.py full` 退出码 0，总耗时 486.2 秒 |
| 完整 Python | 1,147 个非系统项和 70 个系统项，共 1,217 项；仅非系统组的 2 个 Windows 专用项跳过，无失败 |
| 覆盖率 / 系统预算 | 88%；系统五模块总耗时 117.7 秒，逐模块与总预算均通过 |
| Node / 浏览器 | 61/61、17/17 通过 |
| 离线评测 | RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7 通过 |

完整门日志里还包含质量门自身测试产生的小型嵌套 unittest 输出；上表按主非系统组及五个系统模块计数，没有重复累加。原生 Windows 本项运行 Skill 专项，MOD-018 报告中的旧 Windows 基线问题保留，未据此宣称整仓 Windows 测试全部通过。

新 96 文件切片沿用原包锚点和 MOD-018 的 95 文件清单，仅增加发布模块。在无关 cwd、`-I -S` 下，先创建旧 Run，再发布 v2、删除作者目录并执行旧 Ready 和新 Loop；实际模型请求、原生工具和证据结果通过。持续守卫及负控拒绝业务网络、DNS、SQLite、外部进程、业务环境变量和默认服务/旧全局注册入口。Windows 仅放行标准库 Proactor 自身的回环唤醒连接，协程内业务连接仍被拦截。所有实际 app 模块均来自显式切片，默认工具注册表为空。

逐字段边界审查及检查器通过：**272 文件（244 Python/28 静态）**，只新增 `app/skills/releases.py` 的归属与 pure module 登记；原允许依赖边、29 条债务、25 个 DB 候选、13 个兼容入口/97 个消费者不变。原九个 Skill 核心模块、默认链、冻结七单元、旧 37 文件安装清单及既有性能资产未修改；六个中性夹具文本文件在 `evaluations/` 中另计。代码和文档使用 UTF-8/LF，无新依赖或 SHA-256 校验。

本轮没有运行真实模型 Live、公司数据库或额外 1000×2 配对性能门；默认路径未变，既有阈值和历史失败保留。发布语义限定于显式管理对象内，既有 Handler patch、跨进程制品交付、模型生命周期和 Checkpoint 由各自工作包验收。

下一项回到 MOD-009：批量工具来源替换与新增能力验收，之后为 MOD-012 模型生命周期和 MOD-015 Runtime 收口。Skill 四项完成不等于这些工作包或公司真实接入已经完成。

回退本项只涉及新发布模块、可选装配配置、演示/测试、边界登记和文档，无数据库迁移或业务数据改写。
