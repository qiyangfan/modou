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

## 修订记录

- **2026-10-18：容器编排事实修订（testcontainers 未采纳）**。影子库生命周期
  实际落地为手搓 podman/docker CLI 编排（`replay/container.py`，150 行）：
  零额外依赖（重依赖红线）、podman/docker 命令面同构、本地与 CI 行为一致；
  testcontainers（当时最新 4.15）仍拉 SDK 依赖族，与「核心秒级安装」冲突，
  本 ADR 原文的 testcontainers 决策按此修订为未采纳。技术栈其余决策
  （Python/uv/sqlglot/typer/FastMCP）经 2026-10-18 全栈调研重新确认仍最优，
  无修订。
- **2026-10-18：UI 工具链基线入档**。薄报告层工具链基线：eslint 10、
  vitest 5、TypeScript 6（桥接版，typescript-eslint 兼容）；TypeScript 7
  （Go 原生编译器）暂不升级——7.1 之前无可 import 编程 API 且 typescript-eslint
  不兼容，7.1 稳定后另行评估。手搓实现维持的查证结论（DELIMITER 切分器、
  BYOK stdlib 客户端、CLI→MCP 映射）见
  `openspec/changes/`（upgrade-toolchain-latest-stable 提案）。
