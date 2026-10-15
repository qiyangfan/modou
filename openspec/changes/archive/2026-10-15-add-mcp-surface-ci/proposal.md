# 提案：v0.3 MCP 表面 + CI 集成

## Why

2026 年开发者工具的分发入口是 agent 工具列表（ADR-0002 立项依据：Atlas 已出
Claude Code 插件与 Cursor skills、Bytebase 自带 MCP、Postgres MCP Pro 以单
server 拿 3.4k★）。CLI 内核已齐（v0.1 变更车道 + v0.2 优化车道），本 change 把
既有子命令以 1:1 薄封装暴露为 MCP 工具，并交付托管 CI 的纯静态集成示例——在
「影子层不进托管 CI」定调（owner 2026-10-14，快照含生产 schema、数据不出本地）
之下，pack 预警是唯一适合 CI 的切片（纯静态、零容器、零连接）。

## What Changes

- `modou mcp` 子命令：以标准输入输出通道本地拉起 MCP server，表面依赖进可选
  依赖组（未安装时明确报错并给安装指引）。
- 工具与 CLI 分析类子命令 1:1：pack / verify / snapshot capture / optimize /
  version；参数语义一致，返回与 CLI 机读出口同源的结构化报告 + 退出码语义字段；
  描述与 CLI 帮助同源（英文）；一致性由自动化校验（parity 测试）守护。
- 错误翻译：内核异常 → 工具错误（英文消息），不裸穿堆栈。
- agent 演示链路：样例 fixture 下一句话任务书（「校验这个变更集并优化其中的
  慢 SQL」）在单一 MCP 会话内闭环，文档化并留实证记录。
- GitHub Actions 集成示例：PR 上自动跑 pack 预警；示例以醒目方式声明验收类
  命令（产物含生产 schema）禁止进入托管 CI。

## 受影响决策

- ADR-0002：MCP 为面、1:1 映射、表面层零业务逻辑；零平台化（仅 stdio、无端口、
  无常驻、无鉴权体系）。
- ADR-0006：MCP 框架选型（重依赖进 optional-dependencies，核心保持秒级安装）。
- ADR-0008：报告契约稳定（v0.1 冻结），MCP 消费方依赖同源 JSON，不另立契约。

## 顺序与依赖

- 前置：v0.2（optimize 工具与演示链路的优化环节需要它上线）。
- 后续：v0.4 各车道子命令上线时同步扩列工具（parity 校验强制），不再立 MCP
  专项 change。

## 不做清单（Non-goals）

- 不做 HTTP/SSE 等远程传输与鉴权（本地 stdio 是唯一形态）。
- 不映射交互式/长驻表面（报告 UI、MCP 服务自身、交互式口令提示）。
- 不做 GitHub App / marketplace 插件（示例文档形态，不新增维护面）。
- 不把验收类/采集类命令放进托管 CI 示例（生产 schema 不出本地，红线 4）。
- 不做 MCP 独有业务逻辑（表面层出现业务逻辑即架构违规，ADR-0002）。
