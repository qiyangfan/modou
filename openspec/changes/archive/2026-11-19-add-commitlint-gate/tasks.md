# 任务：提交信息门禁（commitlint）

## 1. 接入

- [x] 1.1 UI dev 依赖：`@commitlint/cli`、`@commitlint/config-conventional`
- [x] 1.2 `ui/commitlint.config.mjs`：type 白名单补 `release` / `init` / `revert`，
      header ≤ 120，body 行宽关闭
- [x] 1.3 pre-commit `commit-msg` 阶段钩子
- [x] 1.4 `AGENTS.md` 提交纪律段落同步

## 2. 验证

- [x] 2.1 负向：`随便写的信息` → `subject may not be empty` / `type may not be empty`，EXIT=1
- [x] 2.2 正向：`feat(ui): 覆盖率门禁接入` → EXIT=0
- [x] 2.3 历史 40 条提交信息全量回放 → EXIT=0（仅 1 条 body-leading-blank 警告）
- [x] 2.4 钩子入口等价验证：`commitlint --config commitlint.config.mjs --edit <msg>`
      正/负向与 stdin 模式一致

## 3. 收尾

- [ ] 3.1 首次真实提交时核对钩子触发（pre-commit 对未暂存配置有防呆，需提交时验证）
- [ ] 3.2 全绿后归档本 change
