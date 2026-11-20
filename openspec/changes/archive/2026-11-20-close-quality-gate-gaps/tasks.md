# Tasks

## 1. Python 门禁

- [x] 1.1 Ruff `S` 启用，存量修复/定点 noqa；`ruff check .` 0 error
- [x] 1.2 pytest timeout=300、覆盖率阈值 80 进 pyproject；实测 81.45%
- [x] 1.3 509 passed / 33 skipped

## 2. 供应链

- [x] 2.1 security.yml 增 osv-scanner
- [x] 2.2 syft SBOM + grant 许可证检查（`.grant.yaml` / `.syft.yaml`）
- [ ] 2.3 本机 syft/grant 实跑（工具未安装；CI 首次运行验证）

## 3. UI

- [x] 3.1 size-limit 接入（8 kB 上限 / 4.56 kB 实测）
- [x] 3.2 Playwright + axe 壳层冒烟（2 用例通过）
- [x] 3.3 typecheck/lint/format/style/dup/arch/docs/dead/test/size/e2e 全绿
