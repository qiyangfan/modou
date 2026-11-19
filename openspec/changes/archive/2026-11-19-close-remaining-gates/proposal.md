# 提案：收口剩余门禁（spec / 打包 / 警告 / 配置范围 / workflow 安全）

## Why

逐项复核后发现五处未被任何门禁覆盖的真实缺口：

1. openspec 变更与规格只在本地手工校验，CI 不跑；
2. 发布物从未在 CI 构建，wheel 缺 UI 资源不会被发现；
3. pytest 警告不失败，弃用 API 与资源泄漏可长期潜伏；
4. yamllint 只扫 `.github/workflows` 等三个文件，漏掉 `openspec/**`、
   `examples/ci/pack-gate.yml`、`.yamllint.yml`；Prettier 也漏掉根级与 openspec YAML；
5. workflow 动作全部按 tag 引用，无 SHA 固定，也无 workflow 安全分析。

## What Changes

- CI `workflows` 作业：`npx --yes @fission-ai/openspec@1 validate --all --strict`
  （实测 24 项全过）。
- CI `core` 作业：`uv build` 后断言最新 wheel 含 `modou/ui/dist/` 资源
  （实测 3 个资源）；`AGENTS.md` 给出等价本地命令。
- `[tool.pytest.ini_options] filterwarnings = ["error"]`（实测 497 passed 无警告）。
- yamllint 范围扩为 `.github openspec examples/ci/pack-gate.yml
.pre-commit-config.yaml .yamllint.yml`；`.yamllint.yml` 的
  `comments.min-spaces-from-content` 对齐 Prettier（1 空格）。
- Prettier 文档范围补 `openspec/**/*.yaml`、`examples/ci/*.yml`、
  `.pre-commit-config.yaml`、`.yamllint.yml`。
- 两个 workflow 的 11 处动作引用全部固定到提交 SHA，并统一
  `persist-credentials: false`；`ci.yml` 补顶层 `permissions: contents: read`。
- 新增 zizmor 1.32（dev 依赖），CI 与 pre-push 执行 `uv run zizmor .github/workflows`；
  实测 0 findings。

## 不做清单（Non-goals）

- 不把示例 workflow 的动作固定 SHA：`examples/ci/pack-gate.yml` 是给使用方的
  模板，保持可读的 tag 引用。
- 不启用 CodeQL：需要 GitHub 托管 SARIF 与 Actions 配额，当前账单尚未恢复。
- 不做浏览器级 UI 测试/视觉回归：现有 jsdom 用例覆盖 DOM 断言，真实浏览器
  e2e 属测试能力建设，另行评估。

## 验证

- 正向：openspec 24 passed；`uv build` + wheel 断言通过；pytest 497 passed、
  覆盖率 80.91%；yamllint 0；Prettier 全过；zizmor 0；actionlint 0。
- 负向：临时把 checkout 改回 `@v7` → zizmor `unpinned-uses` EXIT=1；撤销后 EXIT=0。
