# 任务：CSS 门禁（stylelint）

## 1. 接入

- [x] 1.1 UI dev 依赖 `stylelint`、`stylelint-config-standard`；`.stylelintrc.json`
      仅 extends 标准配置
- [x] 1.2 脚本 `style:check`；CI ui 作业增步骤；AGENTS 门禁清单同步
- [x] 1.3 `stylelint --fix` 修复 56 处；Prettier 复核通过

## 2. 负向验收

- [x] 2.1 植入 `.probe { colr: red; }` → `Unknown property "colr"
property-no-unknown`，EXIT=2
- [x] 2.2 移除后 EXIT=0

## 3. 收尾

- [x] 3.1 UI 全量门禁：typecheck / eslint / prettier / stylelint / jscpd / vitest
- [ ] 3.2 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 3.3 全绿后归档本 change
