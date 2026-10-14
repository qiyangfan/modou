# ADR-0006：技术栈——Python 3.12+ / uv / sqlglot / testcontainers / FastMCP

- 状态：接受
- 日期：2026-10-14
- 依据：生态库强度对比与团队接手性评估

## 决策

- **Python 3.12+**，uv 管理依赖与锁，src 布局，typer CLI；
- **sqlglot** 为唯一 SQL 解析器（方言感知、规则引擎基座）；
- **testcontainers**（本地可 podman）管理影子库生命周期；
- **FastMCP** 做 MCP 表面（与 CLI 子命令 1:1）。

重依赖（容器、AI SDK）一律放 optional-dependencies，核心秒级安装。

## 理由

- sqlglot 是当前方言覆盖与解析质量最强的 Python SQL 库，规则迭代快；
- uv 解决开源分发（`uv tool install modou`）与可复现锁；
- FastMCP 到 typer 的映射成本低，表面层零业务逻辑（ADR-0002）。

## 备选与出口

- **Go + TiDB parser**：单二进制分发最优，但规则迭代与 AI 生态弱于 Python；
  留作重写出口——若单二进制成为刚需，内核按本架构重写，表面契约不变；
- **Java + Druid parser**：仅当接手团队完全无 Python 人力时启用，回放式设计下
  对解析强度要求不高，可行但非默认。
