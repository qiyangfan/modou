# 任务：依赖漏洞扫描门禁

## 1. 接入

- [x] 1.1 dev 依赖加 `pip-audit`（`uv add --dev pip-audit`）
- [x] 1.2 `security.yml` 增 `audit` 作业：pip-audit + npm audit（high 及以上）
- [x] 1.3 新增 `.github/dependabot.yml`（pip / npm / github-actions，weekly）
- [x] 1.4 `AGENTS.md` 门禁清单同步

## 2. 修复与验证

- [x] 2.1 首次实测 5 漏洞：fastmcp 4.1.1×2、dnspython 2.9.0、joserfc 1.7.5、
      opentelemetry-api 1.45.1
- [x] 2.2 升级后 `uv run pip-audit --skip-editable` → `No known vulnerabilities found`，EXIT=0
- [x] 2.3 `npm audit fix` 后 moderate 清零；残余 4 条 low（markdownlint 传递依赖）
- [x] 2.4 负向验收（Python）：`pip-audit -r` 指向 `jinja2==2.8` →
      `Found 14 known vulnerabilities in 1 package`，EXIT=1
- [x] 2.5 负向验收（Node）：临时目录安装 `lodash@4.17.15` →
      `1 high severity vulnerability`，`--audit-level=high` EXIT=1

## 3. 收尾

- [ ] 3.1 推送后 Actions 首跑核对 `security / audit`（账号欠费锁定，待恢复后重跑）
- [ ] 3.2 全绿后归档本 change
