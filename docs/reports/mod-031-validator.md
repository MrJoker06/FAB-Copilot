# MOD-031：验证职责与业务证据策略实施记录

执行起点：`638f772`，分支 `feat/local-qwen3-runbook`，起始工作树干净。需求依据：[确定版方案](../validator-responsibility-plan.md)。用户先授权按方案开发，验收完成后明确要求提交同步；本报告随 MOD-031 实现一并提交，实际提交和远程状态以 Git 记录为准。

## 031a：基线与契约

已完成源码入口、七类声明及持久化/外部消费者核对。旧默认路径由 `compatibility` 的依赖快照向 Ready/Loop/离线阶段提供验证函数；显式 Skill 由可信 Workflow 提供验证函数。统一结果仍复用现有 EvidenceValidation，后续增加四个字段：assessment_status、assessment_reason、policy_ref（component_id/version 或 null）、evidence_sufficient（boolean/null），不改外层 HTTP/SSE 键与 event 名。新决定不依赖旧 validated 字面值。

宿主必需策略绑定由可信 Workflow/默认诊断装配承担；无执行资格的澄清 Plan 与已激活诊断的检查失败必须区分，不能把用户缺输入当成来源成功或验证通过。旧发布引用 1.3.0 与新规则 2.0.0 按版本处理。历史存储记录不回填本次结论。

Windows Python 3.13.5（`.venv-win/Scripts/python.exe`），同一环境、UTF-8、PYTHONHASHSEED=0，在 `git archive 638f772` 导出树运行：

```text
python -m unittest tests.test_evidence_validator tests.test_evidence_semantics tests.test_evidence_serialization tests.test_skill_evidence_policy tests.test_skill_standard tests.test_answer_synthesizer tests.test_evidence_truncation
python -m unittest discover -s tests -t .
```

前者 116 项通过（3.552 秒）；全量 1449 项、12 失败、10 错误、4 跳过（310.301 秒），不是全绿。导出树按既有系统夹具需要复制本地部门模拟库，未改原数据库。完整失败标题与原日志保留在忽略目录 `runtime/quality/mod031/baseline-full.log`；定向日志 `baseline-target.log`。配置隔离，模型密钥清空，未调用真实模型或公司接口。

## 031b：等价拆分

本节保留等价拆分批次的实现和验证；不能用该批结果替代后续 031c～e：

- 七类 evidence_requirements 的唯一来源为 `app/skills/policies/manufacturing.py`；原规划声明构造视图，命名工具替换也由该来源提供，不维护两份字段清单。
- `app/skills/policies/capability.py` 承接制造样本/来源/冲突检查、参数匹配及旧光刻知识焦点匹配，保留原版本行为。旧 `app/evidence/skill_policy.py` 已删除，消费者改用实际业务实现。
- `app/evidence/contracts.py` 提供纯的显式 EvidencePolicy；现有观测/结果对象继续使用，不新建重复结果体系。
- 通用 validator 消费显式策略的 matcher、来源描述及业务检查；Tool 的语义元数据归 `app/tools/evidence_descriptors.py`，通用 semantics 保留纯支持关系及未知语义的构造能力。
- 默认诊断通过 `app/bootstrap/evidence_assembly.py` 显式组合，不让通用 evidence 反向导入业务库或 bootstrap。
- EvidenceRequirement 是纯业务声明，归共享策略库；规划使用同一类型。未为了挪动类型让原本不需要 evidence 的隔离切片强制依赖整个 evidence 包。

依赖变化：业务规则到纯 evidence 实现为明确单向依赖；没有放宽整个 skills 格式/加载模块的拒绝边界。保留的 live-patch facade 新增一条到 evidence_assembly 的精确装配债务，归 MOD-027；总债务暂为 10（原 9），不能宣称债务归零。新增 6 个源码、删除旧 skill_policy，受管文件暂为 308。

可移植清单只补实际新增的依赖，不因工具 Profile 中未启用的 Skill 条件分支把整个 Skill 链装入工具切片；复制清单与负向拒绝清单分别处理，原拒绝控制保留。当前光刻切片 110 源码，发布切片 111 源码，tool_sources 保持 104。

验收：

| 范围 | 实际结果 |
| --- | --- |
| 116 项原证据/答案/Skill 定向 | 通过；未改变原测试的业务期望 |
| 定向加光刻/工具/发布切片、七单元、规划及边界测试 | Windows 149 项通过（12.408 秒） |
| 35 份完整验证报告、7 个领域与 7 个具名声明 | 起点导出树和当前树独立进程采集，JSON 逐字节一致 |
| check_module_boundaries / check_modularization_boundaries | 通过，308 文件、0 错误 |

完整对照使用忽略目录的 `mod031_equivalence.py`，包含七类请求的空证据、完整、blocked、部分和小样本五类场景；起点是独立旧实现，不是由新实现生成期望。证据为 equivalence-baseline.json / equivalence-current-b.json。后续新规则需另用手工期望断言，不能直接覆盖本次旧行为证据。

过程中保留的诊断：第一次自动扩展切片过度收集了旧条件分支，已按实际新增依赖收敛；发布切片计数曾写成 112，实际 111，修正数字后通过；错误的逻辑模块名称与新增精确装配边在检查器中被发现并修正/登记，没有跳过检查。原始运行记录保留于 runtime/quality/mod031。

## 031c：统一结果、宿主要求及版本规则

已在工作树落实以下变更：

- `assess_validation` 在唯一边界检查可信检查器返回的类型、版本、计划、枚举、覆盖计数/比例、检查项、风险及实际引用，再添加四个规范化字段。只允许 covered 全部满足、强度为 supported/supported_with_limits 且无 critical 风险/冲突时充分；未知 strong、伪造引用、非法计数、空义务都不能产生通过。检查异常使用稳定原因码，取消继续传播。
- 默认诊断明确绑定策略 2.0.0；Plan 已 ready 而必需策略丢失，返回 required_policy_missing。澄清 Plan 尚未激活诊断，报告 checked/plan_not_ready、充分性 null，保留澄清回答，不能误报检查故障。无可选策略为 not_configured/null。
- 光刻当前 Skill 2.0.0 / Workflow 3.0.0 / capability-evidence 2.0.0。旧 Workflow 2.1.0 固定旧策略 1.3.0；同一配置/发布库包含新旧版本时先解析请求的精确 Workflow，不从单一字典中被后注册版本覆盖。测试反转注册顺序、发布禁用及回退到旧版。
- 宿主要求来自可信 Workflow；删除清单中的 policy 在业务来源调用前失败。最小包、workflow-only、policy-only 的格式和已有受控执行资格仍分别判断，不新增通用 Skill Runner。
- 新策略 CAP-01/CAP-02 明确逐行；零、负数、布尔、字符串和非有限样本不能冒充有效样本。保留已有 30 的业务配置，不解释为普适统计充分性标准。
- 已知不同单位/规格版本且缺少独立生效窗时，报告可比较性未确认；同一口径限值冲突限制结论；明确合法的不交叠生效窗不误报。文档版本同样检查生效窗。未更改观测数据，未新增公司制度阈值。
- 真实知识焦点必须由返回元数据证明；knowledge 标签不能证明正式批准/生效。当前没有独立审批核验源，策略明确提示 document_status_unverified，不为通过补造批准字段。

旧 1.2/1.3 的检查配置保留真实消费者；新规则不是原地修改旧策略。`EvidenceValidation.enforced` 用于是否启用服务端答案约束，`evidence_sufficient` 用于充分性，两者不等价；旧手工构造对象仍可读，不把测试替身的强度当成检查器合法报告。

### 冻结期望的有界变更

没有重新录制整套 Golden。人工审阅后的变化仅有：

| 文件/输入 | 旧期望 | 新期望及独立依据 |
| --- | --- | --- |
| trace_replay_matrix：chain-cmp-capability | supported | hypothesis_only：原合成 knowledge 行只有 confidence/score，没有返回过滤焦点；CAP-01/02 有数据但 CAP-04 不计入。不增加合成来源证明来迁就新检查器。 |
| trace_replay_matrix：counterexample-explicit-sop | supported | insufficient：两组必需 SOP 证据均缺返回焦点证明，不能用模型请求参数代替来源证明。工具路径、作用域和事件字段未改。 |
| refactor_contract_v1：仅 chain-cmp-capability | 两个 answer_delta | 三个：上述缺口说明使离线回放文本跨越现有 120 字符分块边界；仅人工添加一个事件，未改 OpenAPI/DOM 或其他历史失败期望。 |

新增 `tests/test_evidence_policy_v2.py` 的手工边界示例独立断言 each_row、旧版对照、合法/空/拒绝、非法报告、检查异常/取消、样本、文档批准及冲突生效窗；不从实现自动生成期望。已有 Loop 37 场景黄金样本保持原文件，仍逐项比较。渲染单测中的旧版 fixture 明确使用 1.2.0，另用真实 2.0.0 案例断言新约束，不靠放宽生产规则兼容旧测试。

## 031d：编排、答案及真实 HTTP/SSE

默认 Coordinator、Ready、Loop、离线及光刻演示已消费同一规范化结果。覆盖齐全但仍有风险时可以结束收集，停止原因与“证据充分”分别表达；已有预算/权限/无进展优先级保留。检查失败在执行前或工具轮之后确定性结束，不再调用后续 Tool 或模型来补验。

现有 `answer_contract` 增加一个可空的 `evidence_policy_ref`，将已选精确版本带到答案边界，避免渲染时猜测版本；这是四个 evidence_validation 字段之外的必要内部/响应附加字段，外层 HTTP/SSE 键及 event 名、submit_analysis Schema 不变。历史记录不重写，缺新字段仍可读。2.0.0 受控诊断的未结构化断言省略原文；结构化提交中未支持的断言不回显到用户答案，逐声明审计保留原文和否决原因。可支持的直接观测仍可保留；普通无策略说明、模型通用知识披露及已有展示选择不被强制改成诊断章节。

新增 `execution/evidence_failure.py` 是 Loop 两个真实失败出口的确定性收口。首次故障路径发现 connection/检索元数据未初始化，已在既有状态准备和结果序列化所有者处补齐；去掉会使轻量 Runtime 拉入整个 synthesis 包的顶层导入，没有通过扩大所有历史切片规避隔离检查。

`service` 审计将 check_failed 记录为 outcome=degraded、degradation_stage=evidence_validation、稳定原因码和 restricted_answer。外层 status=success 仍表示请求完成，与既有上下文降级语义一致，不表示诊断合格；消费者应读取规范化报告。

新增四个测试方法加入既有 `tests/system/test_sessions_streaming.py`。实际经过 FastAPI HTTP/NDJSON、service/Coordinator、真实 Dispatcher、临时 SQLite、证据检查、答案约束和会话持久化；仅模型传输使用离线脚本网关。覆盖 Ready/Loop、两种轮后故障、非流式以及执行前故障共六条请求，再对每条重放同一 client_message_id，验证原 Run 缓存且不重跑。断言包括：

- 模型综合时 progress 为 null，原始未验证文本不进入增量；串联增量、最终 answer 与持久消息正文一致。
- 被否决的强断言不在用户答案，审计原文不冒充可见事实；错误不泄露模拟内部异常。
- 执行前故障的来源/模型调用为 0；轮后 Ready 不请求综合模型，Loop 只有原有选工具阶段，不再发起最终综合。
- 已执行 Tool 均真实返回；权限、来源和预算使用真实边界，不以 mock 调用次数替代结果断言。

四项 Windows、WSL 均已通过；实际取消/失败后状态隔离另由已有 runtime convergence、Loop cancel 和网关生命周期测试覆盖。没有新增真实模型、外网或公司接口调用，不宣称证明任意自然语言为真。

最终按源码重新统计系统模块为 77 项（13/15/13/21/15），起点已有 73 项，本轮增加会话 4 项；旧测试策略索引写的 70 项已经过期，已同步更正，不把旧统计差异算作本轮新增测试。

## 031e：阶段验证与交付

最终制品在 `runtime/quality/mod031/final-reviewed/`，build_id=mod031-final-reviewed：各使用平台解释器构建，在 Windows 临时目录与 WSL `/tmp` 的仓库外目录以 `-I` 运行交付验证器，tool_sources+skill_release 均 PASS（44 Tool 用例、Cpk 两模式、发布禁用、guard_events=0）。首轮未传 wheelhouse，model_transport 为 NOTRUN；后续发现并使用已有 `runtime/quality/mod-024-20261110-r1/wheelhouse`，两平台仅在新建临时 venv 离线安装锁定依赖，该 Profile 的 MockTransport 也 PASS，网络调用为 0，现有开发环境未安装/升级依赖。最终命令与结果为 final-reviewed/delivery-commands.json、release-win-acceptance.json、release-wsl-acceptance.json；首轮记录保留。

制品来自本轮未提交工作树；内含 git_commit=638f772 表示 checkout 基线，不是声称该提交已包含新实现。build_id 和成员内容对应本轮构建。正式提交/发布时应重新生成制品，不能把当前临时制品当作已发布的不可变提交批次。

最终清单：309 受管文件（281 Python + 28 静态）、10 精确债务、7 兼容入口/95 消费、30 DB 候选；Skill 资源 4，交付成员共 313。tool_sources=104、skill_release=111、model_transport=5；源码并集 153，加资源 157。新增文件有唯一归属，原负向控制未放宽。

完整回归与 full 门审计结果补于下文。四个工具描述/注册视图与 638f772 逐字节一致；两个边界检查器通过，309 文件、0 错误。验收阶段未连接真实服务；随后用户授权提交同步。

收尾人工审查还修正了两条批准语义：被否决的断言不能借建议依据、验证说明或 limitations 重新回显；规格数值相同但明确单位/版本不同，也不能误当作可比较。手工反例和真实 HTTP 结构化提交均覆盖，正常建议及受支持的直接观测仍保留。最终制品包含这两项修正。

### 最终验证记录

以下命令均使用前述隔离配置；命令完整参数、退出码与墙钟在同名 JSON，测试输出在同名 log。原始文件放在忽略目录 `runtime/quality/mod031/`，受跟踪结论为本报告；不能用子代理结论代替实际产物。本轮未使用协作代理。

| 命令/范围 | 实际结果 | 原始证据 |
| --- | --- | --- |
| Windows `python -m unittest discover -s tests -t .`，638f772 导出树 | 1449 项，12 失败、10 错误、4 跳过，310.301 秒 | baseline-full.log/json |
| 同命令，最终工作树（r4） | 1467 项，12 失败、10 错误、3 跳过，427.735 秒；与起点 22 个失败/错误标题集合完全相同，新增/消失均 0 | current-full-r4.log/json、final-failure-comparison.json |
| Windows 证据/答案/Trace/光刻六模块，最终规则 | 101 项通过，2.769 秒 | current-final-policy.log/json |
| Windows 四个新增 HTTP 方法 + answer_synthesizer/evidence_policy_v2/trace_replay | 84 项通过；后续扩充的辅助显示字段反例单项也通过 | current-d-http-final-r4、current-free-display-final-r2 |
| WSL 同一 HTTP/答案/策略/Trace 集合，Conda Python | 84 项通过 | http-wsl-final.log/json |
| WSL 七模块纯规则/Skill/仓库外切片/Trace，unit venv，最终规则 | 48 项通过，3.297 秒；该环境有 jsonschema，无 PIL | final-pure-wsl.log/json |
| WSL `python scripts/run_quality_gate.py full`，Conda Python | 非系统阶段 1346 项，7 失败、4 导入错误、2 跳过，483.424 秒；因失败停止，未运行后续覆盖率/系统模块/Node 等阶段 | full-wsl.log/json |
| WSL 同一 Conda 环境，起点与当前相关十模块 | 两树均 103 项、7 失败/4 导入错误；失败标题及 import 错误模块相同，无新增 | baseline-wsl-related、current-wsl-related、final-failure-comparison.json |
| Windows `python scripts/run_quality_gate.py full` | 在 coverage erase 停止：环境无 coverage；不是覆盖率达标或全量通过 | full-win.log/json |
| WSL `npm run test:e2e`，Node 22 + Conda + Chromium | 最终 17/17，58.8 秒；此前一轮 17/17，43.7 秒 | e2e-wsl-final.log/json、e2e-wsl.log |
| evaluate_playbooks / evaluate_ready_execution / evaluate_trace_replay | 分别 12/12、3/3、7/7，通过；未运行新的 1000×2 墙钟性能协议 | playbooks-final、ready-final、trace-final |
| 两端 build_module_release + 仓库外 verify_module_release，显式离线 wheelhouse | tool_sources+skill_release 与 model_transport 均 PASS；后者使用 MockTransport，网络调用 0 | final-reviewed/ |
| WSL 全仓 ruff，与起点同规则审计 | 240 → 239 个既有问题，按 code/message 多重集无新增；不是 lint 全绿。7 个新应用文件格式检查通过 | ruff-baseline.json、ruff-accepted.log |
| 四个 Tool 描述/注册视图对照 | 与 638f772 JSON 逐字节一致，未更新默认工具 Schema | catalog-baseline-e.json、catalog-current-e.json |

Windows 22 个既有失败/错误分组为：数据系统模块 4 失败；会话系统模块 1 失败/6 错误（含同方法三条回放子例）；context_resolver 1 失败；旧模块化行为基线/夹具时钟 3 失败；refactor_contracts 的 DOM/OpenAPI 2 失败；version_contract 1 失败；agent_assembly 1 错误；operational_reports_runtime 2 错误；personal_job_sse 1 错误。没有通过修改这些旧期望把它们变绿。

导出树未包含本地离线 wheelhouse，多跳过一项 model_transport 安装测试；工作树有该目录，最终实际执行该测试。两边失败集合仍作完整对照，不把跳过数不同隐去。WSL 四个导入错误均为缺少 jsonschema（capability_trend_tool、equipment_health_tool、skill_standard、tool_output_schemas）；在有 jsonschema 的 unit venv 运行相关 Skill/切片，完整 HTTP 链另在有 PIL 的 Conda 环境运行，不拼成“某个单一环境全量已绿”。

WSL full 在最后一条“等值规格、异单位/版本”修正前执行；该有界修正后，Windows 再跑最终全量 r4、WSL 再跑上述 48 项，并重建/实际验收最终两端制品。没有重跑已知会在缺依赖和既有失败处停止的 WSL full。最终完整覆盖率不可用，不引用历史 88%/89% 充当本次结果；未运行 Live、真实量化模型、公司来源或新的性能采样，远程 CI 未验证。

早期完整 r1 为 31 失败/21 错误，已保留：主要新增为轻量导入、旧替身新字段、澄清版本、切片计数及批准的新规则回放期望。修正后 r2/r3 均回到起点同名 12/10；r4 为最后有界修正后的完整审计。中间的 fixture/命令选择错误和所有失败原始记录同样保留，未改阈值、未将失败结果当通过。规则与答案有批准的行为变化，本轮不是整体零行为变化。

### 交付状态与剩余责任

031a～e 已完成，并按计划区分定向通过、基线可复现失败与环境未验证项；完整质量门仍未通过；本次按用户明确授权提交同步，不执行发布。保留 Playbook 规划视图的真实消费者为选择/Planner、提示及对外计划响应；只读规则类型/内容由共享业务库提供。保留 live-patch 门面是默认旧入口的实际消费者，精确装配债务归 MOD-027，不能宣称所有 Coordinator 或 Playbook 已退役。

用户无需在本项选择新的业务阈值或数据来源；当前没有待用户决定才能完成的实施分支。公司正式 SOP 审批/生效核验、目标量化模型效果、真实公司数据接入、持久发布和恢复不在本次完成主张内。MOD-029 继续暂缓，后续按 030/031 实施结果重审；产品统计 228/183/45 不变，模块化未完成 9 项。本版纳入 MOD-031 提交，提交号及远程同步结果以 Git 记录为准。

最终文本与链接复核：62 个修改/新增文件 UTF-8、LF、末尾单换行通过，151 个本地链接均可解析；顺带清理答案综合器原有的多余文件尾空行，仅文本卫生变化，最终制品已重建。check_repository、check_module_boundaries、check_modularization_boundaries（309 文件/0 错误）及 git diff --check 通过。
