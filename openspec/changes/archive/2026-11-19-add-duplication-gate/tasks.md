# 任务：重复代码门禁（jscpd）

## 1. 消除克隆（行为不变）

- [x] 1.1 `cli.py`：`_load_snapshot`、`_write_json_report`、MySQL 选项 `Annotated`
      别名（2 处命令签名）
- [x] 1.2 `ai/lane_common.parse_opinions` 统一 lint/verify 条目解析
- [x] 1.3 `lint/rules._create_table_entries` 统一建表条目提取
- [x] 1.4 `optimize/advisor`：`fetch_candidates` 接受 `config=None`，删除
      `maybe_fetch_candidates`；pipeline 与 3 个测试同步
- [x] 1.5 `optimize/pipeline._guard_shadow_call`，删除重复签名的内外层函数
- [x] 1.6 `report/jsonutil.dumps/one_line`；optimize/patrol 报告复用
- [x] 1.7 UI `shared.detailCard`（单对象参数，规避 max-params）
- [x] 1.8 回归：pytest 497 passed / 33 skipped；UI 23 passed；DOM 断言不变

## 2. 接入

- [x] 2.1 UI dev 依赖 `jscpd@5.4.3`；脚本 `dup:check`
- [x] 2.2 CI ui 作业增 `npm run dup:check`
- [x] 2.3 `AGENTS.md` 门禁清单同步

## 3. 负向验收

- [x] 3.1 复制 `report/jsonutil.py` 为 `_dup_probe.py` → `Found 1 clones`，
      `--exit-code` EXIT=1
- [x] 3.2 删除探针 → `Found 0 clones`，EXIT=0

## 4. 收尾

- [ ] 4.1 推送后 Actions 首跑核对（账号欠费锁定，待恢复后重跑）
- [ ] 4.2 全绿后归档本 change
