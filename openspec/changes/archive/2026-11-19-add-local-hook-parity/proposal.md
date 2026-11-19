# 提案：本地钩子与 CI 门禁对齐

## Why

pre-commit 此前只挂 gitleaks。格式、静态检查、类型检查全部只在 CI 才拦，坏改动要
等到推送后才发现；commitlint 也缺位，提交信息格式无人校验。

## What Changes

- `.pre-commit-config.yaml` 增加本地钩子：
  - pre-commit 阶段：`ruff format`、`ruff check --fix`（仅 Python 文件）；
    `eslint`、`stylelint`、文档 `prettier`、`markdownlint`（整树，UI 与文档体量小）；
  - commit-msg 阶段：`commitlint`（配置在 `ui/commitlint.config.mjs`）；
  - pre-push 阶段：`mypy src/modou`、`tsc --noEmit`（项目级检查不拖慢提交）。
- 脚本复用 `ui/package.json` 已有命令（`npm run … --prefix ui`），不重复定义工具。

## 不做清单（Non-goals）

- 不把 `pytest`、`jscpd`、`pip-audit`、`actionlint` 放进钩子：耗时或依赖外网，
  留在 CI 执行。
- 不引入 husky/lint-staged 等第二套钩子框架：pre-commit 已覆盖。
- 不新增独立文档解释每个钩子：命令本身即单源，`AGENTS.md` 只列门禁清单。

## 风险

- 钩子依赖本机 `uv` 与 `ui/node_modules`：首次使用需 `uv sync` 与 `npm ci --prefix ui`。
- 整树检查在超大改动时变慢：当前仓库体量下实测 < 5 秒；变慢时再按需收窄。
