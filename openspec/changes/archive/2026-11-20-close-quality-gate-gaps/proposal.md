# 变更提案：质量门禁缺口收口（Python 安全 + 供应链 + UI）

## Why

门禁盘点上墨斗是六仓里最薄的一档：Ruff 未启用 bandit 规则、pytest 无超时、覆盖率阈值只
写在 CI、没有 SBOM/许可证门禁、UI 无体积预算与 e2e。供应链与测试面都需要补齐。

## What Changes

1. **Ruff `S`（bandit）**：启用并对存量逐条修复或带原因 noqa；tests 按惯例放行 S101/S105/S106/S107。
2. **pytest**：`timeout=300`、`filterwarnings=error` 保留；覆盖率配置移入 pyproject，阈值取
   实测基线（80%）。
3. **供应链**：security.yml 增 osv-scanner、syft SBOM（CycloneDX）、grant 许可证检查
   （`.grant.yaml` 默认 deny-all）。
4. **UI**：size-limit（实测 4.56 kB brotli / 8 kB 上限）、Playwright 壳层冒烟 + axe。

## Non-goals

- 不改回放/快照/优化业务语义。
- 不引入平台化或外部服务。

## Impact

- 门禁与测试文件；`src/modou` 仅做安全规则要求的等价改写。
