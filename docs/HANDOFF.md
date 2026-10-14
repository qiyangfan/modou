# HANDOFF — modou

## 现状（2026-10-14）

治理层全量就位：宪法（openspec/project.md，六条红线）、目标体系（docs/goals.md）、
ADR 0001~0008、AGENTS.md（门禁单源）、CI（core 门禁 + ui Node 24 预留 job）、
首个 change 提案（changeset-verify 纵切面，含 spec delta 与任务清单）。
代码为 CLI 空壳（`modou version`）+ 冒烟测试，无业务代码，无 git 提交（owner 未指示提交）。

## 口径

- 名字读作**墨斗**（木匠弹线工具），非"魔豆"。
- 决策单源在 docs/adr/；架构事实在 architecture.md；竞品数据快照在 research-2026-10.md
  （引用前复核时效）。
- 门禁单源在 AGENTS.md（ruff format/check + pytest + CLI 冒烟），CI 同款。

## 未完成（按优先级）

1. **原型真值验证一（变更车道）**：真实迭代 SQL 目录 + 本地容器 MySQL（podman，参考
   timestamp-tz-demo 的容器经验），跑通"快照灌入 → 回放 → 三方 diff"，人工构造漏执行须被抓到。
2. **原型真值验证二（优化车道）**：影子库建建议索引 → EXPLAIN 前后对比 → 代价未降自动标"未验证"。
3. 两条链路验证通过后再铺 v0.1 正式代码（changeset/replay/diff 模块）。

## 常见坑（已知，待原型验证后增补）

- 快照 round-trip 保真：字符集/collation 继承、存储过程、触发器、生成列——回放 diff 若报假差异，
  先怀疑快照灌入失真，再怀疑变更集本身。
- MySQL 无 HypoPG：索引实证只能真建，大表注意影子库灌入耗时（必要时采样子集）。

## 可复现

```bash
cd ~/workspace/longzhong/modou
uv sync                 # 安装依赖（生成 uv.lock 与 .venv）
uv run pytest           # 冒烟测试
uv run modou version    # CLI 冒烟
```
