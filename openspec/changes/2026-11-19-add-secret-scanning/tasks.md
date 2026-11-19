# 任务：P0-1 Secret scanning（gitleaks 阻断门禁）

## 1. 实现

- [x] 1.1 新增 `.gitleaks.toml`：`extend` 默认规则 + 路径级 allowlist
      （`tests?/fixtures/`、`docs/**.md|png|jpg`）；本仓无额外路径豁免
- [x] 1.2 新增 `.pre-commit-config.yaml`：gitleaks `v8.30.1` 钩子
- [x] 1.3 新增 `.github/workflows/security.yml`：独立 `secrets` job
- [x] 1.4 `.github/workflows/ci.yml` 的 `astral-sh/setup-uv` 由 `v10.3.0`
      对齐至 `v10.3.3`（handoff §5.0 基准；存量不一致项同 PR 对齐）

## 2. CI 落点

- [x] 2.1 安全作业独立于 `ci.yml`（无路径过滤、无 `continue-on-error`）；
      `actions/checkout@v7` + `fetch-depth: 0`；gitleaks 固定 8.30.1
- [ ] 2.2 推送后在 GitHub Actions 首跑核对 `security / secrets`（需 owner
      授权推送；本地无法触发）

## 3. 负向验收（2026-11-19，本机 gitleaks 8.30.1）

- [x] 3.1 干净树全绿：`detect`（git 历史 12 commits / 1.46 MB）零命中
      EXIT=0；`detect --no-git`（工作树 2.72 MB，含本 change 新文件）零命中
      EXIT=0
- [x] 3.2 植入违规必须非 0：`leak-probe.txt` 写入高熵假 AWS 键
      （形如 `AKIA…`，非 gitleaks allowlist 的 EXAMPLE 样例）+ 假 secret，
      `detect --source . --no-git
      --redact --verbose --exit-code 1` 报 2 处（`aws-access-token` /
      `generic-api-key`），EXIT=1
- [x] 3.3 移除后恢复：删除 `leak-probe.txt` 重跑，零命中 EXIT=0
- [x] 3.4 CI 原命令等价验证：临时克隆仓库并提交同一假键，按 CI 原命令
      `gitleaks detect --source . --redact --verbose --exit-code 1` 扫描
      13 commits，报 2 处，EXIT=1（临时目录已删除，本仓无提交）
- [x] 3.5 仓库门禁：`uv run ruff format --check .`、`uv run ruff check .`、
      `uv run pytest -q`、`uv run modou --help` 全绿（输出见本仓 HANDOFF）
- [x] 3.6 `openspec validate 2026-11-19-add-secret-scanning --strict` 通过

## 4. 分支保护 required

- [ ] 4.1 推送合并后把 `security / secrets` 设为 required check
      （owner 在 GitHub 仓库设置执行；个人账号下无仓外统一执法通道）

## 5. 归档

- [ ] 5.1 上述 required 生效后 `openspec archive 2026-11-19-add-secret-scanning`
