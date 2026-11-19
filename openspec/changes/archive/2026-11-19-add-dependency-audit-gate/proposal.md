# 提案：依赖漏洞扫描门禁

## Why

此前安全门禁只覆盖密钥泄露，第三方依赖漏洞没有任何机械检查。补测时实测发现 5 个
真实漏洞（fastmcp 4.1.1 两条、dnspython 2.9.0、joserfc 1.7.5、opentelemetry-api
1.45.1），UI 侧 `npm audit` 也有 9 条 moderate——全部为当时已存在、CI 不会报的缺口。

## What Changes

- Python：dev 依赖加 `pip-audit`；CI `security.yml` 新增 `audit` 作业执行
  `uv run pip-audit --skip-editable`（本项目为可编辑安装，PyPI 无发布物，跳过自身）。
- Node：CI 同一作业执行 `npm ci --prefix ui` 后 `npm audit --prefix ui --audit-level=high`。
- 依赖修复：`uv lock --upgrade-package opentelemetry-api …` 后 0 漏洞；
  `npm audit fix` 升级 eslint 10.15.0 / typescript-eslint 8.73.0 / minimatch 11.0.9 后
  moderate 清零。
- 新增 `.github/dependabot.yml`：pip、npm（/ui）、github-actions 每周检查更新；
  Bot 是否启用属仓库设置（owner 动作），门禁本身不依赖它。
- `AGENTS.md` 门禁清单同步两条命令。

## 不做清单（Non-goals）

- 不阻断 low 级 Node 告警：当前残余 4 条 low 来自 markdownlint 上游传递依赖，
  上游未发修复版；`--audit-level=high` 是明确的失败线，残余项在 HANDOFF 留证。
- 不审计本仓库自身包（`modou`），审计目标只有第三方依赖。
- 不引入 Snyk/Sonar 等外部平台扫描（零平台化红线）。

## 风险

- 漏洞库更新会让门禁突然变红：处理方式是升级依赖，不加忽略列表。
- `npm audit` 输出随 registry 变化：CI 固定 `npm ci` 锁定依赖树。
