# 提案：类型门禁升到 strict，死代码与抑制收口

## Why

mypy 此前只有默认严格度，且仓库留有 11 处 `# type: ignore`、4 处非空断言、未用导出
与未用变量没有任何机械检查。逐项实测后这些都能用真实类型与结构性修复清掉，不需要
继续留抑制。

## What Changes

- `pyproject.toml` 增加 `[tool.mypy] strict = true`；修复 106 个 strict 错误
  （type-arg 94、no-any-return 7、no-untyped-def 2、attr-defined 1、unused-ignore 2）。
- `# type: ignore` 从 11 处清零：
  - sqlglot `Token`/`TokenType` 改从定义模块 `sqlglot.tokenizer_core` 导入；
  - `threeway` 收窄入参后用 `cast` 取代忽略；
  - `cli` 在连接前显式判空；
  - 测试里的桩连接用 `cast(pymysql.connections.Connection, …)`。
- vulture（`--min-confidence 100`）进 CI 与钩子；18 处未用 `**kwargs` 改为 `**_`。
- knip 进 UI 门禁：删除 8 个未用 barrel 重导出与 `detailTable` 导出；
  `@commitlint/cli` 仅以二进制方式调用，加入 `ignoreDependencies`。
- eslint 恢复 `@typescript-eslint/no-non-null-assertion: error`，修复 4 处非空断言。

## 保留的抑制（结构性，不是偷懒）

- `src/modou/cli.py` 的 ruff `B008`：Typer 以 `typer.Option(...)`/`typer.Argument(...)`
  作为函数默认值声明 CLI 参数；移除忽略后实测 32 处同类写法，全部是框架约定。
  改成全量 `Annotated` 风格属于 CLI 行为面重构，不在本批范围。
- `RUF001/2/3`：中文全角标点，仓库语料使然。

## 验证

- 负向：未注解函数 → `no-untyped-def` EXIT=1；未用 `**kwargs` → vulture EXIT=3；
  未用导出 → knip EXIT=1；非空断言 → eslint EXIT=1；移除探针后全部 EXIT=0。
- 正向：mypy strict 0 错误；vulture 100% 0 命中；knip 0；eslint 0。

## 风险

- strict 会拦住新增代码的裸 `dict`/`list` 注解：按 `dict[str, Any]` 等显式参数化。
- knip 只覆盖 UI（应用）；Python 侧死代码门禁只报 100% 置信度项，避免公共 API 与
  Typer/MCP 动态注册误报。
