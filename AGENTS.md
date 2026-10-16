# Modou 工作区指引

墨斗（modou）——数据库工程化的本地层：变更验收 · SQL 优化 · 规则审核 · 漂移洞察。
Python 3.12+ 内核（uv 管理），CLI 为体、MCP 为面、本地薄 UI 报告层。
**动手前必读**：[openspec/project.md](openspec/project.md)（宪法红线）与
[docs/architecture.md](docs/architecture.md)（北极星）；改行为前先看
[docs/adr/](docs/adr/) 对应决策，不要凭直觉改架构。

## 目录

```
src/modou/         内核：changeset/ snapshot/ replay/ diff/ optimize/ lint/ patrol/ report/ server/
tests/             单测与容器集成测试（影子库 fixture）
openspec/          spec-driven 工作流：config.yaml 约束 + project.md 宪法 + changes/ 变更提案
docs/              architecture.md（架构）goals.md（目标）adr/（决策）research-2026-10.md（竞品事实库）
.github/           CI：Python 内核门禁 + ui 门禁（Node 24，ui/ 落地前自动跳过）
```

## 门禁（单源，CI 同款，全绿才是完成）

```bash
uv sync                          # 装依赖（首次/依赖变更后）
uv run ruff format --check .     # 格式
uv run ruff check .              # 静态检查
uv run pytest                    # 测试
uv run modou --help              # CLI 冒烟
```

## 代码规范

- Python 3.12+，新增代码必须带类型注解；类型检查（mypy）随 v0.1 铺开时引入 CI。
- 中文注释、中文文档、中文提交信息；日志与 CLI 错误文本用英文。
- sqlglot 是唯一 SQL 解析器，禁止引入第二套解析依赖。
- 回放/diff/优化类任务**测试先行**：先写失败测试再实现（openspec rules 同源）。
- 重依赖（容器编排、AI SDK）只准放 `[project.optional-dependencies]`。
- 业务逻辑只准落在内核库；CLI 与 MCP 表面层只做参数解析与展示（ADR-0002）。

## 红线摘要（全文见宪法）

确定性代码当裁判、AI 当分析师（观点不碰退出码，未过实证关不得称有效）；期望态只能
回放推导；零平台化；数据不出本地（BYOK 未配置不联网，委托面零密钥）；多实例多库
默认；门禁即法律。

## 提交纪律

用户未明确要求时禁止 `git commit`/`git push`（全局铁律）；提交信息中文。
