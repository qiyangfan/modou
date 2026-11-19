# 提案：重复代码门禁（jscpd，零克隆）

## Why

按 PMD CPD 类比扫描生产代码（`src/modou` + `ui/src`），jscpd 默认参数
（`min-tokens=50`）发现 13 处克隆、重复行 0.95%（Python 12 处、TypeScript 1 处）：

- `cli.py` 报告写盘块 5 组、快照加载块 2 组、MySQL 选项声明块 2 组；
- `ai/lane_lint.py` 与 `ai/lane_verify.py` 的观点条目解析循环；
- `lint/rules.py` 建表条目提取；`optimize/advisor.py` 参数列表重复；
- `optimize/pipeline.py` 影子函数签名重复；
- `optimize/report.py` 与 `patrol/report.py` 的 JSON 序列化 / 单行压缩；
- UI `views/patrol.ts` 与 `views/verify.ts` 的结论卡片。

## What Changes

- UI dev 依赖增 `jscpd`（5.4.3），脚本 `dup:check`：
  `jscpd ../src/modou src --exit-code`（默认 `min-tokens=50`，任何克隆即失败）。
- CI ui 作业增 `npm run dup:check`；AGENTS 门禁清单同步。
- 先消除全部克隆（行为不变，零豁免）：
  - `cli.py`：`_load_snapshot` / `_write_json_report` 辅助 + `Annotated` MySQL
    选项别名；
  - `ai/lane_common.parse_opinions` 统一两个 lane 的条目过滤；
  - `lint/rules._create_table_entries` 统一建表条目提取；
  - `optimize/advisor` 合并 `maybe_fetch_candidates` 到 `fetch_candidates`
    （`config=None` 早退，公共名同步）；
  - `optimize/pipeline._guard_shadow_call` 统一影子阶段异常收敛；
  - `report/jsonutil.dumps/one_line` 供 optimize/patrol 报告复用；
  - UI `shared.detailCard` 统一结论卡片。

## 不做清单（Non-goals）

- 不调 `min-tokens`、不设 threshold 放水：默认参数 + `--exit-code`。
- 不扫描测试夹具与 `dist/`：门禁只约束生产代码。
- 不为通过而删除公共 API：`dumps_json`、`fetch_candidates` 等名称保留。

## 风险

- 合并重复块改变调用路径：以全量 Python/UI 测试与 DOM 输出断言回归。
