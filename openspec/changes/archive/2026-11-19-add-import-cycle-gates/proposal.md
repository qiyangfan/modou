# 提案：依赖单向门禁（import 环 / 独立性）

## Why

结构门禁只钉住了「内核不依赖表面层」，没有钉住依赖方向与无环。实测子包依赖图
（AST 扫描 `src/modou`，2026-11-19）发现 3 处环：

- `diff ↔ report`：`diff/pipeline.py` 负责验收编排并直接渲染报告，而
  `report/render.py` 依赖 `diff.threeway` 的结论类型。
- `replay ↔ snapshot`：`replay/env.py` 依赖 `SnapshotMeta`，而
  `snapshot/introspect.py` 反向调用 `replay.env.unsupported_version_errors`。
- `cli ↔ server`：`server/surface_map.py` 依赖 `modou.cli.app`，`cli` 的 `mcp`
  命令又懒加载 `modou.server`（仅 import-linter 能看见，AST 子包扫描不可见）。

import-linter 没有独立的「无环」契约类型；分层契约（layers）出现任何反向依赖
即失败，等价于钉住无环；independence 用于语义上必须互不依赖的模块组。

## What Changes

- **去环（行为不变）**：
  - `diff/pipeline.py` → `src/modou/verify.py`：验收编排是组合层，依赖
    changeset/replay/diff/report/snapshot，不属于 diff 包；CLI/MCP 改从
    `modou.verify` 导入。
  - 版本兼容判定（`MINIMUM_SUPPORTED_MAJOR` / `version_series` /
    `unsupported_version_errors`）迁至 `snapshot/compat.py`；`replay/env.py`
    只保留影子库环境比对（`compatibility_errors`）。
  - `modou.cli` 与 `modou.server` 定义为同一表面层（允许互相懒加载），
    不改变导入方式。
- **契约**（零豁免、无 `ignore_imports`）：
  - `分层依赖单向（无环）`：server/cli → ui → verify → patrol → optimize → ai →
    report → diff/lint → changeset → replay → snapshot → params → db。
  - `巡检信号相互独立`：`patrol.drift` / `patrol.slowlog` /
    `patrol.unused_indexes` 三类信号互不依赖，汇总只在 `patrol.report`。
- **测试**：`tests/diff/test_pipeline_guards.py` → `tests/verify/`；版本测试迁至
  `tests/snapshot/test_compat.py`，并补 `compatibility_errors` 两个用例。
- **CI 落点**：`ci.yml` 已有 `uv run lint-imports` 步骤，新契约自动生效，无需改
  workflow。

## 受影响决策

- **ADR-0002**：把「业务逻辑只在内核、表面层只做解析与展示」细化为可执行的
  分层顺序；不修改 ADR 文本。
- 无产品行为变化，走 `skip_specs`。

## 不做清单（Non-goals）

- 不改任何报告格式、退出码、CLI/MCP 参数。
- 不引入 `ignore_imports`、不调换层序来迁就现状；环在代码侧消除。
- 不做模块级（文件级）环契约：分层契约已覆盖包间反向依赖，文件级契约对现有
  代码无额外约束价值。

## 风险

- 移动模块改变导入路径：以全量测试与 CLI 冒烟为回归证据；对外未承诺
  `modou.diff.pipeline` 是公共 API。
- 分层契约对未来代码是硬门槛：新增跨层依赖需先调整架构而不是加豁免。
