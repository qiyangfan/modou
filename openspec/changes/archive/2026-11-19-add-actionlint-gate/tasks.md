# 任务：workflow 静态检查（actionlint）

## 1. 接入

- [x] 1.1 本机 actionlint 1.7.12（Homebrew；等价 `mise install actionlint@1.7.12`）
- [x] 1.2 `ci.yml` 增 `workflows` 作业：固定下载 v1.7.12 + 默认配置扫描
- [x] 1.3 `AGENTS.md` 门禁清单同步

## 2. 验证

- [x] 2.1 干净扫描：`.github/workflows/*.yml` 零告警，EXIT=0
- [x] 2.2 负向：植入 `_actionlint_probe.yml`（`${{ fromJSON() }}` 参数数错误）
      → `number of arguments is wrong. function "fromJSON(string) -> any" takes
1 parameters but 0 arguments are given [expression]`，EXIT=1
- [x] 2.3 移除探针后 EXIT=0

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 3.2 全绿后归档本 change
