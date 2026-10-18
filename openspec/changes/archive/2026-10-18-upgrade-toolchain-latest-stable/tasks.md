# 任务：技术栈升级至最新稳定版

## 1. Python 侧（P0）

- [x] 1.1 `uv lock --upgrade` 刷新依赖锁（实际带入：fastmcp 4.1.1 / ruff 0.17.1 /
      sqlglot 30.23.0 / pluggy 1.7.0 / platformdirs 4.13.4 / cachetools 7.2.3 /
      fastmcp-slim 4.1.1）；uv.lock diff 核对仅版本刷新、零新增依赖
- [x] 1.2 pyproject cryptography 行加注释：pymysql caching_sha2_password（MySQL 8
      默认认证）运行时伴随依赖，源码零 import，禁止误删
- [x] 1.3 全门禁：`uv run ruff format --check .` + `uv run ruff check .` +
      `uv run pytest`（494 passed + 33 skipped，skip 全为影子门禁）+ `uv run modou --help`

## 2. UI 工具链（P1，每步跑 ui 门禁后再进下一步）

- [x] 2.1 vitest 5.0.5 + jsdom 30.1.3 + vite 8.3.4：21 用例全绿，零适配
      （vite peer-dep 前置已满足；无快照测试，reporter/pretty-format 变化无影响）
- [x] 2.2 eslint 10.13.0 + typescript-eslint 8.71.2：flat config 零适配，
      lint 零告警
- [x] 2.3 typescript 6.0.3：typescript-eslint 兼容实证（lint 零告警），
      `tsc --noEmit` 零适配通过；typecheck + test 全绿
- [x] 2.4 构建链路回归：`npm run build` 产出 ui/dist 后 `uv sync` editable
      走 force-include 同路径成功，Python 全门禁全绿

## 3. CI 与文档（P2）

- [ ] 3.1 CI 两 job node-version 24→26（.github/workflows/ci.yml；**执行条件：
      2026-10-28 Node 26 进入 LTS 之后**；与 ui/@types/node ^26 对齐）
      【2026-10-18 执行轮搁置：日历条件未触发，非技术阻塞；条件满足后单独执行】
- [x] 3.2 ADR-0006 增修订记录：容器编排 testcontainers → 手搓 podman/docker CLI
      的事实修订（理由 + 日期）；UI 工具链基线入档（eslint 10 / vitest 5 /
      TS 6；TS 7 待 7.1 稳定编程 API 后另评）
- [x] 3.3 astral-sh/setup-uv action 版本刷新（v10.0.1 → v10.3.0，同 major 线）
- [x] 3.4 收口全门禁：uv 三连 + `modou --help` + ui typecheck/lint/test +
      `openspec validate --strict`（change 与 specs 7 项全过）；冒烟走查：
      回环起服务加载 lint/optimize 样例报告——首页 200、`/api/reports`
      对象形契约正确、kind/version 门禁通过
