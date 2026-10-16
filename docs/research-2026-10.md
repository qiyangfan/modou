# 竞品调研事实库（2026-10-14，2026-10-16 增补 OCR）

> 立项依据的调研数据与结论。星数与维护状态为 2026-10-14 实测快照，引用前可复核；
> 2026-10-16 增补节单独标注。

## 赛道地图

| 车道 | 玩家 | 形态 |
|---|---|---|
| A 迁移管理 | Atlas / Flyway / Liquibase / Skeema | CLI/lib |
| B SQL 审核平台 | Bytebase / Archery / Yearning / SQLE / goInception / DBdoctor | Web 平台 |
| C SQL 优化 | SOAR / SQLAdvisor（双停滞）、everSQL（闭源 SaaS）、Postgres MCP Pro | CLI / SaaS / MCP |
| D AI×DB | WrenAI / Vanna / DB-GPT | BI 引擎（相邻，不同问题域） |

## 关键数据

| 项目 | 数据 | 要点 |
|---|---|---|
| Atlas (ariga/atlas) | 8.8k★，Apache-2.0 | 声明式+版本化迁移；15+ 数据库；16 ORM 加载器；50+ 迁移 lint；漂移检测；K8s Operator；**已出 Claude Code 插件与 Cursor/Codex skills**。前提是"工具自己连库执行" |
| Bytebase | 14.6k★，开源+企业双许可，Docker/K8s | 200+ 审核规则、审批流、RBAC、脱敏、漂移异常检测、自带 MCP。引入成本=上一个平台 |
| Skeema | v1.12（2024-07），MySQL/MariaDB | execute-and-introspect 式 diff（与本仓裁决 2 同思路）；gh-ost/pt-osc 集成；需直连推送 |
| Flyway / Liquibase | JVM | 漂移检测在付费档；Liquibase 社区版 diff 仅纯文本输出（官方文档确认）。同样假设工具直连 |
| SOAR (XiaoMi/soar) | 8.8k★，**事实停滞** | 启发式改写+索引建议+EXPLAIN 分析+同表 ALTER 合并。**注意：小米出品，此前误记为搜狐，已更正**。继承人空缺 |
| SQLAdvisor (美团) | 停滞 | 索引建议 |
| Postgres MCP Pro (crystaldba) | 3.4k★，MIT，仅 PG | DTA Anytime 算法 + HypoPG 假想索引实证 + pg_stat_statements 工作负载分析 + 实验性 LLM 调优。"AI 建议+实证"在 PG 侧的完整实现 |
| Yearning | 活跃，Go，仅 MySQL | 轻量工单平台；已内置 AI 助手（优化建议+text-to-SQL）；自动回滚语句生成 |
| Archery (hhyo) | 活跃，Python | 审核依赖 goInception；查询/执行/备份/慢日志全家桶 |
| DBdoctor | 开源+商业，2025-2026 上升 | eBPF 内核采集+外置 Cost 优化器；慢 SQL 指纹聚合自动审核；信通院认证（2025-12）；平台形态 |
| everSQL / Aiven / Releem | 闭源 SaaS | everSQL 自称 10 万+工程师使用；开源侧 AI 优化位置是空的 |
| WrenAI (Canner) | ~17.8k★ | GenBI/text-to-SQL；证明"开源×AI×数据库"社区热情 |
| pt-osc / gh-ost | 持续维护 | 大表在线变更执行层，集成对象非对手 |
| Open Code Review (alibaba) | 2026-06 开源，Apache-2.0 | AI 代码评审 CLI：确定性工程 × LLM Agent 混合架构（详见下方增补节）；delegation 模式零密钥可用；Claude Code/Cursor/Codex 插件矩阵 + MCP server |

## 四个交叉空白（立项依据）

1. **交棒验收闭环全行业空白**：迁移工具假设"工具自己执行"，平台假设"改用平台执行"；
   没人给"开发交 SQL→运维代执行"的既有流程做打包防漏+执行后机器验收。
2. **AI 建议实证闭环：PG 已占、MySQL 空白**；且没人把影子库基建在变更验证与索引调优间复用。
3. **本地优先+Agent 原生"轻端"没人做全**：平台重部署，CLI 无 Agent 入口（Atlas 刚开始补）。
4. **MySQL 生态现代化规则引擎无人继承**：SOAR 8.8k★停更，Bytebase 规则锁在平台里。

## 增补：AI 代码评审赛道（2026-10-16 实测）

alibaba/open-code-review（OCR，源自阿里内部官方 AI 评审助手，服务数万开发者两年）
开源后成为"确定性工程 × AI"的方法论参照，是 ADR-0009 的外部依据：

- **硬约束层（确定性代码）**：精确文件选择（不漏审）、智能分包（关联文件成组、
  每组独立上下文子评审、天然并发）、模板引擎细粒度规则匹配（模型注意力聚焦、
  源头消噪）、独立定位与反思模块（修行号漂移与内容失准）；
- **Agent 层（动态判断）**：场景化提示词、从生产调用轨迹蒸馏的专用工具集、
  可读完整文件与检索代码库（超出 diff 表面反馈）；
- **实证数据**：同一底层模型 vs 通用 Agent（Claude Code），精度与 F1 更高、
  token 约 1/9、更快；recall 刻意让位 precision（宁缺勿噪）；
- **核心论断**：纯语言驱动缺硬约束——覆盖不全、位置漂移、质量不稳；静态规则
  存在边际效益递减，长尾判断交给模型。

对 modou 的定位意义：OCR 证明了"确定性供证据、模型做判断"的工程学（省 token、
保精度、可审计）；modou 比 OCR 多出影子库——AI 意见可**实测**而非仅自检，
"AI 赋能 × 机器证据"在数据库工程化车道无人做（ADR-0009 决策依据）。

## 命名占用核查（2026-10-14 实测）

- `sqlproof`：PyPI **已占用**（HTTP 200）；GitHub 有同名小项目（★6，SQL property-based testing）。出局。
- `kaogong`：GitHub 前五全部是"考公备考"生态（最高 ★782）——词义已被劫持。出局。
- `modou`：GitHub 仅 2013 年休眠豆瓣客户端（★18）与"魔豆路由器"文档，无冲突；PyPI 可注册（404）。**选定**。
