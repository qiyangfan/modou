# 提案：P0-1 Secret scanning（gitleaks 阻断门禁）

## Why

跨仓质量门禁 handoff（`../QUALITY-GATES-HANDOFF.md` §2 P0-1、§5 批次 1）要求六仓
先落 secret scanning——成本最低、风险最高。本仓当前没有任何 secret 扫描：CI 只有
ruff/pytest/UI 三个作业，凭证泄漏只能靠人工发现。

基线实测（2026-11-19，gitleaks 8.30.1）：

- `gitleaks detect --source .`：12 commits、约 1.46 MB，零命中；
- `gitleaks detect --source . --no-git`：工作树约 2.82 MB，零命中。

因此不存在历史清洗与规则豁免需求，无需 `.gitleaksignore`。

## What Changes

- 新增 `.gitleaks.toml`：`extend` 默认规则 + 路径级 allowlist（测试夹具、文档）；
  禁止规则级全局放行；本仓无额外路径豁免。
- 新增 `.pre-commit-config.yaml`：gitleaks `v8.30.1` 本地前置钩子（Python 仓
  直接复用 pre-commit，不引入 husky）。
- 新增 `.github/workflows/security.yml`：独立 `secrets` job，`actions/checkout@v7`
  且 `fetch-depth: 0`，下载固定版本 gitleaks 8.30.1，
  `gitleaks detect --source . --redact --verbose --exit-code 1` 阻断。
  不并入按路径/条件裁剪的 `ci.yml`，避免安全作业被跳过。
- `.github/workflows/ci.yml`：`astral-sh/setup-uv` `v10.3.0 → v10.3.3`。
  handoff §5.0 要求新增 workflow 按基准表钉版本、存量不一致项在同一 PR 内对齐
  （同 minor 线，行为不变）。
- 负向验收：植入假 AWS 密钥 → 扫描非 0；移除后恢复 0（证据见 tasks.md）。
- 分支保护：`security / secrets` 设为 required（需 owner 推送并在 GitHub
  仓库设置中完成，本地不可代劳）。

## 受影响决策

- 不触碰 ADR-0001~0009：本变更只改 CI/工具链，无产品语义、无运行行为、无架构变化。
- 门禁类改动走 skip_specs：不新增或修改产品规格。
- 与宪法红线 4「数据不出本地」不冲突：gitleaks 只读仓库文件，不接触数据库
  schema、SQL 文本或慢日志；不引入任何联网扫描服务。

## 不做清单（Non-goals）

- 不做 P0-2 依赖漏洞、P0-3 CodeQL、P0-4 SBOM/许可：一类门禁一个 PR，按
  handoff §5 批次顺序推进。
- 不写 `continue-on-error`、`|| true`，不做规则级全局豁免，不批量
  `gitleaks:allow`。
- 不做历史提交清洗（基线零命中）；不引入 gitleaks-action 或任何 SaaS 扫描。
- 不在 pre-commit 中扩展 ruff/format 钩子（§4 P2 统一项，留后批）。
- 不改任何产品行为与退出码语义。

## 风险

- gitleaks 版本固定 8.30.1，不随 latest 漂移；升级须单独 change 并重跑负向验收。
- 误报处理只允许路径级 allowlist，并逐条写原因；若出现规则级噪声，优先把值
  改成明确的假值。
