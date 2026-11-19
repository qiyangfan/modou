# 提案：文档与根级配置校验

## Why

根目录文档与配置此前不在任何门禁里：Prettier 只在 `ui/` 内运行，`docs/`、双 README、
`openspec/` 既不格式化也无 Markdown 规则检查；实测首次扫描有 29 个文件格式不符、
10 处代码块缺语言标记。

## What Changes

- `markdownlint-cli2@0.24.1`（UI dev 依赖）+ `ui/.markdownlint-cli2.jsonc`：
  扫描 README、AGENTS、`docs/**/*.md`、`openspec/**/*.md`；脚本 `docs:check`。
- `docs:format:check`：Prettier 检查根级 Markdown、`.github/**/*.yml`（含
  dependabot.yml）与 `openspec/**/*.md`。
- 全量格式化一次（Prettier 重排 29+ 个文件），并给 10 处无语言代码块补 `text`
  （AGENTS 1、architecture 4、changeset-spec 3、demo-agent 1、历史 design 1）。
- `ci.yml` 的 ui 作业接入两条脚本；`AGENTS.md` 门禁清单同步。

## 配置取舍

- `MD013`（行宽）关闭：中文文档无空格分词，Prettier 又保持段落原样，行宽只会产生噪音。
- `MD041`（首行须 H1）关闭：openspec delta 文件按规范以 `## ADDED Requirements` 开头。
- 其余规则全部使用 markdownlint 默认值。

## 不做清单（Non-goals）

- 不格式化 TOML：Prettier 不支持，`pyproject.toml` 由人工维护。
- 不引入文档链接外网校验：离线环境不可用，链接有效性靠评审。

## 风险

- Prettier 重排会产生一次大 diff：已验证 `openspec validate --specs --strict` 仍通过。
- 新文档必须同时满足 Prettier 与 markdownlint：两者冲突时以 Prettier 为准并复跑。
