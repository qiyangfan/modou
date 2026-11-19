# 任务：CodeQL 语义 SAST

## 1. 接入

- [x] 1.1 `.github/workflows/codeql.yml`（两语言矩阵、`build-mode: none`）
- [x] 1.2 `.github/codeql/codeql-config.yml`（排除构建产物与依赖）
- [x] 1.3 动作固定 SHA、权限最小化
- [x] 1.4 actionlint / zizmor / yamllint 零告警

## 2. 本地基线（下载受限，未完成）

- [ ] 2.1 CodeQL CLI 建 Python 库并跑 `security-extended`
- [ ] 2.2 CodeQL CLI 建 JS/TS 库并跑 `security-extended`
- [ ] 2.3 按规则/严重度统计结果并写入 HANDOFF
      （bundle 879MB、实测约 0.27MB/s，代理无提速；改由 CI 首跑建立基线）

## 3. 收尾

- [ ] 3.1 Actions 恢复后首跑，核对结果与本地基线一致
- [ ] 3.2 基线甄别完成后，决定是否设为 required check 并归档本 change
