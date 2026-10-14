# 数据格式契约（v0.1 冻结）

本文定义墨斗 v0.1 的两个机读契约：快照导出格式与验收报告格式。
两者一经发布即冻结（ADR-0008：报告按库分组的稳定契约，避免下游消费方跟着改）；
后续演进必须提升 `format_version` / `report_version` 并保持向后可读。

## 快照导出格式（format_version = 1）

`modou snapshot capture` 产出，JSON、UTF-8、缩进 2 空格（人可读、可 diff）。

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
          "check_constraints": [ { "name", "expression", "enforced" } ]
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

## 各命令退出码语义

- `modou verify`：0=全部一致，1=存在差异结论，2=环境或输入错误（上文契约主体）；
- `modou pack`：0=打包成功；1=变更集校验失败（manifest 不一致、序号重复、语句边界
  漂移、文件不可读/非 UTF-8）；2=参数或输出错误（如 `--target-major` 不在支持清单、
  输出文件不可写）。pack 产出的是预警（非验收结论），1 的语义是「拒绝交付」，
  与 verify 的「存在差异」不同；
- `modou snapshot capture`：0=采集成功；2=环境或输入错误（连接、权限、库不存在、
  版本低于 8.0 地板、输出不可写）。采集不产出差异结论，不使用 1。

## 采集口径与限制

- 采集目标为 **MySQL 8.0+**（内省依赖 `STATISTICS.expression`、`CHECK_CONSTRAINTS`
  等 8.0 专有元数据）；5.7 仅 `pack --target-major 5.7` 的锁风险注记口径；
- 采集账号需要对目标库**全量元数据可见**：information_schema 按权限静默过滤行
  （这是 MySQL 语义，工具无法自检出「少看了对象」），受限账号会采集到残缺快照，
  进而在 verify 产出成批假「漏执行」。建议具备 `SHOW CREATE ROUTINE`/视图/触发器
  等全部对象权限的账号执行采集；
