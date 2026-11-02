# Windows / Linux 原生启动验收

日期：2026-11-02。基线：`3c6bfe9`，本次是用户新增的启动兼容维护任务，不计作 MOD-009，
不改变业务工具、Runtime 分层和 DB 接入计划。应用 `app/`、依赖版本约束和冻结制品未改。

## 启动方式

原生 Windows：用 Python 3.11+ 创建 `.venv-win`，安装 `requirements.txt` 后执行
`run.bat`。脚本选择本机解释器，完全不调用 WSL。Linux / WSL：创建 `.venv-linux`
并安装相同依赖后执行 `bash run.sh`，也可沿用已激活环境或现有 fab-insight-agent Conda。
详细命令及配置见 [README](../../README.md#快速启动)。

两个入口统一调用 `run.py`，支持 `--check`、`--port`、`--host`、`--source-mode`
和 `--seed-days`，保留 `FAB_PYTHON`、实例目录/ID、PORT 与 env 文件配置。
`--check` 仅检查解释器、依赖存在性与内存 SQLite FTS5 trigram，不创建运行实例。
解释器不满足最低版本时返回明确提示和退出码 2。

| 文件 | 职责 |
| --- | --- |
| `run.py` | 解释器环境检查、实例参数、固定/工作树源码、隔离路径、先 seed 后服务、退出码和子进程清理。 |
| `run.bat` / `run.sh` | 原生平台的解释器选择及参数/退出码透传；支持项目虚拟环境。 |
| `scripts/instance_lock.py` | 按平台选择 POSIX flock 或 Windows 字节锁；Windows 锁位于 `.locks`，以便持锁删除自己的已停止实例。 |
| `scripts/manage_runtime.py` | 保留 list/prune 契约及显式 apply、路径边界、保留期、活动锁与旧计划复核；异平台实例保留，内部 `.locks` 不算实例。 |
| 三个专项测试模块 | 启动、真实子进程锁竞争、运行目录管理；另复跑数据库管理与浏览器测试服务环境回归。 |
| `.gitignore` / README / PROJECT_INDEX | 忽略两端独立环境，说明统一启动方式及运行边界。 |

## 来源、数据和生命周期

默认 snapshot 在本机 Git 能识别项目根目录时，使用当前提交的 Git archive；Python 负责
安全解包，不依赖系统 tar。拒绝路径穿越、链接和特殊成员，已有固定副本的完成标记/提交
须匹配。Git 根目录必须恰好等于项目目录，不能把父仓库当成导出项目的源码来源。

没有 Git 或 Windows 无法解析 WSL worktree 元数据时，复制受控的源码白名单并明确标为
unversioned。配置、数据、日志、运行目录、虚拟环境与用户工作簿不进入该副本。
未版本化默认实例 ID 使用 nonce；显式复用实例仍保留原副本。需要读取未提交修改时，
用户可选 worktree 模式；该模式明确使用当前源码，不声称固定源文件。

实例锁在任何 snapshot、数据目录或 manifest 变更之前取得，直至 seed/服务子进程退出
后才释放。重复启动返回 3，不修改运行中实例的 manifest。五个部门库、主库兼容路径、
个人文件及日志均指向当前实例；env 文件中的业务路径不能把演示 seed 重定向到外部库。
Windows 和 POSIX 默认实例名不同，显式复用另一平台的实例会被拒绝；不宣称两类锁能跨
Windows / WSL 互相同步。没有平台字段的旧实例按原 POSIX 实例处理，在 Windows 下保留。

普通文件系统使用同父目录 rename 发布完整副本。实际 WSL DrvFS 验收发现目录 rename
持续返回 PermissionError（10 次诊断均失败）；现在仅在目标不存在且 rename 被拒绝时，
在实例锁内复制已完成的 staging 内容，最后写完成标记。复制失败没有有效标记，服务不会
启动。清理仅作用于本次成功创建的目标；另有竞态 sentinel 回归证明不会删除他人刚创建
的目标目录。既有 source 若链接或解析到实例外，也明确拒绝。

Ctrl+C / SIGTERM（Windows 包括 SIGBREAK）会回收子进程后释放锁，seed 和服务失败的
退出码透传。源码、静态文件固定与运行数据目录隔离继续成立；没有新增 SHA-256 检查。

## 实际验证

| 验证环境 | 结果 |
| --- | --- |
| 原生 Windows，Python 3.13.5 / SQLite 3.49.1 | 从未修改的 requirements.txt 安装独立 `.venv-win`；应用及 OCR 模块导入通过。最终五模块 48 项回归全部通过。 |
| WSL Ubuntu-24.04，Python 3.11.15 | 最终相同五模块 48 项通过；默认未激活 Conda 时 `bash run.sh --check` 正确找到原环境。 |
| 原生 Windows 的 run.py 和 run.bat | 真实服务均通过页面/管理页面、健康、dashboard、CMP capability 五类请求；每个实例首次启动/重启都通过。最终 batch 版本又独立复跑两次启动。 |
| WSL 的 run.sh | worktree 和 Git snapshot 两模式均通过同一真实服务请求、停止及重启；snapshot 在实际 `/mnt/d` 挂载盘上通过修复后的发布路径。 |
| 锁和实例复用 | 所有真实服务检查五个部门库都在各自实例；重复启动退出 3，manifest 不变；Windows CtrlBreak / Linux SIGTERM 后锁释放、端口停止，没有存活 HTTP 子进程；重启数据行数不变。 |
| 路径 | 单元与真实实例覆盖中文/空格路径；另以含中文/空格目录调用原生 run.bat --check 通过。 |
| 低版本诊断 | 现有原生 Windows Python 3.10 执行 --check 返回 2、明确 Python 3.11+ 提示，无导入 traceback。 |
| 静态与边界 | 六个改动 Python 源码/测试的 Ruff、Bash 语法、Git diff 和仓库检查通过；app 仍为 258 文件，模块边界 0 错误，默认工具迁移检查通过。 |

两端的 48 是同一套测试分别执行，不累计为 96 个不同测试。真实服务采用独立的 14 天
合成数据，各实例 178 个批次；没有调用真实模型、公司接口或共享演示数据库。极短种子
窗口可能触发应用已有的完整数据补齐，所以没有用 1～2 天启动冒充完整服务验收。
Windows 真实服务在隐藏测试控制台内运行，验证完成均停止；没有留下测试服务。
普通独立 Linux 主机未另行部署，POSIX 验证环境是 WSL Ubuntu，而启动代码不依赖 WSL。

本次没有重复 MOD-008 正式性能/全量浏览器或阶段覆盖率；应用业务源码未改，运行必要
启动与数据库相关集合及实际 HTTP 验证。MOD-008 的已验收状态和历史失败证据不变。
初版 native 测试的 4 失败/1 错误、DrvFS 首次启动失败及诊断原样保留，未用单元夹具通过
替代真实操作系统启动。

证据目录：`runtime/quality/cross-platform-startup-20261102-r1/`。包含实现计划、开工副本、
各轮 worker/review、Windows 安装与导入记录、两端最终测试日志、`smoke_server.py`、
各实例 server 日志与 `*-smoke.json`。本次未提交或推送；`.venv-win` 和全部运行产物被忽略。

回退只撤销本次启动器、平台锁、管理器兼容、测试与文档改动；不删除现有数据库或实例，
不回退已同步的 MOD-008，也不改写 WSL worktree 的 Git 元数据。
