# MOD-013 Ready 接入统一 Dispatcher

启动：2026-10-25；验收：2026-10-26。状态：已验收；仅启用显式注入路径，旧默认 Ready/Loop 尚未切换。

## 实施方案与范围

以 MOD-007/010/011 为依赖，向现有 execute_ready_plan 及其兼容 facade 增加服务端显式的
dispatch_binding 注入分支；未注入时完整保留原回调路径，不在本项批量切换全局工具。
新分支实际进入同一个 Ready 入口、同一个拓扑算法和 Dispatcher，不另造模型选工具循环。
默认旧入口与 Loop 的全面推广仍按 MOD-014/008 执行；不能把新分支验收说成全局切换完成。

| 文件 | 变化 |
| --- | --- |
| `execution/ready_graph.py`（新） | 提取既有拓扑算法，旧 ready_plan 保留原名称导出，不复制两份排序逻辑 |
| `execution/ready_dispatch.py`（新） | 纯 Runtime 的 ReadyDispatchBinding、ReadyDispatchOutcome 与实际异步执行/最小归约 |
| `execution/ready_result_policy.py`（新） | 显式配置的知识过滤/行数投影；保留一次调用的 raw_rows 诊断，知识工具名由装配传入 |
| `bootstrap/ready_assembly.py`、`ready_demo.py`（新） | 绑定真实同实例 Guard/Dispatcher/结果策略及独立演示，拒绝错配 |
| `tools/dispatch_contracts.py`、`dispatcher.py` | 可选服务端 ToolResultPolicy，在原始结果验证之后、最终预算记录之前处理结果；默认无策略路径不变 |
| `bootstrap/agent_assembly.py` | new_run 增加仅服务端可用的可选 result_policy，传给 Dispatcher |
| `execution/ready_plan.py`、`compatibility.py` | 增加显式注入分支；适配真实 EvidenceObservation，旧无注入调用不变 |
| 两份边界清单及专项测试 | 登记预计 5 个新文件，旧消费者按真实扫描更新，不扩大依赖方向 |

结果策略先校验原始原生输出、元数据和授权来源，再过滤/截断，随后校验最终结果/行数上限，
最后只 record_result 一次。不得因为先记录 raw 数据而误报知识进展，也不得在 Ready 再次
claim/record。策略不能改写调用/工具/版本/来源或把失败改成成功；异常转固定内部失败，不重试。
默认 Dispatcher 无策略仍维持原有超限失败语义；Ready 显式策略保留旧列表截断和知识过滤口径。
raw_rows 仅为每调用诊断，由策略产生、执行器一次消费并最终清理，不是第二份结果或预算状态。

Ready 只管理 begin/finish_round、依赖阻断和完成后进入综合；数据调用/授权/期限/取消/预算
仍由 Dispatcher 负责。bootstrap 检查 Dispatcher 的 LoopGuardToolBudget 确实包装传入的同一个
Guard，且 guard.plan、Binding.plan、执行参数为同一计划；run_id 错配或图非法时在任何调用前
失败。每步以同一 Guard 的 total_calls 计算剩余调用快照，行数取运行/计划/步骤限制的最小值。

新分支通过既有 ToolResult bridge 投影真实有效 Scope、调用级 TOOL:step 引用和 provenance；
知识来源单独由配置的提取器合并，不把制造 provenance 伪装成知识引用。失败依赖不调用
Dispatcher；执行中超时/取消保留 unknown，迟到结果不更新已结束状态。开始事件不记录原始
参数，拒绝 SQL 时不泄露查询。外层取消和事件接收异常传播，不重复调用或双重记账。

未迁工具通过显式 LegacyBindingAdapter 注册到同一个本地 Registry/Dispatcher，兼容 Schema
和 live handler patch；未授权 SQL 在查询前拒绝。原生失败不得回退执行 legacy。混合兼容在
Dispatcher/Ready 注入接缝验收，不扩展 MOD-011 的原生 AgentDefinition 工具绑定为完整插件系统。

## 验证与风险

先运行当前 Ready/Runtime/Dispatcher 基线。按 AGENTS 由 terra_worker 分不重叠批次实现；
主审独立审查实际 diff 和测试，再接受任务。专测拓扑/错误图/失败依赖、单次预算与进展、
知识过滤/截断、真实设备 Fake/SQLite、范围和 TOOL 引用、拒绝/故障/超时/取消/迟到、事件失败
不重执行、显式 legacy 实时 patch、native 不回退及模型选工具调用为零。

仓库内验证现有 Ready 入口和真实 EvidenceObservation；仓库外仅复制 MOD-011 的 44 个实际
现代源码文件加本项五文件，共预计 49 文件，运行纯 Dispatcher Ready 路径，不伪造 initializer、
不插入原仓库路径、不把它称为新安装制品。使用持续网络/DB/配置/禁止模块守卫与负向控制，
所有 app 来源属于清单；另回归 MOD-007 真安装门及原七便携单元闭包。

运行必要定向测试、Ruff/格式、新旧守卫/仓库检查、旧重构契约、冻结行为 v2。由于调整 Ready
入口、拓扑函数位置和 Dispatcher 结果采用路径，功能门通过后预声明一次正式 1000×2 配对：

```bash
python scripts/modularization_paired_baseline.py --samples 1000 \
  --report runtime/quality/mod-013-20261025-r1/paired-formal.json
```

保持原 reference、墙钟 median/p95、15.65%/16.36%/15.64% 容差与协议；失败保留，不无修改
重跑挑成功、不自动刷新冻结行为。主审独立重算原始样本并核对来源/清理。发现其他实际回归
再追加必要门；未到全阶段收尾，不预设重跑完整浏览器、覆盖率或真实模型。

风险为预算双扣、过滤后进展漂移、证据 Scope 与计划不一致、晚到结果、事件失败误标工具失败。
回退须成套恢复新增分支/策略接口和旧拓扑位置，保留 MOD-001～011 与用户已有改动；不重置
工作树、不迁移数据库、不接真实来源/模型、不新增 SHA-256 校验、不提交或推送。

## 实际实现与独立审查

五个新模块已落地。现有 execute_ready_plan 与 service._execute_ready_plan 均可接受
dispatch_binding；传入时调用实际 Dispatcher，最终仍返回真实 EvidenceObservation。
无注入时继续使用原回调路径，同时提供两种执行依赖会直接拒绝。ready_step_order 已成为
单一纯函数，旧名称仍可导入；重复 ID、未知依赖和环在事件、查询与预算 claim 前拒绝。

bootstrap 绑定时校验计划、Guard、Dispatcher 预算适配器和结果策略的对象身份及 run_id。
Ready 不再自行 check_call/record_result，由同一 Dispatcher 完成授权与单次记账。
结果策略位于原始结果校验之后、记账之前：知识先过滤再截断，最终有效数据才形成进展
指纹；raw_rows 为消费一次后清理的诊断。默认未配置策略的 Dispatcher 保留超行数失败语义。

审查修正了初版知识过滤后未截断、先进入正常综合再 finish_round，以及 demo 忽略 --tool
的行为。最终先 finish_round，保留预算耗尽/no_progress 原因；取消不发正常完成事件。
制造来源保留有效 Scope 与 provenance，知识来源仅采用 reference_id。拒绝 SQL 的事件、
trace、observation 和 demo 计划摘要均不输出查询文本。外部事件回调失败向上传播，不改判
已成功的工具、不补调查询或重复记账。三个固定信息异常边界采用逐处 Ruff 标注。

## 独立验收结果

主审在 WSL Ubuntu-24.04、fab-insight-agent Python 3.11 环境实际执行并审查：

| 项目 | 结果 |
| --- | --- |
| 改动前相关测试 | 58 项通过，0.544 秒 |
| 最终 27 模块必要定向集合 | **204 项通过，26.462 秒** |
| 本项 11 个新/修改的小文件 Ruff、格式 | 通过 |
| 新旧模块守卫、仓库检查 | 204 文件 / 0 错误 |
| 旧重构契约、冻结行为 v2 | 通过，行为差异为空 |
| 原七个便携单元重建与仓库外验证 | 通过，清单未扩充 |
| 原 37 文件 venv 真安装与新 49 文件源码隔离链路 | 通过，包含于定向集合 |
| 唯一一次 1000×2 正式配对与原始墙钟独立审计 | 通过，原阈值不变 |

204 是必要定向测试数，不是全量测试数。完整浏览器、覆盖率和真实模型本轮未重跑。
两个旧文件另按 HEAD 与当前 JSON 诊断独立比较：compatibility.py 9→9；ready_plan.py
2→1，均无新增问题，没有全文件豁免。首次定向集合曾因消费者名单排序不符失败两项，
集合本身一致；按扫描器顺序修正后完整集合通过，初始日志保留。

测试涵盖真实 service facade 注入且旧执行器不调用、Fake/双临时 SQLite、有效设备与日期
Scope 和 TOOL:step 引用、原生失败不回退 legacy、legacy handler 实时替换、知识过滤和
截断、失败父步骤阻断子步骤、单次 begin/finish/claim/record、旧新停止原因一致。
执行前取消/期限为 not_started 且零 claim；执行中超时为 unknown，外层取消传播，晚到
结果不增加指纹。事件异常发生于成功采用之后也不会重执行。SQL 拒绝保持零业务调用。

仓库外使用 MOD-011 的 44 个实际文件加本项五文件，共 **49 文件**，以 -I -S、空环境和
无关 cwd 执行 Ready demo。持续守卫阻断旧 service/compatibility/catalog/registry/settings、
模型网关、Evidence、持久化和制造报表；网络、DNS、SQLite、配置读取均有负向控制。
所有 app 模块来源属于临时清单，默认全局 Registry 为空，模型选择器为抛错 sentinel。
这是源码切片验收，不是新安装制品；MOD-007 的 37 文件/1.0.0 与原七单元保持原样。

## 正式性能与证据

按预声明采样一次，共 12,000 个原始墙钟样本、120 个 AB/BA 块，第二批反向。
主审独立排序重算每批和合并样本的 min/max、整数 median、nearest-rank p95，并以整数
算式核对原容差，没有调用 runner 的统计函数、刷新 reference 或重新采样。

| 场景 | reference median / p95（ns） | current median / p95（ns） | 原容差 | 结果 |
| --- | --- | --- | --- | --- |
| Ready | 7283428 / 8196386 | 6615477 / 7477289 | 15.65% | 通过 |
| Loop | 5157705 / 5831194 | 5103711 / 5801420 | 16.36% | 通过 |
| Knowledge | 4636149 / 5283378 | 4638259 / 5340146 | 15.64% | 通过 |

双方冻结行为通过、差异为空；环境和冻结时钟一致、网络/DB 调用均为零，环境文件为
/dev/null。app/scripts 来源均属于各自隔离树，临时树已清理。采样结束后外层 shell 的
退出码转发因空数字参数报错，但采样器已产出完整 passed 报告；独立原始样本审计通过，
未因包装命令错误重跑。以上测量是既有离线热夹具回归，不代表新路径生产延迟或真实来源效果。

证据沿用启动日目录 runtime/quality/mod-013-20261025-r1/：prechange-tests.log、
policy-review.log、install-review.log、stable-targeted-tests.log（初次失败）、targeted-tests.log、
ruff.log、repository-check.log、repository-final.log、boundaries.json、refactor-contracts.log、
behavior.json/log、portable-units.log、paired-formal.json/log、independent-audit.json 与
validation-commands.txt。boundaries.json 已在文档更新后按最终工作树复验。

## 当前边界与下一项

当前为 204 个应用文件（176 Python、28 静态），28 条精确依赖债务、20 个 DB 候选、
13 个兼容入口和 85 条静态消费者。新增两条消费者来自实际 facade 测试的 import 与 patch。
尚未删除旧 SQL、切换全局默认工具或完成整个 Runtime/Memory/Skill；本项只验收显式
Dispatcher Ready 路径。下一项为 MOD-014：Loop 接入同一 Dispatcher，完成一工具双路径
端到端对照，再按总方案推进批量工具迁移。未暂存、提交或推送；保留全部既有工作与工作簿，
文档和新增源码保持 LF。
