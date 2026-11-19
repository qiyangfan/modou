# 任务：静态卫生收口

## 1. 启用命名规则

- [x] 1.1 `ruff` select 增 `N`；全仓 `ruff check` 零命中
- [x] 1.2 负向：植入 `def BadProbe()` → `N802 Function name 'BadProbe' should be
lowercase`，EXIT=1；移除后 EXIT=0

## 2. 评估结案（默认参数实测）

- [x] 2.1 `S`：`src` 8 条（S603×3、S608×2、S310×2、S105×1）；`tests` S101×855。
      不启用（S608 属产品固有动态 DDL；S101 为测试断言；零豁免不可达）
- [x] 2.2 `D`：`src` 546 条（460 标点 + 约 50 缺 docstring）。不启用
      （与中文标点风格冲突，机械补齐属样板）
- [x] 2.3 vulture（60%）：`src` 34 条，均为动态注册入口/字段/回调误报。不启用
      （需白名单；ruff F401/F841 已覆盖真实死代码）
- [x] 2.4 全限定名：人工审计 0 条；无主流自动规则，不设门禁

## 3. 收尾

- [x] 3.1 全量门禁：ruff format/check 全过
- [ ] 3.2 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 3.3 全绿后归档本 change
