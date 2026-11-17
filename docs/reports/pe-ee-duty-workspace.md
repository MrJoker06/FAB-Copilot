# PE / EE 值班工作区

日期：2026-11-17。源码起点为 `experiment/parallel-platform` 的 `dcca19f`，独立分支为 `feat/pe-ee-duty-workspace`。本轮按用户确认的页面方向优先实施，旧 `main` 和 experiment 分支引用不变；最终提交及推送状态以 Git 为准。

下方原有范围、数字和验证记录描述首轮 `220a333`。最新的报表目录管理、共享上传和案例入口合并见文末追加记录，不能将首轮的 321 文件/23 项浏览器数量当成当前值。

## 目标与范围

产品主要服务 PE / EE 值班工程师。左侧顺序为基础报表、SOP&历史case、Autosystem 平台、值班智能助手；原制造总览、制程能力、知识库、案例库放入底部默认折叠的「所有功能」。原中间总览、右侧助手和原业务分析能力保留。用户指定页面不显示额外的演示报表标识。

根目录 `display_mock_data/` 保存人工编写的合成展示资料：六类报表（SPC、WIP、告警、设备状态、良率、PM），三份 SOP 与三个历史 case（CVD、ETCH、LITHO）。资料日期固定为 2026-11-17，不表示接入生产系统。

## 实现与取舍

- `app/static/app/shift/controller.js` 是现有前端控制器装配中的一个直接消费者；加载单份目录，负责检索、岗位/制程筛选、资料阅读、关联 SOP 和报表链接。最近查看来自实际点击，只保留当前页面生命周期，不伪造历史记录。
- 「向值班智能助手提问」将当前资料的编号、日期、正文填入可编辑草稿，触发已有草稿保存。用户自行发送前不调用聊天接口。资料不会自动入库、参与 RAG 或注册为 Tool。
- `app/api/application.py` 在目录存在时挂载 `/display_mock_data/`；该目录是公开静态展示内容，不是公司文档服务。沿用 StaticFiles 的路径边界，缺失目录/文件明确返回 404，前端显示加载失败并允许重试。链接仅接受相对根路径或无凭据 HTTP(S)，拒绝脚本协议、网络路径与反斜杠。
- `catalog.json` 的报表 URL 可以后续替换；`autosystem_url` 当前为 null，点击明确提示未配置。实际公司身份、授权、接口和文档同步未实施；公司资料不能直接放进此公开目录。
- `run.py` 的完整源码导出白名单加入该根目录，Git 快照也会包含已提交资料。新增静态控制器归现有 `static_ui/application_bundle` 所有者，受管 app 文件变为 321（292 Python + 29 静态），版本一致制品为 325 成员（含 4 个 Skill 文本）。独立模块 Profile 的成员不变，展示目录不加入它们。
- 仅更新一张 Linux Chromium 视觉基线：长回答截图因固定助手标题由旧名称改为值班智能助手而有 665 像素差异，正文、表格和尺寸未变。检查差异后更新，并以非更新模式复验。未刷新业务 Golden、冻结行为或 API 契约来消除既有失败。

## 验证

原始日志和截图位于被忽略的 `runtime/quality/`。下列命令均在本工作树执行，不调用 Live 或真实模型。

环境：原生 Windows Python 3.13.5（`.venv-win`）、WSL Python 3.11.15（`.venv-linux`）、WSL Node 22.22.2 / Chromium。Windows 命令显式使用 `-X utf8`。

| 命令 / 范围 | 实测结果 |
| --- | --- |
| 两端 `python -m unittest tests.test_startup_script tests.test_display_materials tests.test_api_runtime_boundaries tests.test_module_release`（Windows 加 `-X utf8`） | 各 38/38；验证完整源码导出包含展示目录、实际静态响应、缺失/越界拒绝、325 成员归属与可重复构建 |
| `node --test tests/*.test.js`（WSL） | 64/64；新增链接协议拒绝与组合筛选验证 |
| `npm run test:e2e`（WSL，非更新模式） | 最终 23/23；新增 4 项覆盖新导航、折叠/键盘操作、实际报表内容、SOP/case 关联、草稿不自动发送、失败后重试与 Axe 扫描；原页面及结果卸载链路通过 |
| Windows 完整 unittest，隔离副本与清空模型密钥，`python -X utf8 runtime/quality/persistence_audit.py . runtime/quality/duty-audit-windows` | 1522 项，12 失败、10 错误、3 跳过，测试运行 440.219 秒；不是全绿 |
| WSL `python scripts/check_repository.py` | 通过 |
| WSL `python scripts/check_module_boundaries.py` | 通过 |
| WSL `python scripts/check_modularization_boundaries.py` | `files=321 errors=0` |
| `ruff check app scripts tests run.py --output-format json` | 507 条既有问题；与已存基线按文件/规则/描述计数对照，无新增问题，不宣称全仓 Ruff 全绿 |
| `git diff --check`、本轮文本 UTF-8/LF、文档本地链接 | 通过 |
| 实际应用启动与内容检查 | WSL 由浏览器服务器启动完整应用并运行上述 23 项；Windows 独立测试服务器启动成功，HTTP 实读 health、新页面 HTML、6+6 目录及含 LOT-017 的报表；均使用隔离数据库和本地模型协议夹具 |

原始记录包括 `shift-python-final-windows-utf8.log`、`shift-python-final-linux.log`、`shift-node-final.log`、`shift-browser-verified.log`、`duty-audit-windows/{summary.json,unittest.log}`、`duty-ruff.json` 和 `duty-windows-start-result.log`。实际页面截图为 `duty-dashboard.png`、`duty-reports.png`、`duty-procedures.png`，均在 `runtime/quality/`，不提交为业务资料。

### 基线与失败说明

完整 Windows 审计的 12 个失败 ID、10 个错误 ID 与既存 `mod029-audit-windows-0cae608/summary.json` 完全一致，无新增失败/错误 ID；`0cae608` 到本轮起点 `dcca19f` 无 app 源码差异。本轮未重新运行旧树完整审计，对照使用上一轮留存日志。DOM/脚本冻结契约本就失败，本轮又有明确获准的新页面/脚本差异；不能将同名失败理解为该冻结契约已通过。详细既有失败见 [MOD-029 报告](mod-029-tool-result-access.md)。

首次相关测试还发现交付成员断言漏改（324→325），已修正并在两端重跑通过。Windows 首次未显式启用 UTF-8 时有五项 Unicode 路径启动夹具失败；使用与既有审计一致的 `-X utf8` 后 38 项通过。首次浏览器回归为 22 通过/1 视觉差异；人工检查后仅更新上述获准改名对应截图，最终 23 项通过。Windows 首次实际启动使用 8896/8897 时，本地模型夹具绑定 8897 被 WinError 10013 拒绝；保留原日志，改用实际可绑定的空闲端口对后启动成功。没有因此修改应用端口规则。

本轮未运行真实模型/公司接口、Live、移动专项、远程 CI、新的覆盖率或性能门；也未重新运行 RAG/OCR/Ready/Playbook 黄金集。业务算法、Tool Schema、证据策略与存储协议未改，本轮完整 Python 与桌面回归不等于完整质量门全绿。

## 后续接入边界

真实公司报表链接、Autosystem 地址以及 SOP/case 来源尚待确定。当前只交付可交互的展示页面及独立资料文件，不宣称公司接口、LDAP、生产权限或正式 SOP 已生效。本轮不自动推进 MOD-025～028 或恢复链任务，产品统计 228/183/45 保持原口径。

## 报表目录与共享资料追加（基线 220a333）

### 用户确认的范围

- 基础报表前台统一平铺、搜索和最近查看，不显示分类筛选。管理端在与运行状态、模型目录并列的「报表目录」中配置文件夹树。
- SOP&历史case 增加用户上传入口；处理完成后立即向所有用户共享，不增加审批流程。管理员可编辑标题、类别、制程和启用状态。
- 原「所有功能」里的案例库入口合入历史case，原案例记录和来源跳转保留；原个人知识的私有存储不改为共享。
- 用户说明公司 Qwen 配置位于公司电脑，本机不需要恢复。保留现有模型配置、连接、凭据与思考档位机制；本次不修改模型注册或接入代码。

### 实际实现与存储

`api/report_directory.py` 为管理端提供目录读写，验证文件夹引用/环、同级重名、报表 ID、字段长度与安全链接；公开接口只返回已启用的平铺链接。目录首次保存前读取展示 catalog 默认值，之后使用独立 JSON 配置，原子替换且通过 revision 拒绝过期覆盖。管理端支持建立/改名/移动文件夹、删除空文件夹，以及报表新增/编辑/移动/排序/启停/移除；本页编辑需点击「保存目录」生效。原子替换与进程内锁不宣称多工作进程的事务隔离。

`api/routers/shared_documents.py` 复用现有用户/管理员认证依赖，装配上传、列表、阅读、下载、管理员编辑与失败重试。`knowledge/shared_documents.py` 接收显式存储根路径，沿用现有文件校验、正文抽取、OCR 和质量判断，独立保存原文、元数据和抽取结果，不引用应用配置。应用启动只恢复已有库中的 processing 记录，不因启动创建新共享库。读取/上传/管理共享资料时才建立对应库。

默认持久位置是工作树根目录下的 `runtime/local/report_directory.json` 与 `runtime/local/shared_documents/{documents.db,files/}`；可通过 `FAB_REPORT_DIRECTORY_PATH`、`FAB_SHARED_DOCUMENTS_ROOT` 指定路径。启动器将其显式传给源码快照，避免更换源码快照后丢失这些新功能的页面数据。它们不写入公开展示目录、模型目录或个人知识库，也不纳入 Git。备份共享资料应同时保存数据库和原文目录。生产公司接口与 LDAP 未接入。

处理中和失败的元数据由上传者查看，失败原因明确展示；ready 且启用后向所有用户共享。停用会拒绝普通用户（包括上传者）的正文和下载接口，其他用户列表隐藏该资料；上传者仍可看到停用提示，管理员保留原文与内容供管理。恢复启用后重新共享，不删除或冒充处理成功。已下载到用户电脑的副本不在停用控制范围内。

前端合并展示 catalog、原案例 API 与共享资料 API，分别显示加载错误；一个来源失败不遮蔽其他来源。原案例通过原 ID 读取详情，旧来源链接和旧 cases 视图 URL 进入合并页面。桌面端长列表与正文分别滚动。上传资料当前用于页面阅读、下载及填入助手草稿，不自动加入 RAG 索引；原工厂案例 RAG 保留。管理员本次编辑指元数据与启用状态，不包含在线修改原文。

新增 3 个 app Python 文件后，受管源码为 **324（295 Python + 29 静态）**，版本一致源码/资源制品为 **328 成员**；新增两个 DB 调用候选（HTTP 绑定的 sqlite3 错误处理、共享资料真实存储），台账共 37 项。依赖债务仍为 10，兼容入口/消费仍为 7/99，独立模块 Profile 成员不变。未扩展业务 Tool 清单、输入 Schema 或证据策略。

### 追加验证

以下均使用隔离测试目录；不调用真实模型或公司接口。原始日志保留在 `runtime/quality/`，不提交。

| 命令 / 范围 | 实测结果 |
| --- | --- |
| 两端 `python -m unittest tests.test_startup_script tests.test_display_materials tests.test_api_runtime_boundaries tests.test_module_release tests.test_duty_workspace_management tests.test_browser_test_server` | 各 56/56；Windows 使用 `-X utf8`。验证新路径在快照外持久保存、328 成员交付清单、测试存储与宿主隔离，以及真实上传/跨用户阅读/停用/恢复/非法文件拒绝/处理恢复 |
| 路径装配修正后，两端 `python -m unittest tests.test_duty_workspace_management tests.test_api_runtime_boundaries` | 各 13/13；实际 HTTP、SQLite、原文与拒绝结果通过 |
| `python -m unittest tests.test_modularization_boundaries`（Windows） | 28/28；边界台账更新后复验，不将拒绝场景中的故意错误当成检查失败 |
| WSL `node --test tests/*.test.js` | 64/64 |
| WSL `npm run test:e2e`（最终非更新模式） | 25/25，2.0 分钟；报表文件夹持久化/前台平铺/模型目录前后相同，共享上传/跨用户阅读/管理员编辑与停用后内容下载拒绝均通过；包含 Axe 扫描和原案例来源跳转 |
| WSL `python scripts/check_repository.py`、`check_module_boundaries.py`、`check_modularization_boundaries.py` | 均通过，`files=324 errors=0` |
| Ruff 全仓差异 / 新增文件 | 506 条既有问题，对照首轮 507 条按文件/规则/描述计数无新增；新增 4 个 Python 文件单独检查通过，不宣称全仓 Ruff 全绿 |
| 实际原生 Windows 启动 | 真实临时 FastAPI 服务的目录保存、共享上传/阅读/下载、管理员停用与模型目录不变验证通过；使用离线协议夹具和隔离存储 |
| WSL 预览 | `run.sh --source-mode worktree --port 8888`，显式复用此前预览实例，日志确认已有部门数据未重新生成；health、6 个平铺报表和共享列表实际响应通过 |
| Windows 完整 Python 审计 | 1528 项，14 失败、10 错误、3 跳过，419.521 秒；保留结果，不宣称全绿。与基线及随后定向修正的关系见下文 |

日志包括 `duty-management-python-{linux,windows}-final.log`、`duty-management-injection-{linux,windows}.log`、`duty-management-boundary-unit-windows.log`、`duty-management-browser-complete.log`、`duty-management-checks-final.log`、`duty-management-ruff.json`、`duty-management-windows-start-result.log`。实际截图为 `duty-admin-report-folders.png`、`duty-shared-case.png`，保存在同一忽略目录。

首次 6 项专项有两项因工厂函数内 Depends 注解未正确解析而返回 422，移除延迟注解后通过。首次浏览器为 24 通过/1 失败，原因为测试选择器匹配了两个嵌套列表，修正后两项新增链路及最终全部 25 项均通过。首次边界检查发现资料模块读取配置的问题，已改为应用层注入路径；随后显式补齐两个新增 DB 候选。首次完整审计包含这两项台账未登记造成的边界失败，保留日志，不将其抹去为一次通过。

Windows 完整审计先后两轮均为 1528 项、14 失败/10 错误/3 跳过，分别耗时 483.579、419.521 秒。首轮包含两项已修正的边界台账失败，随后 28 项边界测试通过；第二轮无这些边界失败。第二轮相对 `220a333` 留存的 12 失败/10 错误基线，失败 ID 增加两项，错误 ID 无新增：

1. `test_snapshot_launches_seed_then_server_with_isolated_unicode_paths`：本次追加的默认路径断言继承了完整系统测试留下的显式临时存储环境，导致期望根目录与显式覆盖路径不一致。已只修改启动测试夹具，在未显式传参时移除继承的两个新路径变量；原生 Windows 与 WSL 均注入宿主干扰路径后实际运行整个启动测试模块，各 20/20。没有修改应用以忽略显式配置，也未据此再跑第三轮完整审计。
2. `test_fixture_proxy_environment_is_hidden_and_restored`：Windows 环境变量不区分大小写，而旧测试用 frozenset 同时生成 HTTP_PROXY/http_proxy 等不同值，取决于哈希遍历顺序。首次基线单项对照通过；固定 `PYTHONHASHSEED=1` 后，在 `git archive 220a333` 导出树和当前树上用相同 `.venv-win` 各跑该单项，均出现相同 `sentinel-http_proxy != sentinel-HTTP_PROXY` 失败。保留为可复现的既有 Windows 测试问题，本次不夹带修复。

相关记录为 `duty-management-audit-{final-windows,windows}/{summary.json,unittest.log}`、`duty-management-startup-fixture-fixed-{windows,linux}.log`、`duty-management-proxy-{baseline,baseline-seed1,current-seed1}/`。未重新导出旧树跑全套；12 项既有失败集合仍来自首轮保留日志，API/DOM 冻结契约存在本次明确获准的新接口/页面差异，不能将同名失败理解为契约已通过。最终应用代码的桌面浏览器、两端新增后端链路及边界检查通过；完整门仍保留失败，定向修正后的完整套件未再次运行。

未新增有效覆盖率、性能门、Live、远程 CI 或公司模型接入证据。产品统计 228/183/45 及其他 MOD 排期不变。
