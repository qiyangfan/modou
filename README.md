# Modou · 墨斗

> 「木受绳则直」——墨斗弹线，规矩之始。线弹于施工之前，墨迹留于木料之上：
> 工匠照线施工，工头对线验收，墨痕即存档。数据库的变更与优化，缺的正是这条线。
> **Draw the line. Keep the proof.**

墨斗是数据库工程化的本地层：**变更验收 · SQL 优化 · 规则审核 · 漂移洞察**。
它不改造你的发布流程、不部署平台、不接管数据库——只在开发与运维的交棒处画线取证，
让每一个结论（schema 是否一致、索引是否有效）都由数据库回放实证给出，而非人眼或猜测。

🚧 当前处于立项阶段（2026-10-14）：定位与架构定稿（见 [docs/architecture.md](docs/architecture.md)），
首步为两条核心链路的原型真值验证（见 [docs/HANDOFF.md](docs/HANDOFF.md)）。

## 为什么是墨斗

两个真实的痛点：

1. **交棒漏执行**：线上 SQL 由运维代执行，一次开发几十条小 SQL，逐条执行繁琐，
   合并执行易漏，且漏了无人知晓——没有任何机器验收手段。
2. **优化无证据**：SQL 优化（索引建议等）靠经验与文章，建议是否真的有效，
   没有人在真实数据规模上实证过。

墨斗对这两件事的回答是同一条方法论：**用影子库回放推导期望态，让数据库自己出证据**。
这套基建一旦就位，审核与洞察两条车道复用同一内核，边际成本递减。

## 四条车道

| 车道 | 命令域 | 解决什么 |
|---|---|---|
| 变更验收 | `pack` / `verify` | 变更集打包防漏 → 运维执行前后快照 → 三方 diff 验收 |
| SQL 优化 | `optimize` | 采集执行计划 → 规则初筛 → AI 诊断 → 影子库建索引实测复核 |
| 规则审核 | `lint` | SQL 反模式规则库（pre-commit / mapper 批量扫描），规则可社区共建 |
| 漂移洞察 | `patrol` | 定时漂移 diff、未用索引检测、慢日志指纹聚合、DDL 锁风险与 gh-ost/pt-osc 建议 |

## 三种形态，一个内核

- **CLI 是本体**：CI 卡点、审计留痕（确定性退出码）、运维终端里的交棒流程；
- **MCP 是原生表面**：每个 MCP 工具与 CLI 子命令 1:1 映射，任何 agent（孔明、ZCode、Cursor）可调用；
- **本地 Web 是薄报告层**：`modou ui` 起本机服务渲染 diff/EXPLAIN 报告，无登录无部署（lazygit 模式）。

明确否决：需要部署的 Web 平台（那是 Bytebase/DBdoctor 的正面战场）、纯 MCP 工具（无 CI 与审计故事）、
云 SaaS（schema 与真实 SQL 是高敏数据，信任红利在本地）。

## 设计原则（不可协商）

1. **确定性代码当裁判，AI 只当顾问**：schema 是否一致、建议是否有效，由代码与数据库实证裁决；
   AI 负责解释与生成建议，每条建议必须通过影子库实测复核才允许进入报告。
2. **回放推导，不靠解析拼终态**：期望态由真实 MySQL 回放变更集得出，DDL 解析只做预警不做结论。
3. **默认多实例多库**：多库/多 schema 是常态假设而非特例。

## 治理

| 文件 | 职责 |
|---|---|
| [openspec/project.md](openspec/project.md) | 宪法：不可协商红线与工程口径 |
| [docs/goals.md](docs/goals.md) | 目标体系与里程碑验收判据 |
| [docs/architecture.md](docs/architecture.md) | 架构北极星：内核三件套、模块地图、风险 |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR-0001~0008） |
| [AGENTS.md](AGENTS.md) | 工作区指引：目录、门禁命令、代码规范 |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | CI：Python 内核门禁 + ui 门禁（Node 24 预留位） |

## 家族

隆中家族成员：[kongming](../kongming)（孔明，AI Agent——墨斗是其数据库工程化的工具面）·
[muniu](../muniu)（木牛，模型网关）· [sunmao](../sunmao)（榫卯，插件治理——哲学同源：
榫卯管"接得上"，墨斗管"对得齐"）· [jinguan](../jinguan)（锦官）· [siku](../siku)（四库）。

## 技术栈

Python 3.12+ · uv · sqlglot（解析）· testcontainers/podman（影子库）· FastMCP（Agent 接入）。
版本线与依赖以 [pyproject.toml](pyproject.toml) 为准。

## 路线图

| 版本 | 范围 | 验收标准 |
|---|---|---|
| v0.1 | 变更车道：打包 + 影子回放 + 三方 diff（仅 MySQL） | 真实迭代目录产出的验收报告能抓到人工构造的漏执行 |
| v0.2 | 优化车道：采集 + 规则 + AI 诊断 + 实证闭环 | 每条索引建议带"影子库实测提升 X%"标注或明确标"未验证" |
| v0.3 | MCP server + CI 示例 | agent 一句话完成"校验这个变更集并优化里面的慢 SQL" |
| v0.4 | 审核车道 + 洞察车道 + 本地报告 UI | 规则库开放共建；漂移巡检定时化 |

## License

[Apache-2.0](LICENSE)
