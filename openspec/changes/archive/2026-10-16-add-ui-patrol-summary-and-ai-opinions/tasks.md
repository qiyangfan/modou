## 1. Python 侧

- [x] 1.1 测试先行：`patrol_summary` 报告过 kind/version 门禁（tests/ui/test_ui_server.py）
- [x] 1.2 `SUPPORTED_REPORTS` 收录 `patrol_summary: 1`

## 2. 前端

- [x] 2.1 测试先行：综合巡检视图 + AI 观点区渲染断言（ui/tests/views.test.ts）
- [x] 2.2 types.ts：`patrol_summary` kind、`AiOpinion` 与摘要信号类型
- [x] 2.3 views.ts：`renderPatrolSummary` + `renderAiOpinions`（无观点恒等），接入 renderReport

## 3. 同步与门禁

- [x] 3.1 docs/formats.md 报告 UI 识别口径补 patrol_summary；HANDOFF 未完成 #2 收口
- [x] 3.2 全门禁：uv ruff/pytest + ui npm test + openspec validate --strict
- [x] 3.3 真实浏览器走查：回环起服务加载 patrol_summary 与带观点的 verify 样例
