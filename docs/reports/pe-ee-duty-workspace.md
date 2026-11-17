# PE / EE 值班工作区

日期：2026-11-17。源码起点为 `experiment/parallel-platform` 的 `dcca19f`，独立分支为 `feat/pe-ee-duty-workspace`。本轮按用户确认的页面方向优先实施，旧 `main` 和 experiment 分支引用不变；最终提交及推送状态以 Git 为准。

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
