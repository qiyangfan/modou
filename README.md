# Modou · 墨斗

> 「木受绳则直」——墨斗弹线，规矩之始。线弹于施工之前，墨迹留于木料之上：
> 工匠照线施工，工头对线验收，墨痕即存档。数据库的变更与优化，缺的正是这条线。
> **Draw the line. Keep the proof.**

[English](README.en.md) | 简体中文

墨斗是数据库工程化的本地层：**变更验收 · SQL 优化 · 规则审核 · 漂移洞察**。
它不改造你的发布流程、不部署平台、不接管数据库——只在开发与运维的交棒处画线取证，
让每一个结论（schema 是否一致、索引是否有效）都由数据库回放实证给出，而非人眼或猜测。

**v1.0 已定版**：四条车道全部落地，结论分级（确定性实证 + AI 观点单列），零平台化、
数据不出本地（AI 分析为 BYOK 自带密钥，未配置时零网络请求）。

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
| 变更验收 | `pack` / `verify` | 变更集打包防漏 → 运维执行前后快照 → 三方 diff 验收（漏执行/错执行/历史漂移） |
| SQL 优化 | `optimize` | 采集执行计划 → 影子库建索引实测 → 每条建议带「实测提升 X%」或明确标「未验证」 |
| 规则审核 | `lint` | 26 条 SQL 反模式静态规则（SOAR 子集，零数据库零网络），pre-commit / mapper 批量扫描 |
| 漂移洞察 | `patrol` | 漂移 diff、未用索引分层判定、慢日志指纹聚合、DDL 锁风险与 gh-ost/pt-osc 建议 |

两个端到端案例（含真实命令输出）：[变更交棒漏执行验收](examples/changeset-demo/) ·
[索引优化实证](examples/optimize-demo/)。

## 安装

```bash
# PyPI（推荐，要求 Python 3.12+）
uv tool install modou

# 或用 uvx 直接试用
uvx modou --help

# 或从源码
git clone <repo> && cd modou && uv sync && uv run modou --help
```

MCP 表面（接入 Claude Code / Cursor 等宿主 Agent）与 AI 委托工作流见
[docs/demo-agent.md](docs/demo-agent.md)；BYOK 三元组（`MOUDO_AI_BASE_URL` /
`MOUDO_AI_API_KEY` / `MOUDO_AI_MODEL`）不配置时零网络请求。

## 五分钟上手

```bash
# 运维执行前：只读快照
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 -o before.json

# 开发侧：变更集打包 + 破坏性预警
modou pack examples/changeset-demo -o packed.sql

# ……运维执行 packed.sql ……

# 运维执行后：只读快照
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 -o after.json

# 验收：三方 diff，退出码 0=一致 / 1=有差异 / 2=环境或输入错误
modou verify examples/changeset-demo --baseline before.json --after after.json \
    --default-database 库名 --report-json report.json

# 本机浏览器看报告（仅 localhost，无登录无部署）
modou ui --report report.json
```

完整说明见 [docs/quickstart.md](docs/quickstart.md)。

## 三种形态，一个内核

- **CLI 是本体**：CI 卡点、审计留痕（确定性退出码）、运维终端里的交棒流程；
- **MCP 是原生表面**：每个 MCP 工具与 CLI 子命令 1:1 映射（parity 测试守护），
  任何宿主 Agent 可调用；证据原语工具扩列见 [docs/demo-agent.md](docs/demo-agent.md)；
- **本地 Web 是薄报告层**：`modou ui` 起本机服务渲染报告，无登录无部署（lazygit 模式）。

明确否决：需要部署的 Web 平台（那是 Bytebase/DBdoctor 的正面战场）、纯 MCP 工具（无 CI 与审计故事）、
云 SaaS（schema 与真实 SQL 是高敏数据，信任红利在本地）。

## 设计原则（不可协商）

1. **确定性代码当裁判，AI 当分析师**：schema 是否一致、建议是否有效，由代码与数据库实证裁决；
   AI 负责规则表达不了的语义判断，观点在报告单列、永不影响退出码，建议未过影子库实证关
   不得称有效。
2. **回放推导，不靠解析拼终态**：期望态由真实 MySQL 回放变更集得出，DDL 解析只做预警不做结论。
3. **默认多实例多库**：多库/多 schema 是常态假设而非特例。
4. **数据不出本地**：影子库是同版本本地容器（podman/docker），快照与样本永不离开本机。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/quickstart.md](docs/quickstart.md) | 快速上手：四车道最小链路 |
| [docs/changeset-spec.md](docs/changeset-spec.md) | 变更集规范：目录结构、manifest、DELIMITER、多库约定 |
| [docs/rules.md](docs/rules.md) | 审核规则清单（26 条，可 `modou.toml` 配置） |
| [docs/demo-agent.md](docs/demo-agent.md) | MCP 接入与 AI 委托工作流 |
| [docs/formats.md](docs/formats.md) | 数据格式契约（快照/报告/退出码语义） |
| [docs/architecture.md](docs/architecture.md) | 架构北极星：内核三件套、模块地图、风险 |
| [docs/goals.md](docs/goals.md) | 目标体系与里程碑验收判据 |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR-0001~0009） |

## 治理

| 文件 | 职责 |
|---|---|
| [openspec/project.md](openspec/project.md) | 宪法：不可协商红线与工程口径 |
| [AGENTS.md](AGENTS.md) | 工作区指引：目录、门禁命令、代码规范 |
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | CI：Python 内核门禁 + ui 门禁 |

## 家族

隆中家族成员：[kongming](../kongming)（孔明，AI Agent——墨斗是其数据库工程化的工具面）·
[muniu](../muniu)（木牛，模型网关）· [sunmao](../sunmao)（榫卯，插件治理——哲学同源：
榫卯管"接得上"，墨斗管"对得齐"）· [jinguan](../jinguan)（锦官）· [siku](../siku)（四库）。

## 技术栈

Python 3.12+ · uv · typer（CLI）· sqlglot（唯一 SQL 解析器）· pymysql ·
podman/docker CLI（影子库容器编排）· FastMCP（MCP 表面）· Vite + TypeScript（薄报告层，
构建产物随 wheel 分发，运行期零 Node）。
版本线与依赖以 [pyproject.toml](pyproject.toml) 为准。

## License

[Apache-2.0](LICENSE)
