# 提案：覆盖率门禁（pytest-cov，阈值 80%）

## Why

本仓测试数量稳定（497 passed），但没有覆盖率下限，新增未测代码不会触发失败。
离线实测（33 个集成用例默认跳过）覆盖率 80.82%；80% 是业界常用阈值，且当前有
0.8 个百分点余量。

## What Changes

- dev 依赖增 `pytest-cov`。
- CI core 作业把测试步骤改为
  `uv run pytest -q --cov=modou --cov-report=term --cov-fail-under=80`。
- `AGENTS.md` 门禁清单同步。
- 不使用 `[tool.coverage]` 全局 `addopts`：覆盖率只在门禁命令生效，定向跑单个
  测试目录时不会因全局覆盖不足误报失败。

## 不做清单（Non-goals）

- 不设 UI 覆盖率门禁：UI 已有 vitest 用例与 DOM 断言，覆盖率度量未纳入本批。
- 不做按文件覆盖率门槛、不豁免任何模块。
- 不覆盖默认跳过的容器集成用例（需 `MOUDO_TEST_SHADOW=1`）。

## 风险

- 新增代码若缺测试会直接卡住 CI：这是门禁目标；离线基线 80.82%，余量 0.8pt。
- 集成用例在 CI 跳过：阈值按离线口径设定，开影子库后覆盖率只会更高。
