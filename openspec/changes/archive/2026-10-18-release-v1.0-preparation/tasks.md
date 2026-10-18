# 任务：v1.0 对外发布准备

## 1. 版本定版与发布物（P1）

- [x] 1.1 pyproject version 0.1.0 → 1.0.0
- [x] 1.2 `uv build` 产出 sdist + wheel。**过程中发现并修复分发缺陷**：sdist
      不含 ui/dist（构建产物不入 git），下游从 sdist 构建 wheel 时 force-include
      必失败——pyproject 增 `[tool.hatch.build.targets.sdist.force-include]`。
      修复后验证：sdist→wheel 构建链路通（uv "wheel from source distribution"）；
      wheel 内 ui/dist 3 文件 + skills 资产 + METADATA Version 1.0.0；干净
      Python 3.13 venv 安装 wheel：CLI 可用、ui/dist 与 SKILL.md 资产可解析；
      requires-python >=3.12 元数据正确拒绝 3.9（负路径实测）

## 2. 双语 README（P2）

- [x] 2.1 README.md 重写：去除"立项阶段"过时口径；补安装（uv tool install /
      uvx / 源码）、五分钟上手、四车道 × 三表面总览、文档索引、案例入口、
      双语互链；技术栈表述修正（testcontainers → podman/docker CLI）
- [x] 2.2 README.en.md 新增：与中文版对等的英文版，顶部互链

## 3. 文档齐备（P2）

- [x] 3.1 docs/quickstart.md：四车道最小链路（verify 退出码契约、采样口径、
      patrol 四子命令、文档互引）
- [x] 3.2 docs/changeset-spec.md：V 命名/manifest 校验/DELIMITER 复位守卫/
      多库 USE 约定/pack 预警三态/stdout 纯净口径/只增不改交付纪律/退出码表
      （与 formats.md 冻结口径核对一致）

## 4. 案例两个（P3，命令输出为本机影子库真实运行结果）

- [x] 4.1 案例一 examples/changeset-demo/README.md：交棒漏执行验收端到端——
      构造漏执行 V03/V04 → verify 指认 idx_user_amount 与 sp_order_count 漏执行、
      退出码 1 实测（真实报告全文摘录，含打包预警三态、中文注释 round-trip 口径）
- [x] 4.2 案例二 examples/optimize-demo/（setup.sql + slow-sql.sql + README.md）：
      5 万行确定性合成数据 + 采样 5000 → optimize 两语句——语句一 [实测提升 39.4%]
      （17.50 → 10.61）+ 语句二 [未验证]（实证关拦下教科书建议），两级状态真实
      输出；迭代过程：LIMIT 查询与 5000 行数据均无法显现代价差异（影子库按采样
      统计估价），素材按 e2e 测试实证过的形态调整（无索引列查询 + 采样放大）
- [x] 4.3 两案例均注明诚实口径：合成场景 + 本机影子库真实输出，零生产数据；
      案例二附完整本地复现脚本（容器起/灌/采/析/焚）

## 5. 收口（P4）

- [x] 5.1 HANDOFF 更新：待确认 2 条裁决落字（均不做，状态转「已裁决关闭」）；
      「未完成」v1.0 项标注交付边界（发布物就绪，uv publish 待凭据）
- [x] 5.2 全门禁：uv 三连 + CLI 冒烟 + ui 门禁 + `openspec validate --strict`
- [x] 5.3 发布清单留痕（凭据就绪后按单执行）：
      ① `cd ui && npm run build`（force-include 硬前置）；
      ② `uv build`（sdist + wheel，双双含 ui/dist——sdist force-include 已修）；
      ③ 核对 `dist/modou-1.0.0*` 产物（本 change 1.2 已验：wheel 内 ui/dist 3 文件
      + skills 资产 + METADATA Version 1.0.0，干净 venv 安装 CLI/资产可解析）；
      ④ `uv publish --token <PYPI_TOKEN>`（PyPI 名 `modou` 已确认可用，2026-10-18）；
      ⑤ 发布后验证 `uv tool install modou` + `modou --help` + `modou ui` 报告渲染；
      ⑥ 打 git tag `v1.0.0`（等 owner 指令）
