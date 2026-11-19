# 提案：CodeQL 语义 SAST（先落地，配额恢复后启用）

## Why

现有安全门禁只有 gitleaks、pip-audit、npm audit、zizmor，均是规则或依赖层；
缺少语义级污点分析。GitHub Actions 配额尚未恢复，但 workflow 与基线可以在本地
先行验证，避免恢复后才发现查询问题与噪声。

## What Changes

- `.github/workflows/codeql.yml`：`push(main)` / `pull_request` / 每周定时，
  `python` 与 `javascript-typescript` 两语言矩阵，`build-mode: none`。
- `.github/codeql/codeql-config.yml`：忽略 `dist`、`ui/dist`、`ui/node_modules`、`.venv`。
- 动作固定提交 SHA（checkout v7、codeql-action v3），权限最小化
  （顶层 `contents: read`，作业级追加 `security-events: write`）。
- 本地尝试用 CodeQL CLI 建库跑基线：macOS 仅有 osx64 bundle（879MB，Rosetta
  可用），实测下载约 0.27MB/s、8 连接无提速、国内代理同样受限，已停止；
  基线改由配额恢复后的 CI 首跑建立，过程记录在 `docs/HANDOFF.md`。

## 不做清单（Non-goals）

- 本次不设为 required check：等配额恢复、首跑基线经甄别后再启用。
- 本次不修 CodeQL 命中的代码：先记录基线，修复另开变更。
- 不覆盖 Go/Java 等仓库不存在的语言。

## 验证

- `actionlint`、`zizmor`、`yamllint` 对新增 workflow 零告警。
- 本地 bundle 下载受限，建库/分析未完成；阻塞与命令已写入 HANDOFF。
- 首跑后把「实跑结果 → 是否转 required」写回 HANDOFF。
