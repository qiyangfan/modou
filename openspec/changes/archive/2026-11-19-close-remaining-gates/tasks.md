# 任务：收口剩余门禁

## 1. 接入

- [x] 1.1 CI spec 门禁：`openspec validate --all --strict`
- [x] 1.2 CI 打包门禁：`uv build` + wheel 含 UI 资源断言
- [x] 1.3 pytest `filterwarnings = ["error"]`
- [x] 1.4 yamllint / Prettier 范围补齐（openspec、examples、根级配置）
- [x] 1.5 workflow 动作固定 SHA、`persist-credentials: false`、顶层权限
- [x] 1.6 zizmor 进 dev 依赖、CI 与 pre-push
- [x] 1.7 `AGENTS.md`、`ci.yml`、`.pre-commit-config.yaml` 同步

## 2. 验证

- [x] 2.1 openspec `--all --strict` 24 passed
- [x] 2.2 `uv build` + 最新 wheel 含 3 个 `modou/ui/dist/` 资源
- [x] 2.3 pytest 497 passed / 33 skipped，覆盖率 80.91%，无警告
- [x] 2.4 yamllint 0；Prettier 全过；actionlint 0
- [x] 2.5 负向：临时 `uses: actions/checkout@v7` → zizmor EXIT=1；恢复后 EXIT=0

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对 `ci / core`、`ci / workflows`
- [ ] 3.2 全绿后归档本 change
