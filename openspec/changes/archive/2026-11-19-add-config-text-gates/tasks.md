# 任务：配置与文本门禁（YAML/TOML/拼写/行宽）

## 1. 接入

- [x] 1.1 `.yamllint.yml` + CI/钩子（workflows、dependabot、pre-commit 配置）
- [x] 1.2 taplo 0.10.0：CI 固定下载 + `fmt --check` / `lint`
- [x] 1.3 codespell + `.codespellrc`；正文统一为 `unparsable`，
      `pack_warnings.kind` 契约值 `unparseable` 加入忽略表
- [x] 1.4 markdownlint `MD013` 启用（120，表格/代码块/标题豁免）
- [x] 1.5 `AGENTS.md`、`ci.yml`、`.pre-commit-config.yaml` 同步

## 2. 验证

- [x] 2.1 负向（YAML）：缩进错误探针 → EXIT=1；移除后 EXIT=0
- [x] 2.2 负向（TOML）：`[a]\nb=1` 探针 → `fmt --check` EXIT=1
- [x] 2.3 负向（拼写）：拼写探针 → EXIT=65；移除后 EXIT=0
- [x] 2.4 负向（行宽）：超 120 字符正文探针 → `MD013` EXIT=1；移除后 EXIT=0
- [x] 2.5 正向：yamllint 0 / taplo 0 / codespell 0 / markdownlint 94 文件 0 issues

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对 `ci / core`、`ci / workflows`
- [ ] 3.2 全绿后归档本 change
