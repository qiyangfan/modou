# 任务：覆盖率门禁（阈值 80%）

## 1. 接入

- [x] 1.1 dev 依赖增 `pytest-cov`
- [x] 1.2 `ci.yml` pytest 步骤改为 `--cov=modou --cov-report=term --cov-fail-under=80`
- [x] 1.3 `AGENTS.md` 门禁清单同步

## 2. 验证

- [x] 2.1 基线：497 passed / 33 skipped，总覆盖率 80.82%
- [x] 2.2 负向：植入 600 行未覆盖模块 → `FAIL Required test coverage of 80%
not reached. Total coverage: 70.35%`，EXIT=1
- [x] 2.3 移除探针后 → `Required test coverage of 80% reached`，EXIT=0

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 3.2 全绿后归档本 change
