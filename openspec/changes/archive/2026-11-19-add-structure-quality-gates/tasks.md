# 任务：结构质量门禁（先重构、后开闸）

## 1. Python 热点重构（行为不变）

- [x] 1.1 `server/__init__.py`：`_register_tools`（393 行 / 复杂度 51 / 188 语句）
      拆为按工具注册函数；`patrol_unused_indexes` 的 live/offline 分支抽出
- [x] 1.2 `replay/splitter.py`：`_scan`（复杂度 19 / 分支 17 / 76 语句）拆出
      delimiter/lexeme 消费辅助
- [x] 1.3 `changeset/discovery.py`：`discover_changeset`（复杂度 13 / 分支 13）拆出
      manifest 覆盖、文件构建、重复序号、跳号检查
- [x] 1.4 `patrol/slowlog.py` 状态机改为 `_SlowlogParser`；`patrol/fingerprint.py`
      抽出值列表折叠与 token 归一
- [x] 1.5 `cli.py` unused-indexes：拆出库存采集与判定辅助
- [x] 1.6 `ui/server.py`：请求处理器移到模块级 `_ReportHandler`，`run_ui` 只负责装配
- [x] 1.7 `report/render.py`、`ai/slicer.py`、`optimize/candidates.py`、
      `optimize/pipeline.py` 拆分渲染/预算/候选/校验步骤
- [x] 1.8 目标测试回归：`tests/replay tests/changeset tests/patrol` 114 passed；
      `tests/mcp tests/cli tests/optimize tests/report tests/ai tests/ui` 233 passed

## 2. Python 门禁（主流默认参数，无豁免）

- [x] 2.1 ruff `select` 增 `C901/PLR0912/PLR0915/TID/PLW/PERF/C4/RET/T10/T20`
      （阈值全用默认）
- [x] 2.2 dev 依赖增 `pylint>=3.3`、`import-linter>=2.2`；`uv lock` 更新
- [x] 2.3 pylint 体积门禁：`--disable=all --enable=too-many-lines,too-many-public-methods`
      （默认 1000 行 / 20 公有方法，kongming 同口径）
- [x] 2.4 import-linter 契约「内核不依赖表面层（ADR-0002）」；
      补 `src/modou/report/__init__.py` 使 `modou.report` 可被解析
- [x] 2.5 修复规则命中：4 处 `check=False` 显式化、循环变量覆盖、11 处
      extend 化、3 处冗余构造、1 处冗余 return、1 处父级相对导入
- [x] 2.6 全量门禁：ruff format/check 全过；pylint 10.00/10；
      lint-imports 1 kept；pytest 494 passed + 33 skipped；CLI 冒烟通过

## 3. UI 重构与门禁

- [x] 3.1 `views.ts` 拆为 `views/{shared,verify,optimize,lint,patrol,summary,opinions,report}.ts`
      （单文件 <300 行，对外 API 由 barrel 保持不变）
- [x] 3.2 拆 `renderVerify`(28)、`renderOptimize`(34)、`renderPatrolSummary`(66 行)、
      入口 `main`(58 行)
- [x] 3.3 ESLint 增 `complexity/max-depth/max-lines/max-lines-per-function/max-params`
      （默认 20/4/300/50/3）
- [x] 3.4 增 prettier 与 `format:check`（默认配置，`.prettierignore` 仅排除
      `dist/node_modules/coverage/package-lock.json`）；全量格式化
- [x] 3.5 测试按主题拆分（fixtures/render/regressions/opinions/summary），
      23 用例全绿；typecheck/lint/format/test 全过

## 4. CI 落点

- [x] 4.1 `ci.yml` core 作业增 pylint 与 lint-imports 步骤
- [x] 4.2 `ci.yml` ui 作业增 `npm run format:check`
- [ ] 4.3 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）

## 5. 负向验收（植入 → 非 0 → 移除 → 0）

- [x] 5.1 ruff C901：植入 12 分支函数 → `Found 1 error` EXIT=1；移除后 EXIT=0
- [x] 5.2 pylint 体积：植入 21 公有方法类 → `9.77/10` EXIT=8；移除后 EXIT=0
- [x] 5.3 import-linter：`modou.changeset` 植入 `from modou.cli import app`
      → 契约 broken EXIT=1；移除后 1 kept EXIT=0
- [x] 5.4 ESLint complexity：植入复杂度 26 函数 → `1 error` EXIT=1；移除后 EXIT=0
- [x] 5.5 ESLint max-lines-per-function：植入 59 行函数 → `1 error` EXIT=1；
      移除后 EXIT=0
- [x] 5.6 prettier：植入未格式化文件 → `Code style issues found` EXIT=1；
      移除后 EXIT=0

## 6. 归档

- [ ] 6.1 PR 合并后 `openspec archive 2026-11-19-add-structure-quality-gates`
