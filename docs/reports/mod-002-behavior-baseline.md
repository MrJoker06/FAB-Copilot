# MOD-002 行为与性能基线报告

状态：已验证（2026-10-24，用户批准的同轮配对协议）。r1～r5 的历史静态失败完整保留，不改写为通过；当前结论以本节 2026-10-24 结果为准，`MOD-003` 的基线前置已满足。

## 2026-10-24 配对验收收口

参考为 `evaluations/mod_002_reference_v4.zip`，协议为 `evaluations/mod_002_paired_protocol_v1.json`。主审核对原 ZIP 的全部 174 个成员与固定 Git 基线/已审查覆盖文件及原始夹具逐字节一致，模式均为普通 100644；没有使用内容哈希或重建 ZIP。当前 harness 增加时钟输入控制后，ZIP 内原始夹具仍保持不变。

本轮原先有两个行为测试跨日失败：系统提示词在导入时取得宿主日期，policy replay 的部分嵌套路由默认值也泄漏宿主日期。原行为 v2 实际含业务路由日期 `2026-08-07` 和捕获环境日期 `2026-10-22`，此前未完全固定后者。新增 `scripts/modularization_fixture_clock.py` 在执行前固定这两个历史输入；不删除日期、计划 ID 或业务字段，不增加输出归一化，不改变生产日期获取逻辑。模拟宿主日期 2026-10-24/2099-01-01 的测试精确匹配原 v2，而提示词非日期正文变化仍会报差异。这不是将两个历史时钟统一为一个日期，也不解释 r1～r5 的性能失败原因。

主审的 75 项定向测试、Ruff 和真实隔离 `--observe --samples 2` 通过。观察报告 `runtime/quality/mod-002-20261024-r1/observe.json` 中，reference/current 都精确匹配未修改的 behavior v2，环境一致，所有应用模块来自各自 `/tmp` 目录，环境文件为 `/dev/null`，网络/数据库访问计数为零，临时目录已清理。该观察不计作正式性能通过；完成来源/行为审查后，才批准 reference sidecar。

完整门 `python scripts/run_quality_gate.py full` 实际 exit 0，日志为 `runtime/quality/mod-002-20261024-r1/full-gate.log`：Python 758 项（688 非系统项，85.758 秒；70 系统项，总耗时 88.855069164 秒），coverage 89%；Node 61、RAG 15、OCR 8、Playbook 12、Ready 3、Trace 7；Playwright 17/17，41.5 秒。随后只调整了 legacy baseline CLI 的 helper 导入顺序，修复清除 `PYTHONPATH` 时直接启动失败；未改业务或计时逻辑。仓库外 `python -I <absolute script> --help` 回归与主审全部 76 项定向测试再通过（6.786 秒）。

两次正式比较 A/B 的路径、1000×2 样本及“不追加重试挑成功”策略在采样前写入 v4 record。双方使用独立临时树、同一冻结夹具、每批 10 warmup、50 样本 AB/BA 块；参考和当前共 24,000 个正式墙钟样本，每轮 120 个块。A/B 均实际 exit 0，主审独立按原始样本重算整数 median/nearest-rank p95，并用原固定容差 15.65%/16.36%/15.64% 核对通过；CPU/cleanup 仅观察。

| 轮次/场景 | 参考 median / p95（ns） | 当前 median / p95（ns） | 结果 |
| --- | --- | --- | --- |
| A Ready | 7333512 / 8462922 | 6703274 / 7678095 | 通过 |
| A Loop | 5107012 / 5902671 | 5055390 / 5746667 | 通过 |
| A Knowledge | 4622757 / 5334224 | 4580181 / 5275320 | 通过 |
| B Ready | 7220823 / 8100461 | 6550970 / 7317110 | 通过 |
| B Loop | 5099476 / 6075160 | 5051951 / 6179137 | 通过 |
| B Knowledge | 4610996 / 5505525 | 4592982 / 5544712 | 通过 |

正式报告为 `runtime/quality/mod-002-20261024-r1/paired_formal_A.json` 和 `paired_formal_B.json`；双方 behavior baseline diffs 及相互 diff 均为空，临时树已清理。当前正式入口为 `python scripts/modularization_paired_baseline.py --samples 1000 --report <new-path>`；旧 `modularization_baseline.py` 的静态数字比较不充当当前正式门。

这只证明已批准的离线回归协议通过，不证明生产 SLO、生产尾延迟、全部调度噪声已解决或公司数据已接入。以下 r1～r5 及 2026-10-22 的未完成状态均为历史记录，不追溯改写；冻结行为 v2、原 v4 性能数字和旧失败报告继续保留。

## 当前冻结工件

- 行为：`evaluations/mod_002_behavior_baseline_v2.json`
- 性能：`evaluations/mod_002_performance_baseline_v4.json`
- 冻结记录：`evaluations/mod_002_baseline_record_v4.json`

记录日期为 2026-10-22，构建 ID 为 `mod-002-20261022-r3`，父提交为 `0c93cf6075e181caf1e61dfbcc6c616ff3a0f7e4`。冻结记录标明当时工作树为 dirty；该说明只用于溯源，并不枚举或代表全部本地改动。候选及两次独立 validation A/B 均使用固定 candidate 容差并通过；它们不替代随后失败的正式默认 compare。

行为夹具走真实 `_run_agent_impl` 离线路径，固定日期并阻断网络、数据库和真实模型调用。它覆盖 Ready 成功/依赖失败、Loop 成功/重复阻断，以及 general-knowledge 检索成功和空结果降级。`answer_contract` 的键序规范化仅作用于 system `model_messages` 中精确标记后的合法 JSON object；前缀、用户消息、数组、畸形 JSON 和其他业务字段均保留，以免隐藏真实漂移。`PYTHONHASHSEED=0` 的 capture 与 `PYTHONHASHSEED=1` 的只读 compare 已通过；主审原 33 项定向测试加冻结漂移测试共 34 项通过。

## 性能解释与可比性

性能冻结的是本机离线热 Runtime 夹具回归门，不是生产 SLO，也不说明生产尾延迟。计时区域仅为 fixture patch 后的 `_run_agent_impl`，包含 Runtime HTTP-client 构造、mocked request 和 progress recording。没有外部网络、真实模型或数据库调用。

`cold_import` 未测量；`first_run_ns` 只是本夹具采样序列的第一轮，不是新进程冷导入。每个场景有 10 次 warmup、每批 1000 个样本、2 批；30×1 只可作 observation，不能充当 approved gate。schema 1.3 在离线 fixture 内排除代理环境，并在每次 fixture sample 前执行 `gc.collect()`，同时保持 Runtime 内自动 GC 开启。清理耗时和回收对象数单独保留为非门控观察，不能当作生产总耗时。环境中记录 Python、实现、OS、machine、node、httpx、代理和 GC 策略；协议不同即不可直接比较。

`relative_allowance_pct` 是 15 个百分点的政策余量加观测到的 batch spread，不声称完全由噪声推导，也未在冻结或 validation 时放宽。v4 候选中 `ready_success`、`loop_success`、`knowledge_retrieval_success` 的 median 分别为 8595994、6139216、5692488 ns，p95 分别为 10384311、7919892、7471287 ns，固定容差分别为 15.65%、16.36%、15.64%。两次独立 validation 均在这些固定 candidate 容差内通过。该结果只适用于受控离线协议，不代表应用提速、生产 SLO 或生产尾延迟。

## 历史记录、完整门与最终默认 compare

`evaluations/mod_002_behavior_baseline_v1.json` 与 `evaluations/mod_002_performance_baseline_v1.json` 是未通过主审的历史记录，不作为默认 compare 或验收依据。v1 的日期、知识检索路径和计时边界不满足 v2 要求。

2026-10-22 已真实执行完整门并以 exit 0 通过：

```bash
env PATH=/home/zackzhang/miniconda3/envs/fab-insight-agent/bin:/usr/local/bin:/usr/bin:/bin \
  python scripts/run_quality_gate.py full
```

日志为 `runtime/quality/mod-002-20261022-r1/full-gate.log`。Python 为 704 项（634 非系统项，72.736 秒；70 系统项，分组为 13/15/14/17/11，总计 90.965349185 秒），coverage 89%；Node 61/61、RAG 15/15、OCR 8/8、Playbook 12/12、Ready 3/3、Trace 7/7；Playwright 17/17，49.6 秒。桌面旅程使用已批准的同步调整：在 ETCH 操作前等待首个非 ETCH capability 请求获得 200、事件完成且 UI 不 busy，避免正常取消旧请求被 failure monitor 误报；生产代码和 monitor 断言未放宽。

但随后正式默认命令 `python scripts/modularization_baseline.py` 以 exit 1 结束。行为 compare 通过；性能 compare 只在 `ready_success.p95_ns` 失败：实际 median 17.308425 ms、p95 28.440304 ms，冻结 p95 为 21.407736 ms，固定 17.54% 容差的上限为 25.1626528944 ms；两批 p95 为 26.061923/28.546614 ms。Loop、knowledge 和全部 median 均通过。保留的独立 validation 仍在原固定容差内通过，但不能替代这次正式 200×2 失败；全局报告已原样保存为 `runtime/quality/mod-002-20261022-r1/final_comparison_report.json`。r2 的仅代理隔离 V3 候选及两次 validation 均失败，保留为未批准历史。

最初保留 capture 返回对象的诊断不作为正式证据；经主审核对的配对诊断才支持在每次 fixture sample 前控制 GC 初始条件。该控制不丢弃 GC 成本，也不构成业务优化。

schema 1.3 的完整门已以 exit 0 通过，日志为 `runtime/quality/mod-002-20261022-r3/full-gate.log`：Python 709 项（639 非系统项，71.235 秒；70 系统项，分组 13/15/14/17/11，总计 84.315168941 秒），coverage 89%；Node 61、RAG 15、OCR 8、Playbook 12、Ready 3、Trace 7；Playwright 17/17，43.7 秒。

但正式默认 `python scripts/modularization_baseline.py` 以 exit 1 结束，报告为 `runtime/quality/mod-002-20261022-r3/final_comparison_report.json`。行为 compare 通过；仅 `ready_success.p95_ns` 失败：实际 12024663 ns，高于冻结 p95 10384311 ns 在 15.65% 固定容差下的 12009455 ns 上限 15208 ns；同场景 median 9335950 ns 通过，Loop/Knowledge 的全部 median/p95 也通过。A/B 的固定容差成功不能替代该最终正式失败。

失败轮的三个场景 Runtime median 相比候选分别高 8.61%、10.69%、12.66%，非计时 cleanup median 分别高 9.20%、9.98%、10.28%，提示普遍环境或运行成本漂移，但不证明具体原因。主审当前可见的 `ps`/`ss` 进程与端口范围内未发现遗留 Python、Node、Playwright 测试服务或 8899 listener；这不是完整宿主或外部负载排查，因此不能归咎 WSL、GC 或热降频。稳定性尚未解决，v4 不重校准，MOD-002 不完成、MOD-003 不放行。

随后 r5 完整质量门也以 exit 0 通过，日志为 `runtime/quality/mod-002-20261022-r5/full-gate.log`：Python 714 项（644 非系统项，71.966 秒；70 系统项，分组 13/15/14/17/11，总计 83.110282274 秒），coverage 89%；Node 61、RAG 15、OCR 8、Playbook 12、Ready 3、Trace 7；Playwright 17/17，44.0 秒。输出/独立副本 oracle、冻结行为 v2 与主审独立的 103 项测试也均通过（19.011 秒），但这些结构与行为证据不替代性能门。

r5 在不改动 v4 冻结数字、容差或协议的前提下执行三次预先声明的正式 compare，三次都以 exit 1 结束而行为 compare 均通过。冻结 p95 上限为 Ready 12009455.6715 ns、Loop 9215586.3312 ns、Knowledge 8639796.2868 ns。三次实际值依次为：Ready p95 10810712/9973540/10502247 ns（均通过）；Loop p95 9942433/9658678/9667516 ns（均失败）；Knowledge p95 9916747/8117430/8174931 ns（第一次失败、后两次通过）。对应 median 依次为 Ready 8419447/8214352/8463712 ns、Loop 6800018/6584792/6752001 ns、Knowledge 6271997/6159944/6250402 ns。局部序列化 CPU 优化没有抵消这些墙钟失败；详情与归因边界见 [性能诊断](mod-002-performance-diagnostics.md)。

用户当前只允许现有 WSL 环境。2026-10-22 用户已批准同轮可执行的 reference/current 配对 wall-clock 比较：reference ZIP、sidecar 与 protocol 已生成为 candidate；旧 r1–r5 静态结果完整保留，且不改写为 passed。新门不再把历史静态绝对 p95 数字作为当前正式门，而固定保留 v4 的相对容差 Ready 15.65%、Loop 16.36%、Knowledge 15.64%。双方将在独立临时 WSL tree 中使用完全相同的冻结 fixture；每场景 1000×2、每批 10 warmup、50 样本 AB/BA 交替块，wall-clock median 与 p95 是硬门，thread/process CPU 与 cleanup 仅作观察。runner 尚在开发，尚未 observe、未完成 reference 的 behavior v2 审批或任何 formal。后续需先 observe 核对隔离与完整 behavior v2，审批 metadata 后执行完整离线门及两次预先声明 formal；两次均通过才完成 MOD-002 并自动继续 MOD-003，任次失败均保留。

可移植单元校验命令 `python scripts/build_portable_unit.py --verify --output-dir runtime/portable/mod-002-20261022-r5` 已通过：7 个单元通过，`decision_core-1.0.1.zip` 包含该序列化 helper，其余 6 个仍为 1.0.0，所有新 ZIP 成员均为普通 100644 模式。此结构校验同样不替代失败的性能门。
