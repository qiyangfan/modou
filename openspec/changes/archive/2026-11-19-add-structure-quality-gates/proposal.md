# 提案：结构质量门禁（复杂度 / 体积 / import 分层 / 格式）

## Why

本仓门禁此前只有 ruff 基础规则（E/F/W/I/UP/B/SIM/RUF）与 pytest，缺少 PMD 类
结构质量面。按 kongming 的可执行口径与 PMD 数值阈值实测（2026-11-19）：

- 圈复杂度：`src` 有 **12 个函数 C901 > 10**（最高 `server._register_tools` 51、
  `replay/splitter._scan` 19）；UI 有 **4 个渲染函数复杂度 16–34**。
- 体积：无上帝类/上帝模块（最大类 10 方法/170 行，最大模块 717 行），但存在
  **上帝方法级函数**：`_register_tools` 393 行/169 语句（PLR0915 188 语句）、
  4 处语句 >50、4 处分支 >12。
- import 卫生：无环、无内核→表面反向依赖，但有 1 处父级相对导入、2 处未显式
  `check=False` 的 subprocess、1 处循环变量覆盖。
- 重复/低效写法：11 处 list-append 可转 extend、3 处冗余容器构造、1 处冗余 return。
- UI 格式：`views.ts` 440 行、27 行超 120 字符，ESLint 无结构规则，无格式门禁。
- 超长行：Python 已由 E501（行长 120）覆盖且零命中；UI 无格式门禁。

## What Changes

- **先修结构、后开门禁**（无任何豁免）：
  - Python 拆分 `server._register_tools` 为按工具注册函数；拆分
    `splitter._scan`、`discovery.discover_changeset`、`slowlog.parse_slowlog`、
    `cli.patrol_unused_indexes`、`ui.server.run_ui`、`render.render_text`、
    `slicer.slice_schema`、`candidates.build_candidates`、
    `pipeline.validate_inputs` 等 12 个复杂度热点。
  - UI 按报告类型拆分 `views.ts` 为 `views/*`（单文件 <300 行），拆
    `renderVerify`/`renderOptimize`/`renderPatrolSummary` 与入口 `main`。
- **Python 门禁**（主流工具默认参数）：
  - ruff `select` 增补 `C901`（10）、`PLR0912`（12）、`PLR0915`（50）、
    `TID`、`PLW`、`PERF`、`C4`、`RET`、`T10`、`T20`；
  - pylint 仅启用 `too-many-lines` / `too-many-public-methods`（kongming 同口径，
    默认 1000 行 / 20 个公有方法）；
  - import-linter 增「内核不依赖表面层（ADR-0002）」契约；
  - 新增 `src/modou/report/__init__.py`（原为命名空间包，import-linter 无法解析）。
- **UI 门禁**（ESLint/Prettier 默认参数）：
  - ESLint 增 `complexity`(20)、`max-depth`(4)、`max-lines`(300)、
    `max-lines-per-function`(50)、`max-params`(3)；
  - 增加 prettier 与 `format:check`，按默认配置格式化全部 UI 源码。
- **CI 落点**：`ci.yml` core 作业增 pylint 与 lint-imports；ui 作业增
  `format:check`。ruff/pytest 原有作业自动覆盖新增规则。

## 受影响决策

- **ADR-0002**：新增 import-linter 契约把「业务逻辑只在核心里」变成可执行门禁；
  不改变 ADR 内容。
- 不触碰其他 ADR；无产品行为变化（纯重构 + 工具链），走 skip_specs。

## 不做清单（Non-goals）

- 不改任何产品行为、报告契约、退出码语义：重构以现有测试为回归证据。
- 不启用需要逐条抑制的规则（BLE 盲捕获、ARG 未用参数、PT 测试断言风格、
  DTZ 测试中刻意构造的 naive datetime）——选择不启用，而不是加豁免。
- 不引入 mypy/pyright、覆盖率阈值、jscpd/死代码扫描：属跨仓 handoff 的 P1
  独立批次，另立 change。
- 不修改 secret scanning（已单独提交 `4395efb`）。
- 不加 `# noqa`、per-file ignore、`|| true` 或 `continue-on-error`。

## 风险

- 大范围机械重构可能引入行为漂移：以 494 个 Python 用例 + 22 个 UI 用例为回归
  证据；每个热点单独跑目标测试后再合并全量。
- 新规则对未来代码是硬门槛：规则均为主流工具的默认阈值，不设仓库内自定义参数。
- Prettier 首次格式化产生大 diff：属机械格式变化，构建与测试验证通过。
