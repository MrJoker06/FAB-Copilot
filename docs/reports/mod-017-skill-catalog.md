# MOD-017：Skill Catalog、确定性发现与渐进加载

日期：2026-11-03。状态：已验证。基线：`e9c0191`；本轮按用户要求验收后提交并推送，具体提交和同步状态以 Git 记录为准。

## 实现与边界

新增三个标准库模块，保持 `app/skills/` 自身依赖边界；MOD-016 的六个模块及其导出逐字节保留。

| 文件 / API | 责任 |
| --- | --- |
| `catalog.py` / `SkillCatalog.build(roots, inventory)` | 只读显式包根的 Manifest；形成不可变、有序的目录，保留精确版本和不可用原因。 |
| `discovery.py` / `discover(catalog, DiscoveryQuery(...))` | 按已确认的 Workflow ID、制程、Ready/Loop 模式及输入名称存在性进行 AND 筛选，返回候选与拒绝原因。 |
| `loader.py` / `SkillLoader.load(ref)`、`expand(snapshot, paths)` | 必须明确 Skill ID 和版本；先加载 SKILL.md，再按声明路径扩展，返回新快照。 |
| `scripts/demo_skill_loading.py` | 独立三阶段 JSON 演示，复用原有 inventory 读取器，无正文或宿主路径输出。 |

Catalog 不搜索环境目录，不持有全局可变 Registry。相同 ID/版本重复注册拒绝；顺序按 ID 与数值版本稳定排序，1.2.0 排在 1.10.0 前。多个版本都可作为候选，不自动选择 latest。直接构造也要求不可变集合、声明身份和依赖可用性一致。

Catalog 的 available 表示清单/状态/声明依赖符合要求，尚未读取资源正文；不存在或损坏的资源在明确加载时失败。结构损坏或缺失 Manifest 拒绝构建；有效清单中的禁用状态、依赖缺失与版本不兼容保留为可查看的不可用记录。目录相对路径在构建时固定成绝对路径，但不通过 resolve 绕开既有链接检查。

Discovery 不从自然语言猜意图或调用模型。`workflow_id` 是受信调用方对已确认意图的映射；它与 process/mode/input 条件均可显式约束。输入名称存在不代表输入值合法，制程匹配也不是租户 ACL；实际 Tool 参数、权限与预算仍由原执行层校验。它返回所有符合条件的精确版本，不擅自挑选一个执行。

Loader 复用 MOD-016 文件边界，每次加载/扩展前重读 Manifest 并核对目录声明。状态、Workflow、版本或其他声明改变时拒绝 `stale_catalog`，要求重建目录。已加载路径的重复请求不会重新读取正文；同一请求中的重复路径和未声明路径拒绝。新快照继承已读字符串，旧快照不变；跨 Loader 的快照拒绝。

每个资源最多 256 KiB，完整返回快照实际累计最多 1 MiB、64 个资源；超限没有部分新快照返回。没有任意代码执行、动态插件导入、数据库或模型调用。CLI 与结果明确 `execution_authorized: false`，包内容不授予执行权限。

## 查看效果

在 Windows 或 Linux 的仓库根目录使用各自 Python 环境。以下是**验证夹具**，使用 fixture Workflow/证据策略，不是光刻业务执行：

```bash
python scripts/demo_skill_loading.py --package evaluations/skills/catalog_discovery_v1 --inventory evaluations/skills/catalog_discovery_inventory_v1.json --workflow fixture-workflow --process-step LITHO --mode ready --input lot_id
```

输出候选 `catalog-validation@1.0.0`，`stages` 为 `["metadata"]`，`loaded_resources` 为空。
在同一命令末尾追加：

```text
--skill-id catalog-validation --version 1.0.0
```

此时阶段为 metadata / instructions，只加载 `SKILL.md`。再追加：

```text
--resource references/catalog.md
```

阶段增加 explicit_resources，只新增该参考资料。输出包含精确 Skill/Workflow/Policy 版本及路径/字节数。也支持 `python -m scripts.demo_skill_loading`；从无关 cwd 可用绝对脚本路径和绝对参数路径运行。

无匹配时可查看 rejection；精确版本不存在为 `unknown_skill`，已登记但不可用保留 `ineligible_status` / `missing_dependency` / `incompatible_dependency`，可用但不满足筛选为 `selection_no_match`。资源请求未配精确选择为 `invalid_selection`。业务错误为脱敏 stderr JSON、退出码 2，不回退到其他版本或来源。

## 独立验收

方案、起始状态、worker 输出、主审最终结果及可重放演示保存在 `runtime/quality/mod-017-20261103-r1/`。按 AGENTS 流程先制定方案、委派 terra_worker，再由主代理独立审查实际 diff 和测试。首轮复核补齐非法查询类型、直接构造不可变性、CLI 无选择资源请求及真正的渐进 I/O / 隔离负控；未将首轮通过等同最终验收。

| 主审验证 | 实际结果 |
| --- | --- |
| WSL 新旧 Skill 六个 unittest 模块 | 31 项：29 通过，2 个 Windows 专用项跳过，0 失败 |
| 原生 Windows 同组测试 | 31 项：30 通过，1 个 POSIX 专用项跳过，0 失败 |
| 改造前相关 WSL 基线 | 84 项：82 通过，2 个 Windows 项跳过；含 MOD-016 的 16 项，不与最终专项重复累加 |
| 两端主审 CLI/读取观测 | 各 5 组：三阶段 direct 真实输出、module 入口、幂等正文读取与无效请求预检通过 |
| 10 文件隔离真链路 | 两端通过，作为上述专项的一部分；原 MOD-016 七文件隔离仍通过 |
| Ruff / format、新旧边界、仓库静态/文本卫生 | 通过，267 个受管源码文件，0 边界错误 |
| 默认原生 v2 检查、显式 legacy-v1 历史契约 | 通过，默认 SQL 能力未恢复 |

必要测试包括：Manifest-only 读取观测、正文不存在仍可发现、精确重复/数值版本排序、多版本不自动择一、全部筛选条件、无效查询与依赖/状态拒绝、加载前声明和禁用漂移、精确版本无回退、旧快照保持、跨 Loader 拒绝、增量实际 1 MiB 及超限、错误请求不打开新正文，以及 CLI 的无效 UTF-8/重复键/超大 inventory。

10 文件切片精确复制九个 Skill 模块及原样 app 包锚点，在无关 cwd 以 `-I -S` 运行 Catalog → Discovery → instructions → reference，并实测缺依赖、无效 Manifest 和未知版本。持续负控拒绝其他 app 模块、socket/sqlite/subprocess、直接环境读取/写入、os.system，并核对实际加载的全部 app 模块来源恰为明确的十个副本文件。它证明源码切片可独立验证，不等于正式 wheel 或整个应用已独立部署。

主审逐字段比较：只新增三个 skills/platform_core 文件归属和三项 pure module；原允许边、精确债务、数据库/兼容台账不变。现为 **267 文件（239 Python/28 静态）、29 债务、25 DB 候选、13 兼容入口/97 静态消费者**。冻结七单元、旧 37 文件安装清单和 MOD-002/MOD-008 资产未改；无新增依赖或 SHA-256 校验。用户工作簿保留在提交之外。

默认 Runtime、bootstrap、AgentDefinition 与原有 Skill 核心未改。本项运行必要离线检查，不重复完整浏览器、全量覆盖率或 1000×2 性能门；原性能阈值和历史失败记录保留，没有公司接口或真实模型调用。

## 后续与回退

下一项 MOD-018：复用现有 Playbook/Planner，补齐真实 skill_refs/受控装配接缝与光刻 Cpk 的 Ready/Fake Loop 演示。当前 assemble_agent 仍拒绝非空 skill_refs，不能将本项视为实际业务接入已完成。

MOD-019 才负责发布、禁用管理、同版本覆盖拒绝、回退和 Run 内容固定。当前目录是显式构建的声明快照，Loader 返回的已读文本不漂移；尚未加载的资源仍可反映作者修改，不保证文件组原子快照或发布制品不可变性，也不提供进程重启恢复。默认权限/预算权威不变。

回退只需撤回三个模块、演示/夹具/测试、精确边界增量及对应文档，无数据库迁移或数据改写。
