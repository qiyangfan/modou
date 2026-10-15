# 设计：v0.4 洞察车道（patrol）

> 技术口径依据 2026-10 调研（MySQL 8.0/8.4 官方手册 + sys 源码 + Percona
> 文档，出处见文末）。

## 1. 漂移巡检（drift）

- 两方对比（基线快照 vs 当前快照/现场实采），复用 v0.1 维度级 diff 核心：
  分类为新增对象（当前有基线无）、缺失对象（基线有当前无）、定义变更（两侧
  都有但维度差异）；不引入变更集与三方分类（那是 verify 的域）。
- 「现场实采第二份」复用 `snapshot capture`（只读、快照契约不变）；命令即起
  即止，不驻留。

## 2. 未用索引（unused-indexes）分层判定口径

- 数据源：`performance_schema.table_io_waits_summary_by_index_usage`
  （8.0/8.4 默认开启，只读变量；需防御用户显式关闭 → 明确报错而非空结论）。
- 关键口径（源码核实）：
  - INSERT 一律计入 `INDEX_NAME = NULL` 行 → 只写不读的二级索引自身计数为 0，
    恰好匹配「未被读」语义；判定时排除 `PRIMARY` 与 `NULL` 行；
  - `sys.schema_unused_indexes` 只列非唯一二级索引（PK/唯一索引被刻意排除——
    删了丢唯一性/约束语义）→ 同口径排除并说明原因；
  - **统计会清零**：服务器重启全清、TRUNCATE 汇总表清零、改变索引结构的 DDL
    可能使按索引统计重置 → 结论必须交叉校验服务器运行时长（uptime）。
- 分层判定（官方无阈值，工程口径）：
  - 确认未用：计数为零 且 uptime ≥ 观察窗（默认 7 天，可配；须覆盖月度批任务
    周期）；同时披露 uptime 与「统计可能被重置」的风险注记；
  - 疑似低用：读计数占同表 I/O 比例与日均读次数（附数值，不给断言）；
  - 数据不足：uptime < 观察窗。
- 外键依赖索引：联查 `REFERENTIAL_CONSTRAINTS`/`KEY_COLUMN_USAGE`，排除或
  标注依赖（DROP 会触发 MySQL 自动重建索引）。
- 表达式/函数索引按 `EXPRESSION` 比较，不能只看列名。

## 3. 冗余索引（离线模式，纯快照元数据）

三情形（对齐 `sys.schema_redundant_indexes` 源码语义，自行实现以支持离线快照）：

1. 列集合完全相同（duplicate）；
2. 非唯一索引的列序列是另一索引列序列的前缀（`(a)` 被 `(a,b)` 冗余）——
   冗余方必须非唯一：唯一索引的约束语义不可被长索引替代；
3. 唯一索引的列是另一索引列的前缀（`UNIQUE(a)` 使 `(a,b)` 冗余）。

命中附可执行 `ALTER TABLE ... DROP INDEX ...` 建议语句；外键依赖排除同 §2。

## 4. 慢日志解析与指纹聚合（slowlog）

- 格式事实（8.x）：条目 = `#` 头部元数据行 + `SET timestamp=...` 会话行 + 语句
  本体。手册字段清单只有 Query_time/Lock_time/Rows_sent/Rows_examined 四项，
  `# Time:`（8.0.14 起 ISO 8601）与 `# User@Host:` 属**事实格式**（未入册），
  解析器须兼容；5.6/5.7 同秒连续条目可能共享/省略 `# Time:` 行。
  `log_slow_extra`（8.0.14+）追加字段行，官方口径「按字段数自适应判别」。
- 指纹归一（对齐 pt-query-digest 行业事实口径，便于与现有工具生态对账）：
  全小写、空白折叠、去注释、字面量（字符串/数字/十六进制/NULL）→ `?`、
  标识符内嵌数字替换、**IN()/VALUES() 列表无论基数折叠为单个占位符**、
  多值 INSERT 折叠单 VALUES、相同 UNION 折叠。
- 聚合输出：按指纹聚合执行次数、累计/最大 Query_time、累计 Rows_examined、
  一条样本语句；按累计耗时排序输出 top 榜。
- 与 digest 表的口径差异（不互认，故 Non-goal）：服务器端规范化不折叠 IN 列表、
  DIGEST_TEXT 按 1024 字节截断且不重算哈希、容量满归入 NULL 特殊行。

## 5. 调度与红线

- 不带调度器：命令完成即退出；示例文档给 cron 与 systemd timer 两种形态
  （含输出落盘与轮转建议）。
- 退出码：drift 为结论性（0/1/2，1=存在漂移）；unused-indexes 与 slowlog 为
  建议性（0/2，不使用 1——与 capture/optimize 同理，建议不构成失败）。

## 出处

- MySQL 8.0/8.4 Reference Manual：slow-query-log（字段清单、log_slow_extra、
  8.0.14/8.0.29 口径）、performance-schema table-io-waits-summary-by-index-usage
  （INSERT 归因 NULL、TRUNCATE/重启清零）、sys-schema-unused-indexes（源码口径）
- mysql-server 源码：scripts/sys_schema（schema_unused_indexes /
  schema_redundant_indexes 视图定义）
- Percona pt-query-digest 文档（指纹规则、IN 列表折叠）
