# MCP 接入与 agent 演示链路

墨斗的 MCP 表面与 CLI 子命令 **1:1 映射**（parity 测试守护，ADR-0002）：每个工具
的参数语义、返回报告与退出码语义字段都与对应 CLI 子命令同源。

## 接入（客户端按需拉起 stdio 子进程）

```bash
uv tool install 'modou[mcp]'     # MCP 表面依赖为可选 extra
```

客户端配置（Claude Code / Cursor / 其他 MCP client）：

```json
{
  "mcpServers": {
    "modou": { "command": "modou", "args": ["mcp"] }
  }
}
```

形态红线：仅本地 stdio，无端口监听、无常驻、无鉴权（ADR-0002 零平台化）。

## 工具清单（与 CLI 同源）

| 工具 | CLI 对应 | 说明 |
|---|---|---|
| `pack` | `modou pack` | 打包变更集 + 破坏性预警 |
| `verify` | `modou verify` | 影子回放 + 三方 diff（返回 `exit_code` 与报告；BYOK 下附失败归因观点） |
| `snapshot_capture` | `modou snapshot capture` | 只读结构快照（可选采样；返回 `summary` 证据摘要） |
| `optimize` | `modou optimize` | 慢 SQL 影子实证优化（BYOK AI 可选，EXPLAIN 事实预取打包） |
| `lint` | `modou lint` | 静态 SQL 规则审核（BYOK 下附残留语句语义评审） |
| `patrol_drift` | `modou patrol drift` | 两方结构漂移 |
| `patrol_unused_indexes` | `modou patrol unused-indexes` | 未用/冗余索引分层判定 |
| `patrol_slowlog` | `modou patrol slowlog` | 慢日志指纹聚合 |
| `patrol_summarize` | `modou patrol summarize` | 跨信号综合摘要（BYOK 下附跨信号叙事） |
| `version` | `modou version` | 版本号 |

`exit_code` 语义与 CLI 一致：0=ok，1=存在差异结论（verify），2=环境或输入错误。
证据原语清单（快照摘要/回放验收/三方 diff/EXPLAIN/lint 命中）冻结在
`server/surface_map.EVIDENCE_PRIMITIVES`，parity 测试守护映射关系；三方 diff 与
EXPLAIN 由 verify/optimize 的报告字段承载，不另设工具。

结论分级：报告中的确定性结论决定 `exit_code`；可选键 `ai_opinions`（或文本报告
的「AI 观点」区）是 BYOK 内置分析的观点，**永不影响退出码**，转述时保留「未实证」
标注（格式见 formats.md「AI 观点区」）。配套工作流模板随包分发：
`modou/skills/database-change-review/SKILL.md`（纯文本，教宿主 Agent 组合上述
工具完成变更评审闭环）。

## 一句话链路演示（判据：单一 MCP 会话闭环）

任务书（给 agent 的一句话）：

> 「用 modou 校验 `examples/changeset-demo` 这个变更集并优化其中的慢 SQL：
> 验收快照在 demo 目录的 before.json / after.json，慢 SQL 在 slow.sql，
> 库名是 demo_shop。」

链路（三个工具，单一 MCP 会话内，中间产物以本地文件路径传递）：

```
① pack(changeset_dir=examples/changeset-demo)
   → exit_code=0，warnings=[锁风险 2 条（INSTANT/INPLACE 标注）、待人工复核 1 条]
② verify(changeset_dir, baseline, after, default_database=demo_shop)
   → exit_code=1，summary.missing_execution≥1（漏执行的 idx_user_amount / sp_order_count 被指认）
③ optimize(statements_file=slow.sql, baseline=after.json, default_database=demo_shop)
   → exit_code=0，suggestions=[{status: measured, improvement_pct: …} 或 unverified（附原因）]
```

agent 汇总答句模板：

> 打包通过，附 3 条预警（无破坏性语句）；验收发现 2 处**漏执行**
> （`orders.idx_user_amount` 索引与存储过程 `sp_order_count`），退出码 1；
> 慢 SQL 优化建议：在 `orders(user_id, amount)` 建索引，影子库实测提升 X%
> （代价 1205.35 → 42.00），副作用附注：写放大提示 1 条。

## 自动化冒烟

`tests/mcp/test_demo_flow.py` 是脚本化 MCP client 的无头复跑（`MOUDO_TEST_SHADOW=1`
门禁）：在影子容器构造 before/after 快照（V03/V04 人为漏执行），经内存 Client
依次调用 pack → verify → optimize 并断言三段结论——真人 agent 演示与该脚本
共享同一工具面与断言口径。
