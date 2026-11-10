# MOD-024：版本一致的模块制品与离线安装

日期：2026-11-10。应用源码基线：`c193138`（已合入 local-Qwen 与 DEPLOY-019）。状态：已验证；当前仅交付下述 Profile，不代表 P5 整体验收完成。

## 交付与范围

采用总方案允许的版本一致源码 Bundle，保留 `app.*` 导入路径。五个 ZIP 是同一 cohort/version 的组成部分，由 MOD-003 主所有者清单确定归属；每个文件只由一个制品拥有。原七个 portable ZIP 与 Dispatcher 冻结制品保留原格式，仍可独立验收。

| 制品 | 源码/资源成员 |
| --- | ---: |
| platform_core | 156 |
| application_bundle | 78 |
| enterprise_adapters | 24 |
| simulation_fixtures | 1 |
| manufacturing_capability | 31（27 个受管文件 + 4 个 Skill 资源） |
| 合计 | 290；另有每 ZIP 一个元数据文件，物理 ZIP 条目共 295 |

清单、构建器和安装器分别为 `evaluations/mod_024_release_v1.json`、`scripts/module_release.py` / `scripts/build_module_release.py`、`scripts/install_module_release.py`。构建时记录源码提交（Git 可用时）、显式 build_id、版本、唯一归属和成员。原生 Windows 无法解析当前 WSL worktree 的 Git 元数据时，source_commit 明确为 null/status=unavailable；build_id 不能冒充已验证的 Git 提交。

| Profile | 实际安装范围 | 验收 |
| --- | --- | --- |
| tool_sources | 104 个真实 Python 文件，精确复用 MOD-009 当前清单 | 21 项工具及可选设备健康汇总，各走 Ready/Loop，共 44 路 |
| skill_release | 100 个 Python 文件 + 4 个原路径文本资源 | 光刻 Cpk Ready/Loop；实际 SkillReleaseStore 发布、资源读取与禁用后拒绝新 Run |
| model_transport | 5 个 app Python 文件 | HttpModelGateway + httpx.MockTransport，实际 SSE 内容/usage/URL 校验，无真实模型请求 |

运行范围补充：仅选 tool_sources 时不启用 Skill；非空 skill_refs 必须显式同时选择 skill_release。静态审计中其余未随 Profile 安装的 app 导入均位于 TYPE_CHECKING，不是实际运行依赖；本项不提供这些源码的完整类型检查环境。

工具与 Skill 组合共 142 个文件（138 Python + 4 资源）；三个 Profile 组合共 146 个（142 Python + 4 资源）。其余 144 个受管 app 文件已交付，但尚未纳入运行 Profile，列在 deferred_app_files 中。不能据此声称完整 HTTP、OCR、真实公司 Adapter 或整体应用已独立可运行。

## 安装边界与依赖

安装器随交付目录复制，是仅依赖标准库的独立脚本。目标为新建且不继承系统包的 venv；校验实际目标解释器的 CPython、完整版本、OS、machine、ABI 与 purelib。拒绝系统 Python、已有 app、未声明的外部安装、缺失锁项、冲突 pin 与不匹配的目标环境。只接受 pip/setuptools 的标准引导文件；不执行覆盖式升级。

安装前验证整个 cohort：成员与所有权一致、制品 ID 唯一、版本一致、规范化 app 路径、包锚点、UTF-8/LF、Python 可编译以及普通 100644 文件模式。拒绝路径穿越、Windows 反斜杠路径、重复/大小写冲突、符号链接和不安全元数据。各 Profile 共用文件仅写一次；全部验证后先写临时区，检查目标冲突再移入，移动失败时回退本次新写入内容。安装器 `--verify` 仅预检、不安装。

锁定并实际验证的目标：

| 环境 | 解释器/架构 | ABI |
| --- | --- | --- |
| Ubuntu-24.04 / WSL | CPython 3.11.15 / x86_64 | cpython-311-x86_64-linux-gnu |
| 原生 Windows | CPython 3.13.5 / AMD64 | cp313-win_amd64 |

标准库 Profile 不安装 pip 依赖。model_transport 的直接依赖为 `httpx==0.28.1`；传递依赖精确锁为 `httpcore==1.0.9`、`h11==0.16.0`、`anyio==4.16.0`、`certifi==2026.10.23`、`idna==3.20`、`typing_extensions==4.16.0`。这是本轮两个目标的锁，不能直接外推到其他 Python/OS。

Wheel 由操作者在联网侧显式准备；构建与安装不自动下载。安装使用 pip isolated/no-index/only-binary/no-cache，先 dry-run 并检查实际解析结果恰好等于锁定 BOM、来源为本地 file，再用 no-deps 安装全部精确 pin。不借用宿主依赖，也不允许解析器悄悄补入未锁定的传递依赖。遵循用户要求，不引入自建 SHA/内容哈希验收门。

## 可复现命令

构建并静态验证发布组：

```bash
python scripts/build_module_release.py --output runtime/module-release --build-id mod024-1.0.0
```

复制该目录全部内容到内网。先创建新 venv，再查询目标 Python 的 purelib，执行：

```bash
<宿主Python> -I <交付目录>/install_module_release.py --delivery <交付目录> --target-python <目标Python> --target-site-packages <目标purelib> --profiles tool_sources skill_release
```

三个 Profile 一次组合时，在 profiles 后增加 model_transport，并提供 `--wheelhouse <本地Wheel目录>`；目标 venv 需要 pip。Windows 的解释器位于 Scripts/python.exe，Linux/WSL 位于 bin/python。构建入口的 `--verify` 检查已有交付目录，不能代替实际运行验收。

实际验收入口会复制交付物到独立目录，新建无宿主包的 venv，从无关 cwd 使用 `-I -X utf8` 运行真实源码：

```bash
python scripts/verify_module_release.py --delivery runtime/module-release --work-dir <全新验收目录> --report <报告.json> --wheelhouse <本地Wheel目录>
```

不传 wheelhouse 时，模型传输明确记 NOTRUN；本轮正式报告均显式传入，两个环境均无 NOTRUN。第二个 venv 一次安装全部三个 Profile 后执行模型传输，以验证组合安装。验收目录必须全新，脚本不覆盖旧目录。构建器同时复制 install_module_release.py 和 verify_module_release.py。交付目录在仓库外可直接使用 `python -I <交付目录>/verify_module_release.py` 执行上述参数，不依赖原仓库。

## 主审验证与限制

本轮只改交付工具、清单、测试和文档。逐字节与初始副本比对的 296 个既有文件均未改变，包含应用源码/资源、旧制品及冻结边界相关文件。受管源码仍为 286（258 Python + 28 静态），依赖债务 11、兼容入口 7、消费记录 94、DB 候选 26。

| 检查 | 实际结果 |
| --- | --- |
| 新增结构/安装测试 | WSL 与原生 Windows 各 11 项通过（62.478 / 26.066 秒），包含确定性 ZIP 字节对比、安全路径/元数据/符号链接、锁缺失、系统解释器、未锁定传递依赖与已有安装拒绝；模型依赖 Wheelhouse 本轮已提供，无跳过 |
| 独立 CLI 机器报告 | 两端各 44 工具路 + Cpk 双路径 + Skill 发布/禁用；三个 Profile 组合及离线模型传输通过 |
| 副作用与隔离 | tools/Skill 禁止默认装配、全局注册、配置、持久化与模型网关导入；模型验收仅放行传输网关。两者持续阻断业务环境、网络/DNS、SQLite、子进程与 shell；先执行反例证明守卫有效，再要求实际业务路径零违规。Windows 仅放行 asyncio 标准库自身 loopback 唤醒 |
| 导入来源 | -I、新 venv、无关 cwd、空业务环境；加载的 app 模块必须来自安装后 purelib，tools/Skill 还检查其属于已声明文件 |
| 旧制品基线（WSL） | 21 项通过，包括七个旧单元、Dispatcher 安装、Skill/工具来源与模型传输；19.524 秒 |
| 同集旧基线（Windows） | 21 项，保留既有 2 failures / 2 errors；旧 Dispatcher 测试的空环境子进程编码与 UTF-8 父进程解码冲突。没有把这组结果标成通过，也未为本项修改旧测试 |
| 仓库与边界 | check_repository、两个边界检查、Ruff 和 git diff 检查通过；286 文件，零边界错误 |

`tests/test_module_release_install.py` 的模型用例需要本地离线 Wheelhouse；没有时明确跳过，不能视为模型传输通过。正式交付验收应以上述显式 wheelhouse 的 CLI 报告为准。

完整浏览器、覆盖率、Live 和性能阶段门本轮未重跑；生产应用及默认调用热路径没有修改，本轮不是整个 P5 收尾。也未连接真实公司数据库/报表接口或真实模型，没有验证量化模型业务效果。

计划、原始源码副本、测试日志与 JSON 报告保存在 Git 忽略的 `runtime/quality/mod-024-20261110-r1/`：`primary-final-{wsl,windows}.log`、`primary-accept-{wsl,windows}-final.json`、`primary-source-audit.json`，初始失败日志保留，不用后续通过覆盖历史失败。

## 后续与回退

下一项 MOD-025 按各业务 Port 确认 Fake/SQLite/报表 API 的绑定与验收材料，不让模型生成 SQL，不提前承诺公司接入。MOD-026 补充逐模块可读演示，MOD-027 组合最小应用并消化保留的兼容装配，MOD-028 负责独立版本与正式升级/回滚治理。MOD-020～023 的 Checkpoint/恢复仍独立待办。

本项回退限于新增交付工具/清单/测试及文档，不修改已有数据。当前安装器面向全新目标，不支持已部署应用的原地升级或删除；正式部署回滚治理仍按 MOD-028 验收。
