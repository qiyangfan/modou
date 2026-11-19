# 任务：本地钩子与 CI 门禁对齐

## 1. 接入

- [x] 1.1 pre-commit 阶段：ruff format / ruff check / eslint / stylelint /
      文档 prettier / markdownlint
- [x] 1.2 commit-msg 阶段：commitlint
- [x] 1.3 pre-push 阶段：mypy、tsc
- [x] 1.4 `pre-commit install` 安装 pre-commit、pre-push、commit-msg 三类钩子

## 2. 验证

- [x] 2.1 `pre-commit run --all-files`：7 个钩子全过，EXIT=0
- [x] 2.2 `pre-commit run --hook-stage pre-push --all-files`：mypy、tsc 通过，EXIT=0
- [x] 2.3 commitlint 负向：`随便写的信息` → `subject may not be empty` /
      `type may not be empty`，EXIT=1；正向 `feat(ui): 覆盖率门禁接入` → EXIT=0
- [x] 2.4 历史 40 条提交信息全量回放，退出码 0（仅 1 条 body-leading-blank 警告）

## 3. 收尾

- [ ] 3.1 首次真实提交时核对 commit-msg 钩子实际触发（pre-commit 对未暂存配置
      有防呆，`--commit-msg-filename` 手动回放会被该保护拦截；钩子入口已按
      `--edit` 方式直接验证）
- [ ] 3.2 全绿后归档本 change
