# 提案：CSS 门禁（stylelint）

## Why

UI 有 `src/styles.css`（152 行），此前只有 Prettier 负责格式，没有 CSS 规则检查。
按主流默认组合（`stylelint` + `stylelint-config-standard`）实测 56 条问题：颜色函数
旧写法（`rgba`/小数 alpha）、规则间空行等，全部可自动修复。

## What Changes

- UI dev 依赖增 `stylelint`、`stylelint-config-standard`；配置仅
  `"extends": ["stylelint-config-standard"]`（全默认规则）。
- 脚本 `style:check`：`stylelint "src/**/*.css"`；CI ui 作业与 `AGENTS.md`
  门禁清单同步。
- `src/styles.css` 按 `stylelint --fix` 修正 56 处，并用 Prettier 复核格式。

## 不做清单（Non-goals）

- 不加 `stylelint-disable`、不关闭任何规则、不引入 SCSS/自定义语法。
- 不扫描 `dist/`（构建产物）。

## 风险

- 颜色写法统一为现代函数语法（`rgb(… / 15%)`）：浏览器目标为现代 Chromium
  内嵌 WebView，无兼容性回退需求。
- stylelint 与 Prettier 规则交叉：修复后两者同时通过。
