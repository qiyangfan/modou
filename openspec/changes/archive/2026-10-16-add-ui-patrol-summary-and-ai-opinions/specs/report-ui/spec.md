## ADDED Requirements

### Requirement: 综合巡检与 AI 观点区渲染

报告界面 SHALL 渲染综合巡检报告（report_kind=patrol_summary）：逐信号摘要
（漂移 / 未用索引 / 慢日志）、摘要内对象与指纹清单、输入来源映射。报告数据含
`ai_opinions` 观点数组时 SHALL 渲染单列「AI 观点」区，逐条展示车道、主题、
来源模型，降级条目 SHALL 展示降级原因；观点区 SHALL 标注「模型输出·未经实证·
不影响退出码」与确定性结论分级。报告数据无该字段或为空数组 SHALL 不渲染观点区。

#### Scenario: 渲染综合巡检报告

- **GIVEN** 一份 patrol_summary 报告文件
- **WHEN** 用户在报告界面打开
- **THEN** 展示三信号摘要与清单，并列明各信号的输入来源

#### Scenario: 渲染 AI 观点区

- **GIVEN** 一份数据中带非空 ai_opinions 数组的报告
- **WHEN** 渲染该报告
- **THEN** 观点单列展示，逐条附车道、主题与来源模型，降级条目展示降级原因

#### Scenario: 无观点不渲染

- **GIVEN** 一份数据中无 ai_opinions 字段或其为空数组的报告
- **WHEN** 渲染该报告
- **THEN** 页面不出现观点区
