# 提案：workflow 静态检查（actionlint）

## Why

`.github/workflows/` 下的 workflow 此前只靠 YAML 解析与 Actions 实跑验证；表达式
错误、`needs` 引用错误、事件载荷字段错误等在运行前不可见。actionlint 是 GitHub
Actions 的主流静态检查器，默认配置自带表达式类型检查，并在 runner 上调用
shellcheck 检查 `run:` 脚本。

## What Changes

- CI 新增独立作业 `workflows`：下载固定版本 actionlint（v1.7.12，linux_amd64），
  以默认配置扫描 `.github/workflows/*.yml`。
- `AGENTS.md` 门禁清单增 `actionlint .github/workflows/*.yml`。
- 本机安装方式：Homebrew 已有 1.7.12；无 Homebrew 时用
  `mise install actionlint@1.7.12`（uvx 无此工具）。
- 不新增配置文件、不加参数：直接使用 actionlint 默认规则。

## 不做清单（Non-goals）

- 不扫描 `examples/ci/*.yml` 与 `.pre-commit-config.yaml`：本批只约束 CI workflow。
- 不引入 reviewdog/PR 注解集成。
- 不安装 shellcheck 到 CI：GitHub ubuntu runner 自带，与本地一致。

## 风险

- actionlint 版本升级需同步 CI 下载地址与本地版本；已固定 v1.7.12。
- shellcheck 版本由 runner 提供，个别规则随 runner 镜像变化：出现新告警按代码
  修复，不加 actionlint 忽略。
