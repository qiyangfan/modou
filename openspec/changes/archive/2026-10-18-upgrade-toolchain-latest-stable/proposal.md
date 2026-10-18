# 提案：技术栈升级至最新稳定版——UI 工具链大版本 + Python 补丁刷新 + 手搓盘点收档

## Why

owner 2026-10-18 要求全栈升至最新稳定版，重点是功能增量与"升级后原生能力可替代
手搓"的盘点（参照 pi 1.0.0 原生 MCP 替代插件的先例）。调研结论（查证日期
2026-10-18，PyPI / npm registry / endoflife.date 为准）：

**Python 内核侧已基本在最新稳定版**——typer 0.27.3、pymysql 1.2.3、
cryptography 50.0.2、pytest 9.1.1、pydantic（传递依赖）2.14.1 均已是最新；
仅 sqlglot 30.22.0→30.23.0、ruff 0.17.0→0.17.1、fastmcp 4.1.0→4.1.1 三个
补丁级差距，锁刷新即可，声明下限不动。

**真实缺口在 UI 工具链**（package.json 声明 vs npm 最新）：

| 包 | 声明 | 最新稳定 | 差距 |
|---|---|---|---|
| eslint | ^9.0.0 | 10.13.0 | 跨大版本；**eslint 9 已 EOL**，安全补丁不再回移（硬理由） |
| vitest | ^4.0.0 | 5.0.5 | 跨大版本（2026-09-28 发布，性能 + 修复长期缺陷） |
| typescript | ^5.9.0 | 7.0.2 | 目标 6.x 桥接版，**不升 7**（理由见"受影响决策"） |
| jsdom | ^27.0.0 | 30.1.3 | 跨大版本，随 vitest 5 兼容矩阵 |
| vite / typescript-eslint | ^8 | 8.3.4 / 8.71.2 | ^ 范围内刷新 |

**Node 对齐缺口**：CI 双 job 用 Node 24（家族 web 门禁标准），而 ui 的
@types/node ^26.6.5 已按 Node 26 API 声明——类型面与运行面不一致。Node 26
于 2026-10-28 进入 LTS，届时 CI 升 26 完成对齐。

**手搓盘点（本提案核心关切，逐处查证，结论：四处手搓全部维持，一处 ADR 漂移须收档）**：

| 手搓点 | 候选原生替代 | 查证结论 |
|---|---|---|
| `replay/container.py`（150 行 podman/docker CLI 编排） | testcontainers 4.15 | **维持手搓**：重依赖红线（零额外依赖、podman/docker 同构、本地 CI 行为一致）；但 ADR-0006 写的是 testcontainers，**ADR 与实现漂移，须修订入档**防后人按 ADR"纠正"实现 |
| `replay/splitter.py`（205 行 DELIMITER 感知词法切分） | sqlglot parse / tokenize | **维持手搓**：DELIMITER 是 mysql 客户端指令而非服务器 SQL，sqlglot 原生不支持（sqlglot issue #2587 佐证：需自行跟踪自定义分隔符） |
| `ai/client.py`（131 行 stdlib urllib BYOK 客户端） | openai SDK 3.35 | **维持手搓**：SDK 进 core 违"核心秒级安装"（ADR-0006），进 optional 改变 BYOK 内置定位；对各家 OpenAI 兼容端点，SDK 强校验反而增加兼容风险 |
| `server/surface_map.py`（CLI→MCP 1:1 映射） | fastmcp CLI 集成 | **维持手搓**：fastmcp 无 typer/click→MCP 转换器（方向相反：generate-cli 是从 MCP 工具生成 CLI）；且映射是 specs/mcp-surface 冻结契约 |
| pyproject 顶层 `cryptography`（源码与测试零 import） | — | **保留**：实为 pymysql caching_sha2_password（MySQL 8 默认认证插件）的运行时伴随依赖，加注释防误删 |

另：Python 3.15.0 已发布（2026-10-09）。**不抬地板**（>=3.12 保持）：3.14 的
t-strings（PEP 750）不替代任何手搓模块——上下文工程是切片/分包/注入逻辑而非
字符串模板；抬地板收窄 `uv tool install modou` 分发面，无对等收益。

## What Changes

- **UI 工具链四件套**（ui/package.json + 配置适配，行为零变化）：
  - eslint ^9 → ^10（9 EOL 硬理由；breaking 以官方迁移指南为准：Node 版本要求、
    CLI 选项移除、styleText 着色判定变化）；
  - vitest ^4 → ^5（vite 转为 peer dependency——ui 已显式声明 vite，前置满足；
    vm pool 提速、`vitest list` 静态解析、`--repeats` 防抖动）；
  - typescript ^5.9 → ^6.x（桥接版：新默认值 + 保持 JS 编程 API，
    typescript-eslint 8.71 兼容）；
  - jsdom ^27 → ^30（按 vitest 5 兼容矩阵定版本）；
  - vite ^8 / typescript-eslint ^8 在 ^ 范围内刷至最新 minor。
- **Node 对齐**：CI 两 job node-version 24 → 26（执行条件：2026-10-28 Node 26
  进入 LTS 之后；与 @types/node ^26 对齐）。
- **Python 锁刷新**：`uv lock --upgrade` 带入 sqlglot 30.23 / fastmcp 4.1.1 /
  ruff 0.17.1 / hatchling 最新补丁线；pyproject 声明与上限约束不动。
- **ADR-0006 修订**：增修订记录——影子库容器编排实际落地为手搓 podman/docker
  CLI（testcontainers 决策未采纳及理由）；顺带记录 UI 工具链基线（eslint 10 /
  vitest 5 / TS 6，TS 7 待 7.1）。
- **依赖卫生注释**：pyproject cryptography 行注明其为 pymysql 认证运行时伴随
  依赖（源码零 import，禁止误删）。

## 受影响决策

- **ADR-0006**：容器编排事实修订（手搓 CLI 替代 testcontainers，理由与日期入档）；
  技术栈其余决策（sqlglot / uv / typer / FastMCP）经本次调研重新确认仍最优，
  无修订。UI 工具链基线在修订段一并记录。
- **TypeScript 7 不升级**：7.0 无可 import 编程 API（7.1 起提供），typescript-eslint
  与 native 编译器不兼容（官方 issue #10940）；7.1 稳定 API 发布后另开 change
  评估。属工具链版本选择，不入 ADR 层，本提案即记录。
- **uv / Python 工具链**：uv 0.13.1 已是最新，无动作；Python 地板 3.12 保持。
- 不触碰 ADR-0001/0002/0003/0004/0005/0008/0009——运行行为零变化。

## 顺序与依赖

- P0：Python 锁刷新 + cryptography 注释（零风险先行，全门禁验证）；
- P1：UI 四件套——vitest 5 + jsdom（+ vite 范围刷新）先行 → eslint 10 →
  TS 6（与 typescript-eslint 同步验证），每步跑 ui 门禁；
- P2：CI Node 26（日历条件触发）+ ADR-0006 修订 + action 版本核对；
- 前置：无（不依赖其他 change）；ui/dist → hatch force-include 构建链路
  须在升级后回归验证。

## 风险

- vitest 5 内部换用 pretty-format，测试输出/快照格式可能变化——属工具链原因，
  适配期望值并在提交记录注明，非行为变化；
- TS 6 新默认值可能暴露 ui 现有类型问题——ui 面小，预期改动可控；
- eslint 10 规则增删可能产生新告警——逐条确认修复，不批量豁免。

## 不做清单（Non-goals）

- 不升 TypeScript 7.0（无编程 API + typescript-eslint 不兼容；7.1 后另评）；
- 不抬 Python 地板到 3.13/3.14/3.15（分发面优先；t-strings 无替代收益）；
- 不引入 testcontainers / openai SDK / click-mcp 等任何新依赖——四处手搓均
  维持（查证结论见 Why），手搓是决策不是欠账；
- 不改任何运行行为：报告 v0.1 冻结契约、退出码语义、MCP 表面、CLI 输出、
  UI 交互零变化——纯依赖与工具链升级，**无 spec delta**；
- 不动 fastmcp 上限约束（`>=4,<5` 保留；fastmcp 5 若发布另评）；
- 不同步 muniu/kongming 家族的 Node 标准（本仓先对齐类型面，家族一致性由
  owner 另行决策）。
