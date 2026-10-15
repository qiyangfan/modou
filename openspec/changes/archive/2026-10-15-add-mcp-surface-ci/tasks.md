# 任务：v0.3 MCP 表面 + CI 集成

## 1. 表面骨架

- [x] 可选依赖组 `mcp`（框架锁版本）；未安装时 `modou mcp` 退出码 2 + 安装指引
- [x] MCP server 骨架：stdio 拉起、版本信息透出、错误细节遮蔽配置

## 2. 工具 1:1 映射

- [x] 测试先行：parity 校验——工具名集合与分析类子命令集合一致（显式排除清单驱动）
- [x] pack / verify 工具封装：参数一致、返回同源结构化报告 + 退出码语义字段
- [x] snapshot capture / optimize / version 工具封装（同口径）
- [x] 错误翻译：内核异常 → 工具错误（英文），断言无堆栈泄漏
- [x] 工具描述与 CLI help 同源校验（防两表面语义漂移）

## 3. 演示链路

- [x] fixture：样例变更集 + 预采集前后快照 + 慢 SQL 文件（免生产库可复现）
- [x] 脚本化 MCP client 冒烟测试：单会话闭环 pack → verify → optimize
- [x] agent 演示文档（一句话任务书 + 逐步调用记录 + 汇总答句），实证记录入 HANDOFF

## 4. CI 集成示例

- [x] GitHub Actions 示例 workflow：PR 跑 pack 预警 + 摘要回贴（纯静态命令）
- [x] 示例文档：使用说明 + 数据红线声明（验收类命令禁入托管 CI）
- [x] 门禁回归：全量 ruff format/check + pytest + CLI 冒烟全绿
