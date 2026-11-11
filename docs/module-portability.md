# 可搬迁模块与版本一致交付

本项目当前仍是模块化单体，交付保留 `app.*` 导入路径与模块身份。旧 `portable_units_v1` 的七个 ZIP 用于各自独立解压验收；MOD-024 另建立按唯一文件所有权划分的版本一致源码制品，用于选择 Profile 后共同安装。两者均不是独立发布的 Wheel 或服务，完整 HTTP 应用与真实公司接入仍按后续里程碑验收。

## MOD-024：版本一致的源码制品（已验证，2026-11-10）

发布清单 `evaluations/mod_024_release_v1.json` 复用 MOD-003 的五类所有者，按一个明确版本的 cohort 交付：

| 制品 | 内容归属 |
| --- | --- |
| `platform_core` | Runtime、Memory、工具框架、编排、模型传输、证据与必要契约 |
| `manufacturing_capability` | 制造工具 Handler、业务契约及明确声明的光刻 Skill 文本资源 |
| `enterprise_adapters` | 已有数据源、检索和存储/身份适配源码；不代表真实公司接入已验收 |
| `simulation_fixtures` | 非生产演示与模拟源码 |
| `application_bundle` | 包根、显式装配、API、前端等应用源码 |

五个 ZIP 是同一版本发布组的组成部分，不能各自升级成任意版本组合。发布清单记录源码提交或显式构建 ID、各文件唯一所有者、每个 ZIP 的成员和所需版本，以及目标环境锁。共享包锚点只由一个制品拥有；选择多个 Profile 时，共用文件只安装一次。

“制品包含源码”与“已形成可运行 Profile”分别记录。首批 Profile：

| Profile | 安装范围 | 外部依赖 |
| --- | --- | --- |
| `tool_sources` | MOD-009 的 104 个真实 Python 文件，包含 21 项原生工具的 Fake Ready/Loop 演示 | 标准库 |
| `skill_release` | 100 个 Python 文件及 4 个原路径 Skill 文本资源，覆盖光刻 Cpk 与进程内发布机制 | 标准库 |
| `model_transport` | 5 个 app 文件，覆盖 SSE、聊天模板整形及 `ModelGatewayPort` HTTP Adapter | httpx 与锁定的传递依赖 |

仅选 tool_sources 时不启用 Skill；如 AgentDefinition 声明非空 skill_refs，必须同时选择 skill_release。TYPE_CHECKING 中的类型声明依赖不计为运行 Profile，完整源码类型检查另行进行。

当前发布组包含 309 个受管 app 文件及 4 个 Skill 文本资源，共 313 个源码/资源成员；这是 MOD-031 实现后的口径。MOD-024 原报告保留当时 286 + 4 的历史基线。安装器仅安装所选 Profile 的声明文件；其余源码标为尚未纳入运行 Profile。源码入包不代表全部 API、Checkpoint 或公司真实集成已通过。

### 构建与安装

在仓库中使用相应平台 Python 构建，始终显式提供构建 ID；Git 可用时另记录源码提交，无法解析时明确标记 unavailable：

```bash
python scripts/build_module_release.py --output runtime/module-release --build-id mod024-1.0.0
```

将输出目录中的发布清单、五个 ZIP、独立安装器和验收脚本复制到目标环境。源代码安装只需要 Python 标准库，目标机器不需要原仓库或开发环境。先创建新的 venv；仅安装工具/Skill 时可使用 `python -m venv --without-pip <环境目录>`。用目标解释器查询安装位置：

```bash
<目标Python> -I -c "import sysconfig; print(sysconfig.get_path('purelib'))"
```

在无关工作目录调用交付目录内的安装器，填入上述目标解释器和其 site-packages：

```bash
<宿主Python> -I <交付目录>/install_module_release.py \
  --delivery <交付目录> --target-python <目标Python> \
  --target-site-packages <目标site-packages> \
  --profiles tool_sources skill_release
```

示例中的续行符为 Bash 写法；PowerShell 可将参数写为一行。目标解释器在 Windows 中位于 `Scripts/python.exe`，Linux/WSL 中位于 `bin/python`。安装器拒绝已有 app 或其他未声明的安装内容；不负责原地升级、删除或覆盖用户数据。

### 在目标环境验收

构建器同时交付 verify_module_release.py。仅复制交付目录即可运行：

```bash
<宿主Python> -I <交付目录>/verify_module_release.py --delivery <交付目录> --work-dir <全新目录> --report <报告.json> --wheelhouse <本地Wheel目录>
```

该命令新建目标 venv、组合安装真实源码，并输出工具/Skill 与模型传输的机器报告。未提供 wheelhouse 时模型标记 NOTRUN，不能算全部通过。验收工作目录不能位于交付目录内部，也不覆盖旧验收目录。

### 环境锁与离线依赖

首批锁定目标为 Linux/WSL CPython 3.11.15 x86_64 与原生 Windows CPython 3.13.5 AMD64，分别记录平台、架构、解释器版本和 ABI。安装器探测实际目标解释器，不以宿主 Python 的信息代替。其他环境需单独解析、生成目标锁并验收，不能直接把已有锁当作跨平台通用锁。

`model_transport` 需要 pip 可用的新 venv，以及显式准备的本地 wheelhouse。直接依赖与传递依赖按精确版本记录；安装器只从该目录离线解析和安装，不借用宿主 site-packages，不自动联网补包。命令增加 `--profiles model_transport --wheelhouse <本地Wheel目录>`；也可在同一次安装中组合三个 Profile。

源文件安装前验证完整发布组的版本、所有权、成员、路径和目标依赖；拒绝缺失成员、重复文件、版本不符、平台不匹配与依赖缺失。不新增自建内容哈希门。完整验收结果和实际验证命令见 [MOD-024 报告](reports/mod-024-module-delivery.md)。

## 旧版七单元与独立验收（保留兼容）

| 单元 | 包含能力 | 独立验收 |
| --- | --- | --- |
| `memory_core` | 上下文记忆契约、规则、协议与 use case | 在临时目录解压后运行历史窗口单元测试；所有 `app.*` 导入必须来自 ZIP。 |
| `decision_core` | 确定性 Router、Planner、Playbook、制造工序词表与证据语义 | 在临时目录解压后执行随包的 12 条 Playbook Golden Set；所有 `app.*` 导入必须来自 ZIP。 |
| `model_transport` | OpenAI 兼容 SSE 解析、工具调用拼装、推理审计脱敏与重试分类，以及 `ModelGatewayPort` 的 HTTP Adapter（客户端生命周期、URL/凭据头、聊天模板整形） | 在临时目录解压后，使用 `httpx.MockTransport` 完成无网络流式验收；所有 `app.*` 导入必须来自 ZIP。 |
| `enterprise_data_contract` | 制造数据 Provider 与仅含 `tenant_id` 的数据主体契约 | 在临时目录解压后使用假 Provider 与假主体完成无数据库、无网络的离线契约测试；真实 Adapter 不包含在 ZIP 中。 |
| `retrieval_policy` | 检索候选重排、来源选择与证据不足时的确定性降级判定 | 在临时目录解压后对固定候选集验证元数据筛选、排序和 grounding/fallback 语义；不连接数据库或网络。 |
| `factory_search_contract` | 工厂知识/历史案例的检索与目录查询主体、请求、候选/目录响应契约和查询分词 | 在临时目录解压后以假 Provider 验证 tenant、user、roles、检索与目录请求/响应完整性；无数据库、无网络。 |
| `identity_contract` | 不可变身份 Claims 与演示 API Header 解析策略 | 在临时目录解压后验证默认主体、必需 Header、标识格式和长度、角色过滤及 demo/header scheme；无 HTTP、配置、数据库或网络。 |

构建命令（先激活项目 Conda 环境；`model_transport` 的离线验收前提是目标环境已安装 `httpx>=0.28,<1`）：

```bash
conda activate fab-insight-agent
python scripts/build_portable_unit.py --verify
```

默认产物位于被 Git 忽略的 `runtime/portable/`。可用 `--output-dir <目录>` 指向交付目录。每个 ZIP 内的 `portable-unit.json` 固定记录单元名、版本、显式文件列表及（如需要）外部依赖；构建器保持可复现 ZIP，并拒绝缺失文件、不安全路径、数据/日志/密钥类路径、未声明 ZIP 成员，以及未在单元清单中声明的 `app.*` 静态导入。它不使用内容哈希作为验收条件。

这些 ZIP 不能共同安装：当前清单的重复文件为 `app/__init__.py`、`app/core/__init__.py`、`app/core/manufacturing_terms.py` 和 `app/knowledge/__init__.py`。它们仅用于各自解压后的隔离验收；组合发布前必须指定唯一文件所有者或采用版本一致 Bundle（MOD-024 已提供后者）。

## 旧七单元的迁移使用方式

1. 在本仓库修改一个单元，并运行它自己的测试和 `--verify`。
2. 将生成 ZIP 复制到内网测试机，解压到空目录；此时不需要原仓库、SQLite 演示数据、日志或 `.env`。
3. 用该单元的验收命令确认行为，再由内网侧把它接到后续 Adapter 或应用层。
4. 主仓库仍通过相同 `app.*` 路径使用代码，直至后续切换为独立包或服务。

## 旧七单元未覆盖的部分（P0 范围说明）

以下按旧七单元的交付范围说明；其中 Runtime/Skill 的新 Profile 进展以本文 MOD-024 部分为准。当前发布组已包含完整受管源码，但并非所有文件都有已验收的运行 Profile。

- `model_transport` 仅覆盖流式协议、重试策略和 `ModelGatewayPort` HTTP Adapter；完整模型网关的目录、配置、健康检查、真实端点、密钥与模型发布仍不能随该单元迁移。它要求目标环境自行安装 `httpx>=0.28,<1`，且不应在验收时调用网络。
- `enterprise_data_contract` 仅交付 Provider 契约；`enterprise_data.py` 中现已提供显式注册接缝，内网装配代码可注册实际 Adapter 后用 `FAB_DATA_PROVIDER` 选择它。Oracle 表、DSN、驱动、网络客户端和报表仍不在该单元中，也尚未完成 `DATA-017`、`DATA-018` 或 `DEPLOY-018`。
- `factory_search_contract` 交付候选检索、知识文档/历史案例目录查询的可替换契约与分词规则。应用现在可用 `FAB_FACTORY_SEARCH_BACKEND` 选择显式注册的非 SQLite Adapter；目录调用必须由同一 Adapter 实现，缺少方法、未知名称、构造失败和畸形候选/目录响应都会失败关闭，绝不静默退回 SQLite。目录验证只允许 Active 文档和 Validated 案例，并校验 detail 的请求 ID 与文档—章节来源一致性。默认 `sqlite` 仍是本地演示实现，未完成生产 ACL 声明或强制执行。
- `identity_contract` 仅交付 Header Claims 的解析与校验策略；它不是可信认证、SSO/JWT、权限/ACL 强制执行，也不会迁移个人知识 owner。`PrincipalContextMiddleware` 仍是 HTTP/API 装配层，读取当前配置、保留请求关联 ID 和既有 401/400 JSON 合约；内网部署必须以受信任身份 Adapter 替换该演示 Header 路径。
- `retrieval_policy` 仅交付候选元数据排序和 grounding/fallback 规则。个人知识存储、生产用户 ACL 与身份隔离仍在应用路径中，尚不可随该单元独立迁移；`RAG-019`、`DATA-019` 和 `DEPLOY-018` 均未完成。
- 检索与引用契约已抽取并经过 MOD-008 验收；完整 OCR、个人知识存储与后端尚未形成 MOD-024 运行 Profile。
- Agent Runtime 已完成 MOD-015 收口，工具来源与 Skill 可显式受控装配；完整默认应用的独立组合与兼容装配退出仍由 MOD-027 验收。
- API、身份、会话持久化、前端和监控仍依赖应用装配；旧七单元不包含这些实现。MOD-024 发布组已包含其受管源码，但未形成完整 HTTP 应用运行 Profile。

后续切片、依赖次序和验收门由 [总方案](architecture-modularization-master-plan.md) 与 [模块化工作包追踪](todos/modularization.md) 管理。本轮 P0 的七单元基线、工作树范围和构建记录见 [MOD-001 便携基线报告](reports/mod-001-portable-baseline.md)。每片仍需提供显式文件清单、离线验收、隔离解压验证和可回滚的兼容接入。

## decision_core 1.0.1 增量（历史记录）

以下描述 MOD-002 当时的结构验证，保留原结果；当前版本及阶段状态以实际清单和工作包追踪为准。`decision_core` 从 1.0.0 升至 1.0.1，仅将 `app/evidence/serialization.py` 纳入显式文件清单，以服务于 Evidence/Answer 域的等价序列化 helper；当时其余六个单元仍为 1.0.0。`python scripts/build_portable_unit.py --verify --output-dir runtime/portable/mod-002-20261022-r5` 已验证全部七个单元（含 `decision_core-1.0.1.zip`），全部新 ZIP 成员均为普通 100644 模式。该结构验证不替代当时尚未通过的 MOD-002 墙钟性能门；后续通过记录见对应报告。

## MOD-031 实现后的成员口径（2026-11-11）

当前清单为 309 个受管应用文件加 4 份 Skill 资源，共 313 个唯一成员；tool_sources 为 104 个源码，skill_release 为 111 个源码加 4 资源，model_transport 为 5 个源码。三 Profile 源码并集 153、加资源 157。旧目录已退出，来源与 Tool 同组，Fake/模拟数据单独归 simulation_fixtures；共享策略和 Tool 语义描述各有唯一文件所有者。当前验证与未验证项见 [MOD-031 报告](reports/mod-031-validator.md)。历史 MOD-024/MOD-030 报告保留原值，冻结 v4 参考保留旧成员身份，不能与当前 Profile 清单混用。

光刻默认交付组合为 Skill 2.0.0 / Workflow 3.0.0 / capability-evidence 2.0.0；旧发布可通过固定 Workflow 2.1.0 使用原 1.3.0 策略。发布对象仍在进程内，必须随制品提供匹配的源码、资源和可信版本配置；回退不能只修改清单版本或删除必需策略。默认诊断使用 2.0.0，旧 1.2.0 保留为有消费者的明确版本配置。
