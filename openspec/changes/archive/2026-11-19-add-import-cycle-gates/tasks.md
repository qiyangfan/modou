# 任务：依赖单向门禁（import 环 / 独立性）

## 1. 去环（行为不变）

- [x] 1.1 `diff/pipeline.py` 迁至 `src/modou/verify.py`；`cli.py`、`server/__init__.py`、
      `tests/integration/test_verify_e2e.py` 改从 `modou.verify` 导入
- [x] 1.2 版本兼容判定迁至 `snapshot/compat.py`；`replay/env.py` 只保留
      `compatibility_errors`，`snapshot/introspect.py`、`optimize/pipeline.py`
      改用新模块
- [x] 1.3 测试重排：`tests/diff/test_pipeline_guards.py` → `tests/verify/`；
      `tests/replay/test_env.py` 改为 `compatibility_errors` 用例；
      新增 `tests/snapshot/test_compat.py`
- [x] 1.4 回归：AST 子包扫描 cycles=none；`pytest` 497 passed / 33 skipped

## 2. 契约（零豁免）

- [x] 2.1 `pyproject.toml` 增 layers 契约「分层依赖单向（无环）」，层序
      server:cli → ui → verify → patrol → optimize → ai → report → diff/lint →
      changeset → replay → snapshot → params → db
- [x] 2.2 `pyproject.toml` 增 independence 契约「巡检信号相互独立」
      （drift / slowlog / unused_indexes）
- [x] 2.3 `uv run lint-imports`：3 kept / 0 broken
- [x] 2.4 全量门禁：ruff format/check、pytest 全过

## 3. 负向验收（植入 → 非 0 → 移除 → 0）

- [x] 3.1 造环：`diff/threeway.py` 增 `from modou.report.render import REPORT_VERSION`
      → `分层依赖单向（无环） BROKEN`，`modou.diff -> modou.report (l.396)`，
      LINT_EXIT=1；移除后 RESTORED_EXIT=0
- [x] 3.2 破坏独立性：`patrol/slowlog.py` 增 `from modou.patrol.drift import CATEGORY_LABELS`
      → `巡检信号相互独立 BROKEN`，LINT_EXIT=1；移除后 3 kept，RESTORED_EXIT=0

## 4. CI 与收尾

- [x] 4.1 CI 落点：`ci.yml` 既有 `uv run lint-imports` 覆盖新契约
- [ ] 4.2 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 4.3 全绿后 `openspec archive 2026-11-19-add-import-cycle-gates --yes --skip-specs`
