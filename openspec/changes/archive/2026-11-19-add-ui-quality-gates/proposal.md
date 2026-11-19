# 提案：UI 覆盖率与依赖方向门禁

## Why

UI 侧有 23 条 vitest 用例但没有覆盖率门槛，jacoco 类门禁只覆盖了 Python；同时
`ui/src` 没有依赖方向校验，循环依赖或孤儿模块只能靠人工发现。

## What Changes

- `@vitest/coverage-v8`（v8 provider）；`npm test` 改为 `vitest run --coverage`，
  另有独立 `coverage` 脚本。
- 阈值按实测基线下取整（2026-11-19：lines 93.53 / statements 92.41 /
  functions 96.22 / branches 66.00）：lines / statements / functions ≥ 90，
  branches ≥ 60。
- `dependency-cruiser` + `.dependency-cruiser.cjs`：`no-circular`、`no-unresolvable`、
  `no-orphans`（入口 `src/index.ts` 与 `.d.ts` 除外），脚本 `arch:check`。
- `ci.yml` 的 ui 作业增加 `arch:check`；`ui/coverage/` 加入 `.gitignore`。

## 不做清单（Non-goals）

- 不按文件设覆盖率门槛：当前只有整树阈值，个别视图（patrol.ts 81.57%）不单独卡线。
- 不引入 ESLint 之外的 UI 分层规则：依赖方向由 dependency-cruiser 单点负责。
- 不覆盖 `styles.css`：v8 不统计 CSS，样式由 stylelint 负责。

## 风险

- 新增代码可能拉低整树覆盖率到阈值下：这是门禁的预期行为，补测试或调整阈值需留证。
- dependency-cruiser 对 TS 路径别名依赖 tsconfig：改 tsconfig 后需复跑 `arch:check`。
