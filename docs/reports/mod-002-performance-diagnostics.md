# MOD-002 性能诊断边界（2026-10-22）

本报告记录离线验收的诊断观察和边界。2026-10-24 MOD-002 已按用户批准的配对协议验证通过，见 [基线报告](mod-002-behavior-baseline.md)；以下 r4/r5 的失败、v4 历史数字和相对容差保持不变。

## r4 时钟与亲和性观察

`runtime/quality/mod-002-20261022-r4/clock_diagnostic_1000.json` 的 Ready 计时区间中，wall-clock median/p95 为 8475518/12174082 ns，线程 CPU median/p95 为 7319783/8375576 ns，二者差值（off-CPU）median/p95 为 1099404/4502139 ns。Ready 的极端样本为 wall 24201291、CPU 7335973、off-CPU 16865318 ns；Loop 的极端样本为 wall 34650282、CPU 5564233、off-CPU 29086049 ns。

这些数值只能说明该诊断计时区间存在显著的线程未执行时间。它们不能归因于 Windows、WSL、GC、具体调度器或 I/O，也不能外推为生产环境结论。`affinity_paired_diagnostic.json` 的 200 对交替观察中，pinning 未改善结果，因此亲和性不是修复方案。

## 序列化优化的证据边界

`profile_diagnostic.json` 在受 profiler 扰动的观察中发现 Evidence/Answer 域重复序列化热点；它不是性能门证据。随后 r5 的 `serialization_ready_paired_microbenchmark.json` 在真实 Runtime Ready 对象上做了 10 次 warmup、1000 次 old/new 交替的 CPU-only 观察：

- `EvidenceValidation`: 218317 → 125078 ns
- `AnswerContract`: 171148 → 98119 ns
- `AnswerSynthesisReport`: 24332 → 15808 ns

这只支持局部 CPU 成本降低，不能抵消墙钟硬门失败，也不构成应用提速、生产 SLO 或生产尾延迟声明。较早的 `serialization_paired_microbenchmark.json` 只捕获了第一个 policy replay 对象，不能用作 Ready 计量证据。

## 当前结论

r5 三次预先声明的正式 compare 均失败：Loop 的 p95 每次都超过冻结上限，第一次 Knowledge 的 p95 也超过上限；Ready 三次均通过。该历史静态结果保持不变。2026-10-24，两次预声明的同轮 reference/current 正式比较 A/B 均通过，wall median/p95 使用原固定相对容差，CPU 与 cleanup 仍只辅助观察。它不证明旧静态门通过或全部调度噪声已被定位/消除，完整样本与数值见基线报告。

另发现的跨日行为漂移已通过历史输入时钟控制修正，冻结 v2 与 ZIP 未改、未增加输出归一化。该行为夹具修复与 r4/r5 的墙钟尾延迟诊断是两件事，不相互充当因果解释。
