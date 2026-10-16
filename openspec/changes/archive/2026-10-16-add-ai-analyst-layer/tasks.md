# 任务：AI 分析师层（v0.5）

## 1. 决策与文档面（本 change 完成）

- [x] ADR-0009 成文；ADR-0003 标注 AI 职责面部分取代；ADR 索引更新
- [x] 宪法红线 1/4 改写（AI 当分析师 + 委托面零密钥）；工程口径增评测纪律
- [x] openspec/config.yaml 口径同步（ADR-0001~0009、红线表述）
- [x] architecture.md 增"AI 分析师层"章节、模块地图 `ai/`、车道矩阵 AI 列
- [x] goals.md 增 v0.5 里程碑与验收判据
- [x] 竞品事实库增补 alibaba/open-code-review 调研节

## 2. P0——结论分级契约与委托面（零密钥）

- [x] 测试先行：报告"AI 观点"区契约——单列、来源标注、退出码不受影响；
      未配置时无该区且行为与 v0.4 一致（契约测试）
- [x] MCP 证据原语工具扩列（快照摘要/回放验收/三方 diff/EXPLAIN/lint 命中），
      与 CLI 机读出口 parity（parity 清单扩列，测试先行）
- [x] skills 资产：数据库变更评审工作流模板随包分发（纯文本，零依赖）
- [x] 委托面演示链路：宿主 Agent 仅凭 MCP 工具完成"变更集 → 影子库验收 →
      报告解读"（冒烟记录入 docs/HANDOFF.md）

## 3. P1——`ai/` 模块与 BYOK 内置分析（受控多轮）

- [x] 测试先行：schema 切片器——按语句触达裁剪、token 预算上限、边界（无 schema 触达）
- [x] 测试先行：变更分包器——按库/语句组分包、并发单轮聚合
- [x] 测试先行：规则注入器——lint 命中清单模板化注入
- [x] BYOK 客户端自 optimize/advisor.py 演进收拢进 `ai/`（行为不变，现有测试守护）
- [x] lint 残留语义评审：规则引擎后残留语句 → AI 观点；未配置零网络回归证明；
      调用失败 fail-safe 降级（测试先行）
- [x] verify 失败归因解释进 AI 观点区（测试先行）
- [x] patrol 跨信号综合叙事进 AI 观点区（测试先行）

## 4. P2——optimize 受控多轮与评测

- [x] optimize 顾问升级：EXPLAIN 事实预取打包（受控多轮；实证关与副作用检查不变，
      现有测试守护）
- [x] 评测集入库：lint 残留评审正反例抽样 + 首版精度数字
      （数字待 BYOK 实测：门禁已就位，owner 配端点跑一次即回写——HANDOFF 待确认第 3 条）
- [x] 评测回归接入门禁：提示词/模板/切片变更必跑评测

## 5. 验收

- [x] 全门禁绿：`uv run ruff format --check . && uv run ruff check . && uv run pytest`；
      `uv run modou --help` 冒烟
- [x] 手工冒烟记录：未配置 BYOK 全车道行为与 v0.4 一致；委托面演示链路留痕
      （docs/HANDOFF.md）
