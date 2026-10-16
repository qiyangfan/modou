# 数据格式契约（v0.1 冻结，v0.2 增补）

本文定义墨斗的机读契约：快照导出格式与验收报告格式（v0.1 冻结）、优化报告格式与
快照 v2 采样数据节（v0.2 增补）。
一经发布即冻结（ADR-0008：报告按库分组的稳定契约，避免下游消费方跟着改）；
后续演进必须提升 `format_version` / `report_version` 并保持向后可读。

## 快照导出格式（format_version = 2，v1 向后可读）

`modou snapshot capture` 产出，JSON、UTF-8、缩进 2 空格（人可读、可 diff）。
v2 相对 v1 的唯一增量是表级可选 `sample` 数据节（`--sample-rows` 采样模式）；
结构快照（无采样）同样以 v2 产出（`sample` 为 null）。v1 快照必须仍可被
`verify` 等既有命令消费（冻结契约的演进方式 = 向后可读）。

```jsonc
{
  "format_version": 1,
  "tool_version": "0.1.0",
  "captured_at": "2026-10-14T04:00:00+00:00",   // UTC，仅信息用途
  "meta": {                                      // 服务器级元信息（影子兼容性检查的依据）
    "server_version": "8.4.11",
    "version_comment": "MySQL Community Server - GPL",
    "character_set_server": "utf8mb4",
    "collation_server": "utf8mb4_0900_ai_ci",
    "lower_case_table_names": 0,
    "sql_mode": "ONLY_FULL_GROUP_BY,..."
  },
  "databases": {
    "<库名>": {
      "name": "<库名>",
      "charset": "utf8mb4",                      // 库默认字符集（继承锚点）
      "collation": "utf8mb4_0900_ai_ci",         // 库默认 collation
      "tables": {
        "<表名>": {
          "name": "...", "engine": "InnoDB", "collation": "...",
          "comment": "...", "create_options": "...",  // 已剥离 auto_increment 计数器
          "ddl": "CREATE TABLE ...",             // 灌入载体；diff 不比较表 DDL 文本
          "columns":  [ { "name", "ordinal", "column_type", "nullable", "default",
                          "extra", "collation", "comment", "generation_expression" } ],
          "indexes":  [ { "name", "unique", "parts": [ { "seq", "column", "sub_part",
                          "direction", "expression" } ] } ],
          "foreign_keys": [ { "name", "columns", "ref_table", "ref_columns",
                              "on_update", "on_delete" } ],
          "check_constraints": [ { "name", "expression", "enforced" } ],
          "sample": {                                    // v2 可选；无采样时为 null
            "columns": ["id", "..."],                    // 与 rows 逐位对齐
            "rows": [[1, "..."], ...],                   // JSON 安全值（二进制为 {"$binary": hex}）
            "sampled_rows": 1000,                        // 实际采样行数
            "estimated_rows": 100000,                    // information_schema.TABLES 估计（可能 null）
            "method": "primary_key_asc",                 // 主键序确定性抽样；其余取值：
                                                         // primary_key_asc_row_limit_reached（达到
                                                         // --sample-rows 上限）、skipped_no_primary_key
                                                         // （rows 空）。生成列不进采样列清单（INSERT
                                                         // 显式赋值生成列报 3105，且其值可推导）
            "note": ""
          }
        }
      },
      "views":      { "<名>": { "name", "ddl" } },   // DDL 已归一化：剥离 DEFINER
      "procedures": { "<名>": { "name", "ddl" } },
      "functions":  { "<名>": { "name", "ddl" } },
      "triggers":   { "<名>": { "name", "ddl" } },
      "events":     { "<名>": { "name", "ddl" } },
      "warnings": ["..."]                            // 预留字段（当前恒为空；权限不足直接报错）
    }
  },
  "warnings": ["..."]                                  // 预留字段（当前恒为空）
}
```

### 归一化规则（采集侧完成，diff 不做二次归一）

- 对象 DDL（视图/过程/函数/触发器/事件）剥离 `DEFINER=...` 子句：灌入影子库后
  服务器会把 DEFINER 重写为灌入者，不剥离将产生假差异；
- `create_options` 剥离 `auto_increment=N`：计数器是运行时状态，非结构；
- 表 DDL 原文保留**继承态**注记（未显式声明的字符集不出现在 DDL 中）。

### 已证实的 round-trip 行为（2026-10-14 实证，MySQL 8.4）

- 库级字符集/collation 继承、生成列（VIRTUAL/STORED）、函数索引、前缀索引、
  CHECK、外键、触发器、存储过程、事件、中文注释：结构化字段 round-trip 全等；
- 表的 SHOW CREATE 文本在「列字符集继承库默认 collation」场景下，重灌一轮后
  从继承态注记变为显式态注记（第二轮起收敛）。**因此三方 diff 不比较表 DDL
  文本，只比较结构化字段**；灌入与保真判定同口径。

### 采集执行的语句清单（全部只读）

```sql
SELECT VERSION(), @@version_comment, @@character_set_server,
       @@collation_server, @@lower_case_table_names, @@sql_mode;
SELECT ... FROM information_schema.SCHEMATA / TABLES / COLUMNS / STATISTICS
             / REFERENTIAL_CONSTRAINTS / KEY_COLUMN_USAGE / CHECK_CONSTRAINTS
             / TABLE_CONSTRAINTS / VIEWS / ROUTINES / TRIGGERS / EVENTS;
SHOW CREATE TABLE / VIEW / PROCEDURE / FUNCTION / TRIGGER / EVENT <db>.<obj>;
```

除会话级设置外不产生任何库对象或数据变更（spec「采集过程无写操作」）。

## 验收报告格式（report_version = 1）

`modou verify --report-json` 产出：

```jsonc
{
  "report_version": 1,
  "generated_at": "...",
  "exit_code": 1,                        // 0=全部一致 1=存在差异 2=环境或输入错误
  "summary": {
    "missing_execution": 1,              // 漏执行
    "wrong_execution": 0,                // 错执行
    "historical_drift": 0,               // 历史漂移
    "databases_with_findings": 1
  },
  "env_errors": ["..."],
  "replay_error": {                      // 仅回放失败时非空
    "statement_index": 2, "sql": "...", "error_code": 1064, "error_message": "..."
  },
  "pack_warnings": [ { "source_file", "statement_index", "kind", "level", "message" } ],
  "databases": {
    "<库名>": [
      {
        "object_type": "table",          // database/table/view/procedure/function/trigger/event
        "object_name": "orders",
        "kind": "missing_execution",
        "dimensions": ["columns", "indexes"],   // 参考差异维度（英文枚举）
        "details": [ { "dimension", "path", "expected", "actual" } ]
      }
    ]
  }
}
```

结论分类语义（维度级判定、按类别聚合成「对象 × 类别」条目）：

| kind | 判定（逐维度/逐条目） |
|---|---|
| `missing_execution` | 期望态与实际态不同，且实际停在该维度的基线态（变更未生效） |
| `wrong_execution` | 实际态同时异于基线与期望（执行了但结果不对） |
| `historical_drift` | 变更集未触碰的条目，线上却与基线不同（他人并行改动/采集遗漏） |

退出码多库聚合取最严重档：2 > 1 > 0。

## 优化报告格式（report_kind = optimize，report_version = 1）

`modou optimize --report-json` 产出。独立于 verify 契约（不改动 report_version=1
的验收报告）。两级状态是全局统一口径：每条建议处于且仅处于
`measured`（实测提升，附实证数据）或 `unverified`（未验证，附原因）；退出码
0=报告产出、2=环境或输入错误，**1 不使用**（建议性输出不构成验收结论，
退出码永远不受 AI 输出影响）。

```jsonc
{
  "report_version": 1,
  "report_kind": "optimize",
  "generated_at": "...",
  "exit_code": 0,
  "env_errors": [],                       // 容器/影子/兼容性错误（退出码 2 时非空）
  "input_errors": [],                     // 快照无采样、语句类型不支持等（退出码 2 时非空）
  "advisor": {
    "configured": false,                  // BYOK 三元组是否齐备
    "model": null,
    "dropped": ["ai candidate ... dropped: ..."]  // 幻觉防线丢弃记录（前缀标注来源 rule/ai，
                                                  // 另含超每语句候选上限的 AI 截断记录）
  },
  "evidence_env": {
    "note": "代价为优化器估计（基于采样统计），无官方同值保证；…",
    "tables": [ { "database", "table", "sampled_rows", "estimated_rows" } ]
    // 涉及库的全部表都列出：未采样表 sampled_rows=null（无数据支撑代价对比，可见而非缺席）
  },
  "databases": {                          // 按库分组（ADR-0008 同款结构）
    "<库名>": {
      "statements": [
        {
          "index": 1,
          "database": "shop",
          "sql": "SELECT ...",
          "baseline": { "cost": 1205.35, "tables": [ { "table", "rows", "access_type" } ],
                        "actual_time_ms": null },   // EXPLAIN ANALYZE 实测（仅 SELECT，参考值）
          "findings": [ { "code": "FULL_WILDCARD_LIKE", "message": "…" } ],  // 确定性发现
          "suggestions": [
            {
              "source": "rule",              // rule / ai
              "kind": "index",               // index / rewrite
              "content": "ALTER TABLE `shop`.`orders` ADD INDEX `idx_user_id` (`user_id`)",
              "status": "measured",          // measured / unverified（二选一，无第三态）
              "cost_before": 1205.35, "cost_after": 42.0,
              "improvement_pct": 96.5,       // unverified 时为 null
              "rows_before": [], "rows_after": [],
              "actual_time_before_ms": null, "actual_time_after_ms": null,
              "reason": null,                // unverified 原因（冗余/代价未降低/环境原因/…）
              "side_effects": [ { "kind": "WRITE_AMPLIFICATION", "message": "…" } ]
              // kind 取值：WRITE_AMPLIFICATION / INDEX_COUNT / FK_DEPENDENCY /
              // EXISTING_BECOMES_REDUNDANT / CANDIDATE_REDUNDANT / INDEX_DROP_FAILED
              // （INDEX_DROP_FAILED = 候选索引未能从影子库删除，后续候选基线可能偏高）
            }
          ]
        }
      ]
    }
  }
}
```

冗余候选（确定性判定被现有索引覆盖）不进入影子实证，直接标 `unverified`
（reason 注明「冗余候选」）——确定性结论优先于实证，避免浪费影子资源。

## 各命令退出码语义

- `modou verify`：0=全部一致，1=存在差异结论，2=环境或输入错误（上文契约主体）；
- `modou pack`：0=打包成功；1=变更集校验失败（manifest 不一致、序号重复、语句边界
  漂移、文件不可读/非 UTF-8）；2=参数或输出错误（如 `--target-major` 不在支持清单、
  输出文件不可写）。pack 产出的是预警（非验收结论），1 的语义是「拒绝交付」，
  与 verify 的「存在差异」不同；
- `modou snapshot capture`：0=采集成功；2=环境或输入错误（连接、权限、库不存在、
  版本低于 8.0 地板、输出不可写）。采集不产出差异结论，不使用 1。
  `--sample-rows` 采样模式不改变退出码语义（采样失败同属 2）；
- `modou optimize`：0=报告产出（建议全部未验证也算产出）；2=环境或输入错误
  （快照不可读/无采样数据、语句类型不支持、语句引用了快照中不存在的表、容器不可用、
  报告不可写）。1 不使用：建议性输出不构成验收结论。
  冗余判定忽略前缀长度的对侧不成立：带前缀长度（如 a(64)）的现有索引与完整列
  候选不互判冗余（比较以「列+前缀长度」整体进行）；
- `modou lint`：0=无命中；1=存在命中（规则命中或 PARSE.001 解析命中——无法解析
  的语句逐条记录为工具命中，不中止整轮）；2=环境或输入错误（文件不可读、配置非法、
  未知规则 id、路径不存在）；
- `modou patrol drift`：0=无漂移结论；1=存在漂移结论；2=环境或输入错误（快照
  不可读、live 采集失败）；
- `modou patrol unused-indexes`：0=报告产出（建议性输出）；2=环境或输入错误
  （performance_schema 关闭、连接失败、快照不可读）。1 不使用；
- `modou patrol slowlog`：0=报告产出；2=环境或输入错误（文件不可读）。数值损坏
  的日志条目跳过并计数（skipped_lines），不构成输入错误。1 不使用。

## 采集口径与限制

- 采集目标为 **MySQL 8.0+**（内省依赖 `STATISTICS.expression`、`CHECK_CONSTRAINTS`
  等 8.0 专有元数据）；5.7 仅 `pack --target-major 5.7` 的锁风险注记口径；
- 采集账号需要对目标库**全量元数据可见**：information_schema 按权限静默过滤行
  （这是 MySQL 语义，工具无法自检出「少看了对象」），受限账号会采集到残缺快照，
  进而在 verify 产出成批假「漏执行」。建议具备 `SHOW CREATE ROUTINE`/视图/触发器
  等全部对象权限的账号执行采集；

## 审核报告格式（report_kind = lint，report_version = 1）

`modou lint --report-json` 产出。引擎纯静态判定（无数据库、无容器、不联网）；
配置 BYOK 三元组时附带 AI 残留语句语义评审（可选键 `ai_opinions`，见
「AI 观点区」节；未配置时无该键，行为不变）。

```jsonc
{
  "report_kind": "lint",
  "report_version": 1,
  "exit_code": 1,
  "summary": { "hits": 2, "error": 1, "warning": 1, "info": 0, "files": 1 },
  "hits": [
    {
      "rule_id": "CLA.015", "level": "error",       // error / warning / info
      "file": "V01__update.sql", "line": 3,          // 语句起始行（含前置注释，大致位置）
      "message": "UPDATE 语句无 WHERE 条件，将更新全表",
      "suggestion": "确认非误写，必要时先在影子库验证影响面"
    }
  ]
}
```

`rule_id` 是开放集合：除 SOAR 规则外，`PARSE.001` 是引擎产出的工具命中（语句无法
解析，非规则清单成员；级别固定 warning），指认文件与语句起始行，可经
`--skip-rule PARSE.001` 显式关闭。

## 巡检报告格式（report_kind = patrol_*，report_version = 1）

三类巡检各自独立成报告，字段随类型：

```jsonc
// patrol_drift：两方漂移（结构同 verify 结论粒度，无期望态语义）
{ "report_kind": "patrol_drift", "report_version": 1, "exit_code": 1,
  "summary": { "added": 1, "removed": 0, "changed": 2, "databases_with_findings": 1 },
  "databases": { "<库名>": [ { "object_type", "object_name", "category": "added|removed|changed",
                              "dimensions": ["existence|definition"], "details": [ { "dimension", "path", "expected", "actual" } ] } ] } }

// patrol_unused_indexes：分层未用索引（live）+ 离线冗余（snapshot）
{ "report_kind": "patrol_unused_indexes", "report_version": 1, "exit_code": 0,
  "uptime_seconds": 604800, "observe_days": 7,
  "usages": [ { "database", "table", "index_name", "columns", "status",
                "count_star": 0, "daily_average": null, "table_share_pct": null,
                "drop_statement": "ALTER TABLE ... DROP INDEX ...;",
                "note": "观察窗 7 天（uptime …s）内零读取；统计可能被重启/DDL 重置" } ],
  // status 取值：confirmed_unused / low_use / insufficient_data / excluded_unique / excluded_fk
  // count_star 是该索引 I/O 总量（含 UPDATE/DELETE 维护写），INSERT-only 表上零计数≈零读
  "redundancies": [ { "database", "table", "redundant_index", "dominant_index",
                      "case": "duplicate|prefix_non_unique|unique_prefix",
                      "drop_statement": "...", "fk_protected": false } ] }

// patrol_slowlog：慢日志指纹聚合（pt-query-digest 语义）
{ "report_kind": "patrol_slowlog", "report_version": 1, "exit_code": 0,
  "source_file": "slow.log", "entries_parsed": 42, "skipped_lines": 0,
  "top": [ { "fingerprint": "select * from orders where user_id = ?", "count": 2,
             "query_time_total": 4.0, "query_time_max": 2.5,
             "rows_examined_total": 300000, "sample": "SELECT ..." } ] }

// patrol_summary：跨信号综合（v0.5，`modou patrol summarize`）——确定性 digest，
// 输入为上三类报告文件（至少一份；report_kind 错位 = 输入错误退出 2）
{ "report_kind": "patrol_summary", "report_version": 1, "exit_code": 1,
  "generated_at": "...", "inputs": { "drift": "d.json", "unused": null, "slowlog": null },
  "signals": {
    "drift":   { "exit_code": 1, "added": 2, "removed": 0, "changed": 1,
                 "objects": [ { "database", "object_type", "object_name", "category" } ] },
    "unused":  { "exit_code": 0, "uptime_seconds", "observe_days",
                 "confirmed_unused": 1, "low_use": 0, "insufficient_data": 0, "redundant": 1,
                 "items": [ { "database", "table", "index", "status" } ] },
    "slowlog": { "exit_code": 0, "entries_parsed": 42, "fingerprints": 3,
                 "top": [ { "fingerprint", "count", "query_time_total", "rows_examined_total" } ] } } }
// exit_code 取已加载信号的最严重档；样本 SQL 不进摘要
```

## AI 观点区（ai_opinions，v0.5，各车道报告「只增不改」）

配置 BYOK 三元组（`MOUDO_AI_BASE_URL` / `MOUDO_AI_API_KEY` / `MOUDO_AI_MODEL`）后，
verify（失败归因）、lint（残留语句评审）、patrol summarize（跨信号叙事）、
optimize（候选生成，advisor 节既有）四车道可附 AI 分析。契约
（spec ai-analyst「结论两级分级」，ADR-0009）：

- **未配置**：不发起任何网络请求，报告不含 `ai_opinions` 键，与无 AI 版本零差异；
- **单列**：观点只出现在报告顶层可选键 `ai_opinions`（机读）与文本报告尾部的
  「AI 观点」区（人读），不混入确定性结论字段；
- **退出码免疫**：AI 观点永不影响 `exit_code`（结构性保证：观点合并函数不读不写该字段）；
- **降级可见**：调用失败产出 `status="degraded"` 条目并标注原因，报告照常产出。

```jsonc
"ai_opinions": [
  { "lane": "verify",                       // verify / lint / patrol
    "subject": "shop.table:orders",         // 对象定位（lint 为 文件:行；patrol 为 cross-signal）
    "opinion": "索引缺失疑似漏执行……",       // 观点正文（中文）
    "source": "ai", "model": "<模型名>",     // 来源标注
    "status": "ok",                          // ok / degraded
    "degraded_reason": null }
]
```

## 快照摘要（snapshot capture --report-json，v0.5 委托面证据原语）

`modou snapshot capture --report-json <path>` 与 MCP `snapshot_capture` 工具的
`summary` 字段同源（kernel `snapshot_summary` 单源，一致性校验守护）：仅元数据，
采样数据行绝不进摘要。**breaking 说明**：MCP `snapshot_capture` 的输出自 v0.5 起
以 `summary` 承载证据（原 v0.3 的 `server_version` + `databases` 计数键被取代），
既有 MCP 客户端请迁移到 `summary.databases`（`tables` 等同名计数在场，另含
`table_details`；旧 `sampled_tables` 计数由 `table_details[].sampled_rows > 0`
的条目数承接——0 行与跳过采样的表在两侧口径下都不计入）。

```jsonc
{ "server_version": "8.4.6",
  "databases": { "<库名>": {
      "tables": 3, "views": 1, "procedures": 2, "functions": 0, "triggers": 1, "events": 0,
      "table_details": [ { "table": "orders", "columns": 12, "indexes": 4, "sampled_rows": 200 } ] } } }
```

## 报告 UI 类型识别口径

报告加载按显式 `report_kind` 识别；支持清单由 `ui/server.py` 的 `SUPPORTED_REPORTS`
单源（现含 verify / optimize / lint / patrol_drift / patrol_unused_indexes /
patrol_slowlog / patrol_summary）；**verify（v0.1 冻结契约）是唯一没有
report_kind 字段的报告**，按 `summary.missing_execution` 形状 + `report_version=1`
识别——新报告类型不得省略 report_kind，否则会被误判为 verify。
