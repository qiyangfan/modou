# 提案：依赖卫生门禁（deptry）

## Why

pip-audit 只查漏洞，不查依赖声明与代码实际使用是否一致：删代码后残留的依赖、
漏声明的直接依赖、只在测试里用到的生产依赖都无人拦截。实测 deptry 0.25.1 在
配置第一方包后仅剩 `cryptography` 一条——它由 PyMySQL 在运行时按认证插件加载，
代码中无直接导入。

## What Changes

- dev 依赖增 `deptry>=0.25.1`。
- `[tool.deptry]`：`known_first_party = ["modou"]`；`DEP002` 按模块忽略
  `cryptography`（运行时认证插件依赖，非直接导入）。
- CI core 作业新增 `uv run deptry .`；pre-push 钩子同命令。
- `AGENTS.md` 门禁清单同步。

## 不做清单（Non-goals）

- 不做依赖许可证合规扫描（仓库已声明 Apache-2.0，逐依赖许可证策略未定）。
- 不做依赖版本新鲜度检查（upgrade 决策不属于门禁）。

## 验证

- 负向：临时把 `requests` 写入 dependencies → `DEP002` EXIT=1；移除后 EXIT=0。
- 正向：`uv run deptry .` 0 问题；UI 依赖由 knip 覆盖，不重复扫描。
