# MOD-016：独立 Skill Manifest 与安全资源读取

日期：2026-11-02。状态：已验证。基线：`6d6e6fa`；本轮代码、优先级文档及本报告未提交或推送。

## 已交付范围

`app/skills/` 六个模块只依赖 Python 标准库和自身。`contracts.py` 保存不可变声明与可信调用方提供的依赖快照，`versions.py` 处理版本，`manifest.py` 校验 JSON/结构/依赖，`resources.py` 处理文件边界，`package.py` 提供显式包 API，`__init__.py` 导出公共入口。逐文件职责见 [结构快照](../current-project-structure.md)。

清单采用 `manifest.json`，Schema 为 1.0.0，包含身份/版本/标题/描述、状态、过程/输入、工具及其版本要求、Ready/Loop 模式、Workflow 和 Evidence Policy 精确版本引用，以及声明资源。使用 JSON 避免增加 YAML 解析依赖；资源仍可为 Markdown/JSON 等 UTF-8 文本。

严格拒绝未知/缺失字段、重复键、非有限数值、非法类型及过深 JSON。版本仅接受无前导零的 x.y.z；工具版本支持精确版本或最多八个逗号 AND 比较式（==、>=、>、<=、<），拒绝通配、caret、tilde、OR 及矛盾边界。Workflow/证据策略引用只匹配可信 inventory 中的精确版本，不导入或执行引用内容。draft/disabled/retired 可解析检查，但默认不具备运行资格。

Manifest 通过不授予执行权限。Skill 不持有 SQL、连接信息或独立 Agent Loop，不导入 Runtime、全局 Registry、配置、数据库或模型客户端。后续仍由受控装配、Planner 与 Dispatcher 执行业务工具；本文不宣称全应用数据库已解耦。

## 文件边界与使用

资源只在调用方显式请求且已声明时读取；返回冻结的文本快照，`.py` 内容同样作为文本处理。路径使用规范相对斜杠形式，拒绝穿越、绝对路径、UNC、盘符、ADS、控制字符、Windows 保留名/非法字符和别名冲突。拒绝符号链接、junction/reparse、硬链接及非普通文件。

POSIX 使用目录 FD、O_NOFOLLOW 和非阻塞叶文件打开；Windows 在链接检查后，用实际打开的文件句柄核对最终路径，包外文件在读取前拒绝。测试覆盖打开前替换路径。显式包根及宿主解释器属于可信输入；这些检查不构成对恶意宿主的沙箱承诺。

上限为 manifest 128 KiB、单个资源 256 KiB、单次读取实际累计 1 MiB、最多 64 个声明资源；句柄最多读 limit+1，错误释放 FD。CLI inventory 同样有 128 KiB 上限。错误返回稳定错误码和脱敏描述，不输出宿主路径、原始资源或系统异常文本。

在仓库根目录使用 Windows 或 Linux Python：

```bash
python scripts/check_skill_package.py --package evaluations/skills/manifest_validation_v1 --inventory evaluations/skills/manifest_validation_inventory_v1.json --resource SKILL.md
python -m scripts.check_skill_package --package evaluations/skills/manifest_validation_v1 --inventory evaluations/skills/manifest_validation_inventory_v1.json
```

直接脚本支持从无关 cwd 使用绝对路径。成功输出清单/依赖摘要、声明/读取路径与字节数，`execution_authorized` 固定为 false；失败为 stderr JSON、退出码 2。样例只作清单验证，其 fixture Workflow/Policy 和 inventory 不代表实际业务能力、服务端授权或光刻试点已经完成。

## 独立验收结果

证据在 `runtime/quality/mod-016-20261102-r1/`，含实现计划、起始状态、保留的优先级文档、worker 输出、主审回归与边界审计。首版复核发现异常类型、Windows 叶链接检查、聚合预算和隔离负控不足，已交回修正；不以首版检查代替最终结果。

| 验证 | 主审实际结果 |
| --- | --- |
| WSL Python 3.11，三个新 unittest 模块 | 运行 16 项：14 通过，2 个 Windows 专用项跳过；0 失败 |
| 原生 Windows Python 3.13，同一组测试 | 运行 16 项：15 通过，1 个 POSIX 专用项跳过；0 失败 |
| 补充严格输入/版本/直接构造检查 | 两端各 22 项通过，脚本 `primary-extra-checks.py` |
| 既有 Agent/legacy 装配、Registry、Runtime Ports、默认原生与边界测试 | 65 项通过（含边界测试故意拒绝非法清单的输出） |
| 既有装配/Ports/Registry 仓库外隔离回归 | 3 项通过 |
| 仓库静态/文本卫生、新旧边界 | 通过；264 源码文件，0 边界错误 |
| 默认 v2 工具迁移和显式 legacy-v1 历史契约 | 通过；默认 SQL 能力未恢复 |

专项实际验证缺失/冲突的三类依赖、非发布状态、防御性 inventory、非法清单与路径、UTF-8、硬链接、WSL FIFO、真实链接/打开前替换、Windows junction 与目录交换、超限文件/清单、FD 异常释放、五个微小资源、精确 1 MiB 及超限，以及 `.py` 不执行。平台不具备符号链接权限时，对应测试内部不强求该权限；原生 junction 用例实际运行且未跳过。

两端的源码隔离测试精确复制六个 Skill 文件和原样的 app 包锚点，从无关 cwd 用 `-I -S` 执行真实解析、依赖校验和资源读取；负控禁止非 Skill 的 app 导入、socket/sqlite/subprocess、环境变量直接读取/写入及 os.system，并检查所有加载的 app 模块来源都在副本。该结果证明本项源码可独立验证，不等于正式 wheel 或全应用独立部署。

主审逐字段比较：仅新增六个 skills/platform_core 归属及 self-only skills 边界；旧所有权、允许边、精确依赖债务、DB 台账、兼容台账均保留。现为 264 文件（236 Python/28 静态），29 条依赖债务、25 个 DB 候选、13 个兼容入口/97 个静态消费者。冻结七单元及旧 37 文件安装清单未扩写。

默认 app 源码、热路径及公开协议未修改。本项运行必要离线测试，不重复浏览器、全量覆盖率或 1000×2 性能门；既有阈值、历史失败及 MOD-002/MOD-008 冻结资产不改。没有真实模型/公司接口调用，没有新增依赖或 SHA-256 校验，用户工作簿保留。

## 后续与回退

下一项 MOD-017：Catalog、确定性发现与渐进 Loader。本项只有显式资源读取，不能标为完整 Skill 加载机制。MOD-018 接实际 skill_refs/受控装配及光刻 Cpk Ready/Loop；MOD-019 接 Run 固定版本与发布/禁用/回退。当前 AgentDefinition/assemble_agent 对非空 skill_refs 的限制仍保留。

本项可通过撤回六个新模块、CLI/夹具/测试、精确边界增量与对应文档回退；无需数据库迁移。版本发布不可变性、跨 Run 生命周期及运行快照留到 MOD-019；包重新打开可看见作者的资源修改，不能将本项冻结的返回字符串等同发布制品固定。
