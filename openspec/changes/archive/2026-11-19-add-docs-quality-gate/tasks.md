# 任务：文档与根级配置校验

## 1. 接入

- [x] 1.1 `markdownlint-cli2` + `ui/.markdownlint-cli2.jsonc`（MD013、MD041 关闭并注明理由）
- [x] 1.2 `docs:check` / `docs:format:check` 脚本
- [x] 1.3 Prettier 全量格式化根级 Markdown、workflow YAML、openspec 文档
- [x] 1.4 10 处无语言代码块补 `text`
- [x] 1.5 `ci.yml` ui 作业与 `AGENTS.md` 接入

## 2. 验证

- [x] 2.1 `npm run docs:check`：84 files，0 issues，EXIT=0
- [x] 2.2 `npm run docs:format:check`：全部文件通过，EXIT=0
- [x] 2.3 负向（markdownlint）：`docs/_md_probe.md` 跳级标题 → `MD001`，EXIT=1；
      移除后 EXIT=0
- [x] 2.4 负向（Prettier）：`docs/_fmt_probe.md` 未格式化表格 → 检查失败，EXIT=1；
      移除后 EXIT=0
- [x] 2.5 `mise x -- openspec validate --specs --strict`：7 passed，EXIT=0

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对 `ci / ui`（账号欠费锁定，待恢复后重跑）
- [ ] 3.2 全绿后归档本 change
