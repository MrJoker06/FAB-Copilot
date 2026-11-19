# Windows 与 WSL 完整回归修复

实现基线为分支 `feat/pe-ee-duty-workspace` 的 `fe505eb`。上一轮 Windows 全量发现 1563 项，13 个失败、10 个错误、3 个平台或环境跳过。

## 已修复的原因

| 原回归问题 | 处理 |
| --- | --- |
| 七个会话用例的测试替身拒绝 Thinking 参数 | 替身接受实际的 `thinking_effort`、`thinking_dialect`。流式用例核对了关闭档位和 DeepSeek 方言确实传到执行层，并继续验证事件顺序、会话读取和执行记录。 |
| Thinking 成功断言缺少推理数据 | 同一路径分别传入普通正文和带推理计数的响应，验证 answer_effective 的差异，并保留只做上下文解析的断言。 |
| 临时 SQLite 库四项错误 | 三项建库测试在提交事务后显式关闭连接。个人任务快照在临时目录中建库，避免 Windows 对已打开临时文件的共享限制。 |
| SQLite 路径和代理两项平台断言 | 分别测试原生路径和 WSL 挂载路径。Windows 每个代理环境变量只设一次，检查执行期间隐藏、退出后恢复。 |
| 三项报表依赖运行日历 | 报表用例查询 2026-06-01 至 2026-08-10 的固定参考历史区间。继续断言异常存在、设备与制程准确隔离，以及 CVD-02 的 Cpk 低于同组设备。系统测试自身装配并还原存储绑定，可独立运行。 |
| 六项旧契约断言 | 使用下节的新版本契约。代理和宿主日期测试直接比较同一场景在不同环境下的结果。个人知识页面验证 Thinking 下拉框及关闭档位。 |

## 契约审阅

- `refactor_contract_v1.json` 与 `mod_002_behavior_baseline_v2.json` 保留原始字节，供历史回放和交付参考。旧 MOD-002 命令使用其历史目录及固定数据。
- 现行 `refactor_contract_v2.json` 冻结 API、DOM、Agent 结果和默认 Tool Schema。比对确认旧 API 的操作、路径和成功状态均保留，新增 14 项操作，属于报表目录、共享资料及结果存储。OpenAPI 增加 6 个 Schema，无旧 Schema 删除。ChatRequest、ModelCapabilitiesRequest、AdminModelCapabilitiesRequest 的差异来自已上线的 Thinking 档位和 Tool 结果引用。DOM 移除的旧案例页面 ID 对应 SOP 与历史案例合并，Thinking 按钮改为下拉，增加值班工作区脚本且保留其余脚本的相对顺序。Agent 回放事件顺序和字段契约与旧版相同。默认 Tool 目录按当前 21 项具名工具与 submit_analysis 记录，旧目录仍单独验证。
- `runtime_behavior_contract_v1.json` 为六个离线场景明确列出请求分类、业务意图、是否澄清、计划状态与工具顺序、模型请求次数、工具结果及错误码、检索和降级。预期逐个定义。历史回放详细输出仍可独立对照，当前默认运行的具名查询和权限边界由原有运行测试覆盖。
- 新增两张 Windows 浏览器参考图，人工核对已有 Linux 参考图与 Windows 渲染差异，再在禁止写入快照的正常模式下复跑，沿用原来的像素阈值和布局断言。

## 完整门额外发现

- Windows 默认编码下，报表目录测试按系统代码页读取含中文的 UTF-8 JSON。测试现按存储契约指定 UTF-8。
- Windows 的中文检出路径由 Git 以文件系统编码返回。启动器现按文件系统编码解析路径；启动测试进一步核对实际提交号和快照标记，并验证工作树编辑不会进入提交快照。
- Windows 质量门以 `npm.cmd` 启动 npm，并把执行该质量门的 Python 所在目录放在 npm 子进程 PATH 的首位，使浏览器服务沿用同一环境。npm 脚本直接使用已锁定的 Playwright 包入口，适用于 Windows 和 WSL 共用一个装有依赖的检出。新增测试检查命令和解释器传递，并用真实浏览器启动验证。

## 验收证据

- Windows 99 项原问题及契约回归通过。运行测试的解释器为 `.venv-win` 的 Python 3.13.5。
- Windows 与 WSL 各 27 项启动器和报表目录专项通过，覆盖中文路径、已提交快照与工作树选择、报表 JSON 和 Qwen 示例配置保持。
- WSL 首轮完整离线门退出码 0。Python 发现 1564 项，其中非系统 1485 项（2 项既有跳过），5 个独立系统模块共 79 项全过；分支覆盖率 89%，Node 65/65，浏览器 27/27；RAG、OCR、Playbook、Ready 与 Trace 离线评估通过。该轮之后补了 Windows 编码和浏览器启动的修正，最终跨平台门以更新后的记录为准。
- 同一共享工作树上的 Windows 后续运行通过 1486 项非系统测试（3 项既有跳过）、79 项独立系统测试及 89% 覆盖率。Windows Git 对共享工作树中指向 WSL 的 Git 元数据路径返回 128，完整门在仓库检查处停止。最终 Windows 验收使用同一基线加本次改动的临时原生检出，按 `scripts/prepare_ci_data.py` 生成独立的 CI 合成数据。该检出缺少 MOD-024 本地 wheelhouse，对应测试按已有规则额外跳过。
- 仓库检查、模块边界检查及 `git diff --check` 通过。MOD-003 检查覆盖 324 个文件，0 个错误。

最终 Windows 原生检出的 `python scripts/run_quality_gate.py full` 退出码 0。Python 发现 1565 项，非系统 1486 项（4 项跳过），独立系统 79/79，零失败、零错误；分支覆盖率 89%，系统阶段总耗时 76.2 秒。Node 65/65、Playwright 27/27、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7。Windows 原生验收使用仓库声明的测试依赖及本机 Chromium，两张视觉参考图均在普通测试模式下验证通过。

最终 WSL 完整离线门退出码 0。使用 `.venv-linux` 的 Python 3.11.15，发现 1565 项，非系统 1486 项（2 项跳过），独立系统 79/79，零失败、零错误；分支覆盖率 89%，Node 65/65、Playwright 27/27、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7。会话流式模块 53.2 秒、系统阶段总计 199.1 秒触发原有告警，分别低于 80 秒和 300 秒失败阈值。两端使用合成历史数据或其临时快照，本轮未运行 Live、真实公司接口或远程 CI。
