# 任务：UI 覆盖率与依赖方向门禁

## 1. 接入

- [x] 1.1 `@vitest/coverage-v8` + `vite.config.ts` 阈值配置
- [x] 1.2 `npm test` 跑覆盖率；新增 `coverage` 脚本
- [x] 1.3 `dependency-cruiser` + `.dependency-cruiser.cjs` + `arch:check` 脚本
- [x] 1.4 `ci.yml` ui 作业接入；`.gitignore` 排除 `ui/coverage/`

## 2. 验证

- [x] 2.1 基线：23 passed；lines 93.53 / statements 92.41 / functions 96.22 /
      branches 66.00
- [x] 2.2 干净运行 `npm test` → 阈值通过，EXIT=0
- [x] 2.3 负向（覆盖率）：阈值临时提到 99 →
      `ERROR: Coverage for lines (93.53%) does not meet global threshold (99%)`，EXIT=1
- [x] 2.4 干净 `arch:check`：`✔ no dependency violations found (12 modules, 25 dependencies)`
- [x] 2.5 负向（循环）：`probe-a.ts ↔ probe-b.ts` → `error no-circular`，EXIT=1
- [x] 2.6 负向（孤儿）：`probe-orphan.ts` → `error no-orphans`，EXIT=1
- [x] 2.7 探针移除后两条命令均 EXIT=0

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对 `ci / ui`（账号欠费锁定，待恢复后重跑）
- [ ] 3.2 全绿后归档本 change
