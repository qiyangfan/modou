# 提案：配置与文本门禁（YAML/TOML/拼写/行宽）

## Why

workflow 之外没有任何 YAML 语义检查，TOML 没有格式校验，拼写错误无人拦截；
markdownlint 的 `MD013` 也一直关着。实测发现 16 处拼写不一致、
`.gitleaks.toml` 与 `pyproject.toml` 未按 TOML 规范排版、两条 Markdown 长行超限。

## What Changes

- `.yamllint.yml`（extends default）：
  - `document-start` 关闭（GitHub workflow 惯例省略）；
  - `truthy.check-keys` 关闭（workflow 的 `on:` 键是规范要求）；
  - `line-length.max` 160（长 URL 与单行命令）。
- yamllint 进 CI 与钩子，覆盖 `.github/workflows`、`dependabot.yml`、
  `.pre-commit-config.yaml`。
- taplo 0.10.0（CI 固定下载）对 `pyproject.toml`、`.gitleaks.toml` 执行
  `fmt --check` 与 `lint`；两文件已按 taplo 默认风格排版。
- codespell 2.4.3 + `.codespellrc`；正文拼写统一为 `unparsable`；
  `pack_warnings.kind` 的 `unparseable` 是既有报告契约值，保留并加入忽略表。
- markdownlint `MD013` 启用：行宽 120，表格/代码块/标题不参与；两条超长正文已折行。
- `MD041` 仍关闭：openspec delta 文件按规范以 `## ADDED Requirements` 开头。

## 不做清单（Non-goals）

- 不启用 `MD013.tables`：中文表格列宽由内容决定，强制折行会破坏可读性。
- 不引入 markdown 链接外网可达性检查（离线环境不可用）。
- 不对 TOML 做 schema 校验（taplo lint 只校验语法）。

## 验证

- 负向：YAML 缩进错误 EXIT=1；未格式化 TOML EXIT=1；拼写探针 EXIT=65；
  超 120 字长行 → `MD013` EXIT=1；探针移除后全部 EXIT=0。
- 正向：yamllint 0；taplo fmt/lint 0；codespell 0；markdownlint 94 文件 0 issues。
