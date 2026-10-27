# MOD-014 Loop 接入同一 Dispatcher 与单工具双路径

启动/验收：2026-10-26。状态：已验收；仅显式注入分支，默认旧调用仍待后续迁移。

## 具体实施计划

沿用 MOD-013 的显式注入方式，在现有 run_agent_loop(context, *, dispatch_binding=None)
增加服务端可选接缝，不切换默认全局工具。原模型请求/流式回调、单独 submit_analysis、
综合与证据校验继续由现有 Loop 执行；完整 Provider/客户端生命周期留到 MOD-012。
不另建生产模型循环或 Coordinator，不提前批量迁移工具、删除旧 SQL 或实现 Skill。

| 文件与符号 | 变化与验收边界 |
| --- | --- |
| execution/loop_response.py（新） | LoopResponse 与 classify_loop_response，接收既有 assistant 形状或最小 ModelResponse；只分类正文、单独提交、业务调用、混合提交，结构非法固定信息拒绝，原始参数保持字符串给 Dispatcher |
| execution/loop_dispatch.py（新） | LoopDispatchBinding / LoopDispatchOutcome、validate_loop_binding、execute_dispatched_loop_round；纯 Runtime 一轮工具执行，不创建模型客户端或重试 |
| bootstrap/loop_assembly.py（新） | bind_loop_dispatcher / bind_loop_run；复核同计划/Guard/Dispatcher/结果策略/run_id，模型工具清单从实际 Registry 按服务端能力投影，submit_analysis 不注册为业务工具 |
| bootstrap/loop_demo.py（新） | 固定 Fake 模型两阶段演示，消费同一轮次执行器；与 Ready 的同工具/来源对照。固定演示不冒充新的生产 Loop |
| execution/agent_loop.py | 可选关键字注入；查询前验证绑定，注入时使用本地能力 Schema、纯响应分类及轮次执行器；继续归约真实 EvidenceObservation、messages、sources、trace 与现有综合结果 |
| 两份边界清单、专项测试 | 精确登记四个新文件和实际消费者，不扩大整个 Runtime 的允许依赖方向 |

LoopDispatchBinding 保存 plan、guard、RuntimeContext、ToolDispatcherPort、raw_rows_for、
extract_sources、cleanup、tools_json 及装配时 initial_total_calls。后者仅是计算可信剩余调用
上限的不可变锚点，不能跨轮重置 remaining_calls，也不成为第二个预算；claim/record 唯一
权威仍是 Dispatcher 包装的同一个 Guard。计划可为非 ready，不能误套 Ready 的状态限制。

execute_dispatched_loop_round 接收计划、Guard、run_id、1-based iteration、分类响应、
progress，以及 binding/notify/emit_event；验证后拥有一次 begin/finish_round 和 finally
诊断清理。现有 Loop 的旧分支保留原 begin/finish，新分支不能再次调用。结果通过原
tool_result_bridge 投影、合并真正的知识 reference_id、产生关联模型调用 ID 的工具消息。
server call_id 为 loop-{iteration}-{index}，不采纳模型 ID 为执行身份；缺乏匹配计划步骤时
使用 TOOL:server_call_id，有精确参数匹配时使用 TOOL:step_id。参数匹配只是引用提示，
JSON 校验和执行决定仍由 Dispatcher 权威处理。单独提交只进原综合；混合提交返回该项
受控拒绝消息，其余业务调用遵循现有行为，不把 submit_analysis 发给 Dispatcher。

行数按运行/计划/匹配步骤上限最小值；复用可选结果策略，使有效数据在唯一记账之前采用。
新分支保留成功/拒绝/错误/执行中 unknown，不吞外层取消或事件错误，不在失败后回退
legacy。开始事件和失败 observation/trace 不带原参数，注入路径的模型请求/响应审计使用
安全摘要，避免恶意 SQL 从 model_call_started/finished 的 full_content 泄露。模型消息中
必要的协议关联与原参数不作为日志回显；模型可见 Schema 只含明确能力及独立综合工具。

## 验证、风险与回退

改动前相关基线已实际通过：79 项，0.714 秒，prechange-tests.log。
按 AGENTS 由 terra_worker 分不重叠所有权实现，主审等待交付后审查实际代码/差异并复跑。
专项覆盖实际 run_agent_loop 的 Fake 流响应到最终答案、同工具 Fake/双只读 SQLite 的
Ready/Loop 公共结果/有效 Scope/来源/拒绝等价、事件与预算单次采用、跨轮剩余上限、重复
参数/无进展/综合停止、混合/单独提交、非法响应/JSON、未授权 SQL 零查询及所有审计脱敏、
legacy 实时 patch、native 失败不回退、取消/期限/迟到结果和事件异常不重执行。

原 MOD-007 37 文件/1.0.0 与七个单元清单不改；MOD-013 的 49 个实际源码文件加本项四个，
预计 53 文件，验证纯轮次与 Fake 模型 Port 的仓库外链路。隔离证明不导入旧 agent_loop
或 service，不声称旧 httpx/证据/综合已完成迁移；真实旧 Loop 的集成另在仓库内端到端验证。
沿用 -I -S、空环境/无关 cwd、来源清单、持续网络/DB/配置/禁止模块守卫及负向控制。

运行必要定向集合、新旧守卫/仓库检查、旧重构契约、冻结行为 v2、Ruff 与格式；旧文件按
改动前诊断比较无新增，不全文件重排或添加总豁免。回归原七源码闭包和 37 文件实际安装。
本项改现有 Loop 热路径，功能门通过、所有源码完成后预声明只采样一次正式性能：

```bash
python scripts/modularization_paired_baseline.py --samples 1000 \
  --report runtime/quality/mod-014-20261026-r1/paired-formal.json
```

固定原 reference、1000×2、墙钟 median/p95、15.65%/16.36%/15.64% 容差，独立重算
原始样本、来源与清理；失败保留，不无改动重跑挑成功、不刷新冻结行为。未到阶段收尾，
不预设全量浏览器/覆盖率或真实模型；实际回归再追加必要门。

主要风险是预算双扣/跨轮上限重置、关联 ID 混淆、提交被当业务工具、结果已采用后事件
错误引起重试、日志泄露原始参数。回退限本项注入分支/四新模块/测试与台账，不重置工作树。
保留前序未提交修改和用户工作簿；WSL 操作、UTF-8/LF，不新增 SHA-256，不接公司来源、
真实模型，不暂存/提交/推送。

### 2026-10-26 验收修订与第二次采样预声明

r1 的 216 项必要定向、28 项最终绑定复验、冻结行为/旧契约/守卫与首次 1000×2 正式
采样均通过，12,000 个墙钟样本独立重算通过。随后主审对模型故障分支作补充审查，发现
显式注入路径仍可能通过旧 offline_answer 绕过 Dispatcher 调用业务数据；此问题不能留待
后续模型网关任务。修正仅禁止注入路径的隐式旧业务回退，保留无注入行为、重试和健康记录，
重试耗尽后传播原故障；加入实际 Loop 的零旧回退/零业务 claim 测试。

因源码发生必要变化，首次通过不作为最终修订版的性能证明。主审在功能复验通过后另行
预声明 r2，保留 r1 报告与独立审计，不放宽阈值、不刷新 reference/冻结行为，不以同代码
重跑挑选结果。r2 命令如下；本修订是在执行 r2 之前写入：

```bash
python scripts/modularization_paired_baseline.py --samples 1000 \
  --report runtime/quality/mod-014-20261026-r2/paired-formal.json
```

## 最终实现与主审验收

四个新模块与现有 run_agent_loop 注入分支已落地。纯响应分类器兼容文本/None 调用，拒绝
非法容器、重复 ID、多提交及不一致的分类；原始参数字符串由 Dispatcher 权威校验。
Loop 轮次只有一次 begin/finish，跨轮剩余额度使用装配时调用数锚点，工具查询和结果记账
均委托同一个 Dispatcher/Guard。模型 ID 只关联消息，执行 ID 为服务端 loop-iteration-index。
混合提交只返回受控拒绝消息，单独提交仍进入既有综合，不注册成业务执行能力。

模型可见 Schema 每轮都取本地能力投影，包括综合模式；未显式启用的 legacy 不进入清单。
注入绑定在客户端/模型/事件前校验，False/0 等错误配置不会退回旧执行器。新分支合并
真实 EvidenceObservation、sources、trace 和模型消息后复用原公共校验块，保留证据覆盖、
validator/synthesizer 消息、知识回退披露和 round-finished 事件，结果构建前同步上下文事实。
旧无注入分支不接受这些状态归约改变，原行为与 live patch 回归保持。

主审退回了初版仅改 Ready 输出标签的假 Loop 演示和跳过公共归约的分支。最终 demo 实际
通过 AgentRun.model_stage 收到工具选择，调用 execute_dispatched_loop_round，然后将工具
消息交给第二次 Fake 模型响应；不调用 Ready demo/执行器。仓库外测试对此设置失败 sentinel，
并持续守卫网络、SQLite、配置及旧模块导入。53 个文件均为真实源码，来源全部属于临时
清单；默认全局 Registry 为空。该证明仅覆盖纯轮次与 Fake Model Port，旧 httpx/Provider
客户端生命周期尚未移走，不能称整个旧 Loop 已可独立部署。

| 验证项目 | 主审实际结果 |
| --- | --- |
| 改动前基线 | 79 项通过，0.714 秒 |
| r1 必要定向集合 / 最终绑定复验 | 216 项通过，26.874 秒 / 28 项通过，0.322 秒 |
| r2 最终必要集合（29 模块） | **217 项通过，27.462 秒** |
| 旧模型故障/部分输出/非重试回退系统用例 | 3 项通过，0.293 秒，独立临时系统环境 |
| 本项四模块与两测试 Ruff/格式 | 6 文件通过 |
| 旧 agent_loop.py Ruff JSON 对照 | HEAD 5 项 / 当前 5 项，无新增 |
| 仓库、新旧边界守卫 | 208 文件 / 0 错误 |
| 冻结行为 v2、旧重构契约 | 通过，冻结行为差异为空 |
| 原七源码单元与旧 37 文件真实安装 | 重建/隔离验证和安装回归通过，原清单/版本未改 |
| r1 与必要源码修正后的预声明 r2 性能 | 均通过，各 1000×2；两份原始墙钟独立审计通过 |

217 为必要定向数，不是全量测试数；3 项系统用例单列，不重复计入。未重跑完整浏览器、
全量覆盖率或真实模型。测试包含真实旧 Loop 两轮到综合的完整调用、独立提交不进 Dispatcher、
SQL schema sentinel 在两个模型轮次都被剔除、双临时只读 SQLite 的 Ready/Loop 实际
status/data/row_count/error/来源/有效 Scope/TOOL 引用一致。跨轮额度、空结果无进展、
执行前 deadline/取消、外层取消与晚到无指纹、采用后 notify/emit 故障不重执行均通过。
模型可用性故障不会进入旧 offline_answer；同条件下默认旧路径的回退仍通过专门回归。

## 最终正式性能与证据

r1 通过后发现并修复模型故障绕过，故按上文预声明执行 r2；不是对同源码无修改重跑。
两报告及初轮审计均保留。以下为最终 r2：每侧每场景 1000×2，共 12,000 个原始墙钟
样本、120 个交替 AB/BA 块。主审不用 runner 统计函数，独立重算每批/合并 min/max、
整数 median、nearest-rank p95，以整数式核对原容差。

| 场景 | reference median / p95（ns） | current median / p95（ns） | 原容差 | 结果 |
| --- | --- | --- | --- | --- |
| Ready | 7864442 / 8779264 | 7155667 / 8030963 | 15.65% | 通过 |
| Loop | 5573514 / 6283459 | 5532110 / 6295029 | 16.36% | 通过 |
| Knowledge | 5141450 / 5827772 | 5160298 / 5884212 | 15.64% | 通过 |

双方冻结行为通过、差异为空，环境/冻结时钟一致；network_calls/database_calls 为零，环境
文件为 /dev/null。app/scripts 来源均属对应隔离树、临时树已清理；两次正式进程均正常
退出。数据是原离线热夹具回归，不证明真实模型或公司来源延迟。

证据目录：runtime/quality/mod-014-20261026-r1/ 保留 prechange-tests.log、targeted-tests.log、
final-binding-review.log、core-followup-tests.log、ruff.log、repository-final.log、boundaries.json、
refactor-contracts.log、behavior.json/log、portable-units.log、paired-formal.json/log 和
independent-audit.json。最终 r2/ 保存 targeted-tests.log、legacy-fallback-system.log、ruff.log、
repository-final.log、behavior.json/log、paired-formal.json/log、independent-audit.json；
命令与环境另见 r2/validation-commands.txt。

## 当前边界与下一项

208 应用文件（180 Python、28 静态），28 条精确债务、20 个 DB 候选、13 兼容入口 / 85
静态消费者。未退出的依赖仍保留原任务，不靠改名或删除台账宣称消失。原 37/1.0.0 安装
制品及七单元清单不变，53 文件证明不是可与全应用任意组合的 Wheel。默认全局 SQL 仍在，
Memory/Skill/Checkpoint 尚未整体实现。下一项按主线为 MOD-008：分批推广具名工具/Ports，
以单列的能力版本替代并退出模型 SQL，再 MOD-009→012→015。未暂存、提交或推送，
保留既有改动和用户工作簿；文档/新增源码为 UTF-8/LF。
