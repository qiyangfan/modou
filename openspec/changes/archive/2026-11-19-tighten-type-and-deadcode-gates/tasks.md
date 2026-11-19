# 任务：类型门禁升到 strict，死代码与抑制收口

## 1. 类型

- [x] 1.1 `[tool.mypy] strict = true`
- [x] 1.2 修复 106 个 strict 错误（type-arg 94 / no-any-return 7 / no-untyped-def 2 /
      attr-defined 1 / unused-ignore 2）
- [x] 1.3 `# type: ignore` 11 → 0（sqlglot 定义模块导入、cast、判空）
- [x] 1.4 负向：未注解函数 → `no-untyped-def`，EXIT=1

## 2. 死代码

- [x] 2.1 vulture 2.16（dev 依赖）+ CI/钩子 `--min-confidence 100`
- [x] 2.2 18 处未用 `**kwargs` 改为 `**_`
- [x] 2.3 负向：未用 `**kwargs` 探针 → EXIT=3；移除后 EXIT=0
- [x] 2.4 knip（UI）接入；删除 9 个未用导出；`@commitlint/cli` 计入二进制依赖
- [x] 2.5 负向：未用导出探针 → EXIT=1；移除后 EXIT=0

## 3. 抑制收口

- [x] 3.1 eslint `no-non-null-assertion` 恢复 error；4 处断言改为显式判空
- [x] 3.2 负向：`document.body!` 探针 → EXIT=1
- [x] 3.3 评估 B008：移除后出现 32 处 Typer 框架写法，保留 per-file 忽略并注明理由

## 4. 收尾

- [ ] 4.1 推送后 Actions 首跑核对 `ci / core`、`ci / ui`
- [ ] 4.2 全绿后归档本 change
