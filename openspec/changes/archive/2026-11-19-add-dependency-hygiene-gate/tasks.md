# 任务：依赖卫生门禁（deptry）

## 1. 接入

- [x] 1.1 dev 依赖增 `deptry`，`uv lock` / `uv sync`
- [x] 1.2 `[tool.deptry]`：第一方包 `modou`，`DEP002` 忽略 `cryptography`
- [x] 1.3 CI core 与 pre-push 钩子接入 `uv run deptry .`
- [x] 1.4 `AGENTS.md` 同步

## 2. 验证

- [x] 2.1 负向：临时未使用依赖探针 → `DEP002` EXIT=1；移除后 EXIT=0
- [x] 2.2 正向：`uv run deptry .` 0 问题

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对 `ci / core`
- [ ] 3.2 全绿后归档本 change
