# 设计：v0.3 MCP 表面 + CI 集成

> 调研快照 2026-10（FastMCP 4.1.0 / MCP 规范 SEP-986），出处见文末。

## 1. 框架与版本

- 选 `fastmcp`（PrefectHQ 维护，当前 4.1.0），锁 `>=4,<5`。核心 API
  （`FastMCP(name)` + `@mcp.tool` + `mcp.run()`，stdio 默认）自 2.x 起稳定，
  薄封装用法无断层风险。
- 不用官方 SDK 内置的 `mcp.server.fastmcp`（2024 年并入的旧 1.0 高层 API，仅维护
  不新增）；4.x 完整安装仍以官方 `mcp>=2,<3` 为协议运行时，无平行实现风险。
- 依赖落位：`[project.optional-dependencies] mcp = ["fastmcp>=4,<5"]`——重依赖
  只进 optional（宪法），核心 `uv sync` 秒级安装不变。

## 2. 工具契约（1:1 的落地细则）

- **清单**（本 change 时点的分析类子命令）：`pack`、`verify`、`snapshot_capture`、
  `optimize`、`version`。嵌套子命令以下划线连接（`snapshot_capture`）。
- **命名**：snake_case、纯字母数字 + 下划线、≤64 字符——满足 SEP-986（允许字符集
  `A-Za-z0-9_-. /`，部分客户端拒 `.`，取最稳子集）。
- **描述**：复用 CLI help 英文文案（description 是 agent 工具发现的唯一依据，
  两表面同源避免语义漂移）。
- **返回**：返回内核层既有结果结构（dict/Pydantic model）→ 自动生成结构化内容
  与输出 schema，同时附文本保兼容；返回体必含与 CLI 一致的退出码语义字段
  （exit_code），agent 依此判断结论档位。
- **错误**：内核异常在表面层翻译为工具错误（英文消息）；启用
  `mask_error_details=True` 遮蔽非工具异常细节，防堆栈与内部路径泄漏。
- **参数**：与 CLI 同名同义；路径类参数收本地路径字符串（快照、变更集目录、
  报告输出），MCP 会话与用户共享同一本地文件系统是产品前提（本地工具）。

## 3. parity 守护（架构红线的机械化）

- 单测枚举 typer 注册子命令 → 过滤非映射面（显式排除清单：交互式/长驻表面）→
  与 MCP server 注册的工具名集合比对，缺一或多一即失败。
- 新车道子命令上线必须同步扩列工具，parity 测试把「忘了映射」变成红灯而非
  悄悄漂移。

## 4. 形态与零平台化

- `modou mcp` 子命令启动 stdio server（客户端按需 spawn 子进程，用完即退，
  无常驻）；无端口监听、无鉴权、无远程形态（ADR-0002）。
- 未安装 `[mcp]` extra：导入守卫 → 退出码 2 + 英文安装指引
  （`uv tool install modou[mcp]`）。

## 5. agent 演示链路（v0.3 判据二）

- fixture 复用 `examples/changeset-demo` + 预采集的执行前后快照 + 慢 SQL 文件：
  演示不需要生产库连接，任何机器可复现。
- 链路：`pack`（预警）→ `verify`（快照验收，退出码语义）→ `optimize`（慢 SQL
  实证优化）——全部在单一 MCP 会话内完成，中间产物以本地文件路径传递。
- 交付：演示文档（一句话任务书原文、agent 逐步调用记录、最终汇总答句）+ 脚本化
  MCP client 的自动化冒烟测试（无头复跑，不依赖真人 agent）。

## 6. GitHub Actions 示例（v0.3 判据三）

- 形态：示例文档 + 可复制 workflow（示例目录），不发布 marketplace 插件
  （不新增维护面，owner 定调）。
- 内容：PR 触发 → 装 uv → `uv tool install modou`（或 pipx）→
  `modou pack <changeset_dir> --report-json pack-warnings.json` →
  预警摘要回贴 PR（steps output / job summary）。
- 红线声明（示例文档必含）：`verify` 类命令的输入快照含生产 schema 全文，
  禁止进入托管 CI；需要 CI 化验收的团队在本机 runner 自跑（本地门禁口径）。

## 出处

- gofastmcp.com：FastMCP tools / running server / changelog（4.1.0、结构化返回、
  ToolError、mask_error_details）
- modelcontextprotocol.io SEP-986（工具名字符集与长度）
- PyPI：fastmcp / mcp 版本线（2.3.0，2026-10）
- 本仓：docs/HANDOFF.md「未完成」第 1 条（影子层 CI 定调与 pack 切片依据）
