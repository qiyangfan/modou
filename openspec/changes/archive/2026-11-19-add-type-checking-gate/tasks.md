# 任务：类型门禁（mypy）

## 1. 接入

- [x] 1.1 dev 依赖增 `mypy`、`types-PyMySQL`（`uv lock` 更新）
- [x] 1.2 `ci.yml` core 作业增 `uv run mypy src/modou`
- [x] 1.3 `AGENTS.md` 门禁清单增类型检查命令

## 2. 修错误（零 ignore / 零豁免）

- [x] 2.1 sqlglot 注解统一 `exp.Expr`；`Rule.check` 签名同步
- [x] 2.2 `patrol/summary._section` 增加 overload；`optimize/sideeffects` 局部收窄
- [x] 2.3 `diff/threeway`、`patrol/drift` 的 `dimension_specs` 显式标注并移除
      `type: ignore`
- [x] 2.4 `optimize/candidates` 的 Optional 列定义、`_contains_column` 类型、
      `referenced_tables` 允许无库名
- [x] 2.5 `ai/client` 重试循环类型收窄；`snapshot/introspect` 判空；
      `server/surface_map` 空帮助回落
- [x] 2.6 `uv run mypy src/modou` → `Success: no issues found in 58 source files`

## 3. 负向验收

- [x] 3.1 植入 `PROBE: int = "not-an-int"` → mypy EXIT=1
      （`Incompatible types in assignment`）
- [x] 3.2 删除探针后 EXIT=0

## 4. 收尾

- [x] 4.1 全量门禁：ruff format/check、mypy、pytest 497 passed / 33 skipped
- [ ] 4.2 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 4.3 全绿后归档本 change
