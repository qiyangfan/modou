# ADR-0002：形态三位一体与开源许可证

- 状态：接受
- 日期：2026-10-14
- 依据：竞品形态分析（Atlas 已发 Claude Code 插件/Cursor skills、Bytebase 自带 MCP、
  Postgres MCP Pro 以单 server 拿 3.4k★）

## 决策

**一个内核，三种表面**：

- **CLI 为体**：确定性退出码承载 CI 卡点与审计留痕，运维终端里的交棒流程只有 CLI 能承载；
- **MCP 为原生面**：每个 MCP 工具与 CLI 子命令 1:1 映射，FastMCP 薄封装，零逻辑重复；
  2026 年开发者工具的分发入口是 agent 工具列表；
- **本地 Web 为薄报告层**：`modou ui` 起本机服务渲染 diff/EXPLAIN 报告，无登录无部署
  （lazygit 模式）。

三个否决：**否决 Web 平台**（Bytebase/DBdoctor 正面战场，平台引入成本恰是痛点根源）；
**否决纯 MCP**（无 CI 故事、无审计链路，发布门禁场景不可用）；**否决云 SaaS**
（敏感数据信任门槛，everSQL 已占商业位）。

许可证 **Apache-2.0**：与 Atlas 同款，含专利授权，对企业采用与潜在双许可路线最友好；
MIT 亦可但缺专利条款。

## 理由

- CI/审计要求确定性工具链 → CLI 不可替代；
- Agent 分发已被头部竞品验证（Atlas skills、Bytebase MCP）→ MCP 必须原生而非附属；
- 报告可视化是刚需但价值在渲染不在服务 → 薄层即可，一旦做厚就变成平台。

## 后果

- 所有业务逻辑必须落在内核库（src/modou/），CLI 与 MCP 只做参数解析与展示——
  表面层出现业务逻辑视为架构违规；
- CI 需为 ui 门禁预留 Node 家族标准版本位（家族 muniu/kongming web 门禁同用 Node 24）。
