# 提案：类型门禁（mypy）

## Why

本仓此前没有 Python 类型检查门禁，类型注解只靠约定。引入 mypy 默认模式（不启用
strict）实测：

- 缺 `types-PyMySQL` 时 45 个错误；补桩后 26 个，集中在 sqlglot 30 的
  `Expr`/`Expression` 分层、Optional 收窄、迭代器元素类型、数据库行空值。
- 其中 `ai/client.py` 的重试循环存在 `None` 可能被 raise 的推断缺口；
  `snapshot/introspect.py` 对 `fetchone()` 未判空。

## What Changes

- dev 依赖增 `mypy`、`types-PyMySQL`。
- CI core 作业增 `uv run mypy src/modou`（默认严格度，只约束生产代码）。
- 修全部 26 个错误，**零 `# type: ignore`、零配置豁免**：
  - sqlglot 相关注解统一到 `exp.Expr`（`Condition` 不继承 `Expression`）；
    `Rule.check`、`_wrapped_predicate_columns` 等随同收口。
  - `_section` 用 `@overload` 保持 dict/list 返回类型；`IndexView.keys`
    在过滤后以局部变量收窄。
  - `dimension_specs` 显式标注渲染函数类型，移除既有 4 处 `type: ignore`。
  - 数据库行 `fetchone()` 判空后抛 `RuntimeError`；`inspect.getdoc` 空值回落。
  - AI 重试循环显式类型收窄，保持「耗尽后抛最后一次错误」的行为。
- `AGENTS.md` 门禁清单同步。

## 不做清单（Non-goals）

- 不启用 `--strict`、不引入 pyright 双跑：mypy 默认模式先立住，strict 另议。
- 不检查 `tests/`：测试夹具大量动态构造，先约束生产代码。
- 不加 `ignore_missing_imports` 或模块级豁免。

## 风险

- sqlglot 上游类型标注变动会影响门禁：注解跟随其公开类型，不使用 private API。
- 类型收窄改动触及影子库错误路径：以全量测试（497 passed / 33 skipped）回归。
