# 提案：v1.0 对外发布准备——发布物、双语 README、文档齐备、案例两个

## Why

HANDOFF「未完成」第 1 条（v1.0 对外发布）。owner 2026-10-18 授权全盘调研并
决策。调研结论（查证日期 2026-10-18）：

- **PyPI 名字**：`modou` 未被占用（registry 404），发布名定 `modou`，
  `uv tool install modou` 一条命令的承诺成立；
- **发布凭据**：本机无 PyPI 凭据（无 ~/.pypirc / UV_PUBLISH_TOKEN）——本轮把
  发布物准备到位并完成构建验证，**实际上传是凭据就绪后的单独一步**（对外
  不可逆动作不并入本 change）；
- **版本号**：pyproject 0.1.0 与内部能力版本（v0.1~v0.5 全落地、六能力 spec
  归档、报告契约冻结、MCP parity 守护、评测精度 1.0 留痕）脱节——对外定版
  **1.0.0**，语义即「现状冻结」：CLI 表面/报告契约/退出码/MCP 工具清单全部
  只增不改，站得住 1.0 承诺；
- **文档缺口**：快速上手缺、变更集规范缺（口径散在 HANDOFF/formats.md，
  无用户视角文档）、英文 README 缺、中文 README 过时（仍写"立项阶段 2026-10-14"）；
- **案例缺口**：examples/changeset-demo 仅为冒烟素材，无案例叙事；优化车道
  无任何演示素材。

## What Changes

- **版本定版**：pyproject version 0.1.0 → 1.0.0；
- **双语 README**：README.md 重写（去立项过时口径，补安装/五分钟上手/车道
  总览/文档索引）+ 新增 README.en.md（顶部互链）；
- **文档齐备**：新增 docs/quickstart.md（快速上手）与
  docs/changeset-spec.md（变更集规范：V 命名/manifest/DELIMITER 复位/多库
  USE 约定/破坏性预警口径，从 HANDOFF 与 formats.md 提炼为用户文档）；
- **案例两个**：案例一 = examples/changeset-demo 补 README（交棒漏执行验收
  端到端叙事，本机影子库真实命令输出）；案例二 = 新增 examples/optimize-demo
  （合成 orders 场景 + 采样快照 + 慢语句，跑 optimize 全流程记录真实输出）。
  诚实口径：场景为基于仓外参考痛点模式（energy-ai-platform 交棒漏执行）重建
  的脱敏合成数据，命令输出为本机 podman 影子库真实运行结果，案例文档明示；
- **发布物验证**：`uv build` 产出 sdist + wheel，核对 wheel 内 ui/dist 与
  skills 资产随包（force-include 链路）；
- **HANDOFF 收口**：「待确认」2 条裁决落字（均不做，理由见 Non-goals），
  关闭反复上报状态；「未完成」v1.0 项标注本轮交付边界（发布物就绪，上传待凭据）。

## 受影响决策

- ADR-0006：uv 分发决策（`uv tool install modou`）由本 change 兑现发布物侧；
- 不触碰 ADR-0001/0002/0003/0004/0005/0008/0009 与全部红线：案例零真实数据
  （数据不出本地），零行为变化（报告契约/退出码/MCP 表面/CLI 输出不动）。

## 不做清单（Non-goals）

- **不执行 PyPI 实际上传**：本机无凭据，且对外不可逆动作须凭据就绪后单独
  执行（发布命令与核对清单随本 change tasks 留痕）；
- **不做 GitHub Release / CI 发布自动化**：一次性动作不预建工作流（零平台化），
  首次真实发布后再按实际流程留痕；
- **不做 sqlglot 程序体"显式跳过声明"**（HANDOFF 待确认 1，裁决：不做）——
  PARSE.001 warning 披露 + `--skip-rule` 已满足"显式非静默"，无真实痛点证据，
  1.0 冻结期不引入新行为面；
- **不做慢日志 UNION 分支折叠**（HANDOFF 待确认 2，裁决：不做）——spec 未
  要求、实现已覆盖全部要求、同语句聚合稳定；pt-query-digest 完整口径对齐
  出现真实需求再立 delta；
- **不提前 CI Node 26 升级**：维持 2026-10-28 LTS 条件（上一 change 搁置项，
  条件触发后单独执行）；
- **零行为变化**：不改报告契约、退出码语义、MCP 表面、CLI 输出与任何内核
  模块——纯发布准备。

## 顺序与依赖

- P1：版本定版 + 发布物构建验证（其余交付物在仓库内，构建验证先行确认
  分发链路无恙）；
- P2：双语 README → quickstart → changeset-spec（文档三件套相互引用）；
- P3：案例一 → 案例二（案例二需本机 podman 影子库实跑）；
- P4：HANDOFF 收口 + 全门禁收口。
