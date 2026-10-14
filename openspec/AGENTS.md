# openspec — 规格驱动开发（spec-driven）

- `project.md`：**项目宪法**（不可协商红线 6 条 + 工程口径），先于任何编码阅读。
- `config.yaml`：硬约束清单（注入每次 AI 请求的 context 与 rules）。
- `specs/`：主规格（当前 0 能力，随首个 change 归档生成），每能力一个 `spec.md`
  （Purpose + Requirements + Scenario）。归档变更时 delta 在此合并，是行为的唯一权威口径。
- `changes/`：活跃变更（proposal/design/specs delta/tasks 全件）。
  流程：propose（全件 + strict 校验）→ apply（逐任务实现 + 勾选，测试先行）→
  独立评审 → archive（移入 `changes/archive/YYYY-MM-DD-*/`，delta 合并进 specs/）。
- `tasks.md` 全部勾选只表示实现任务完成；归档前仍须门禁全绿并附实证记录
  （回放/diff/优化类改动）。
- 校验：`openspec validate --changes --strict` / `--specs --strict`
  （openspec CLI 经 mise 提供，非交互环境用 `zsh -ic` 或 `mise exec`）。

## 硬规则

- MODIFIED Requirements 必须保留原需求全部 Scenario 名（整块替换，丢场景名 archive 报错）
- proposal 必须含 Non-goals 并引用受影响 ADR；任务粒度 ≤ 2 小时
- 一个 change 一个车道，禁止顺手扩大范围
- Requirement 用 SHALL/SHOULD；Scenario 用 GIVEN/WHEN/THEN；spec 不绑定实现
