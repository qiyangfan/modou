# 提案：提交信息门禁（commitlint）

## Why

提交信息此前只靠约定，没有机械校验；仓库历史混用 `feat:`、`release:`、`init:` 等
前缀，格式漂移无法被发现。

## What Changes

- `@commitlint/cli` + `@commitlint/config-conventional`（UI dev 依赖）；
  `ui/commitlint.config.mjs`：
  - 继承 Conventional Commits，type 白名单在默认集合上补充仓库已有的
    `release`、`init`、`revert`；
  - `header-max-length` 取 120（中文标题按字符计）；
  - `body-max-line-length` 关闭（中文正文无自然折行）。
- `.pre-commit-config.yaml` 增加 `commit-msg` 阶段钩子，调用 UI 内的 commitlint。

## 不做清单（Non-goals）

- 不校验提交正文内容质量（语义正确性靠评审）。
- 不在 CI 重跑 commitlint：钩子已拦截，CI 不重复解析提交历史。
- 不引入 commitizen 等交互式工具。

## 风险

- 配置放置 `ui/`：commitlint 解析 extends 时按 cwd 查找模块，放在 UI 项目内才能
  解析到 `node_modules/@commitlint/config-conventional`；钩子以 `cd ui` 方式调用。
- 新 type 需要走配置评审：白名单是显式清单，避免任意前缀扩散。
