# 测试质量 TODO

本文件仅维护未完成任务和未激活的可选候选。已完成 9 项，定义与验收见[归档](archive/testing-quality.md)；[完成索引](completed.md)。

## 用户暂缓

- [ ] `QA-010` 将双通道 E2E 纳入可治理质量门：普通 push/PR 继续执行零外网、零真实模型的确定性 full；本地已新增仅 `workflow_dispatch` 的受保护 Live workflow、必填模型 ID、Environment Secret 接口、完整 `full` target 和版本化调用/Token/启动/单测/总耗时硬预算，环境 override 仅能收紧。Live 成功必须同时满足 Provider 调用、模型身份、无降级、流式完成、Session/Trace 一致和凭据/隐藏推理泄漏检查，供应商不可用不得伪装成功；artifact 只上传 metadata-only 报告，不上传正文、请求体、Playwright 报告、数据库或日志。`provider-matrix` 仅作必要/诊断，不能替代发布或标签前对目标 commit 手动运行的完整 7-run 门；本地故障夹具、确定性门与 Provider 门分别统计。2026-09-04 本地完整 Live 通过：浏览器 3/3、runs 7/7、calls 18、input/output/total=72538/19260/91798，startup=38448.0ms、test=273198.9ms、duration=312451.1ms，fallback/degraded=0。2026-09-05 用户暂缓远程 `live-e2e` Environment、Secret 与完整 workflow 验收；私有仓库 required reviewer API 返回 422，未将其替代为自审或宣称远程通过。本项保持未完成，发布或打标签前仍必须完成目标 commit 的远程完整 Live 门。依赖：`QA-005` 至 `QA-009`、`DEPLOY-012`。
