# 审核规则清单（v0.4a，26 条）

纯静态规则（sqlglot AST 判定）：零数据库、零容器、零网络。ID 沿用小米 SOAR 编号
（迁移心智），出处 [XiaoMi/soar doc/heuristic.md](https://github.com/XiaoMi/soar/blob/master/doc/heuristic.md)；
级别语义：**error**=正确性/高危问题，**warning**=性能或工程风险，**info**=规范建议。
任意已启用规则命中 → 退出码 1；规则可在 `modou.toml [lint]` 禁用或 `--skip-rule` 跳过
（命令行优先于配置文件）。

阈值（`[lint.thresholds]`，默认值）：`in_list` 100 · `offset` 10000 · `index_count` 10。

工具命中（非 SOAR 规则，同走命中通道与跳过机制）：`PARSE.001` | warning | 语句无法解析 | 解析器不支持该语法形态（版本条件注释 `/*!50700 ... */`、存储过程体等），逐语句记录、整轮不中断 | 人工复核；确认无需机器审核后 `--skip-rule PARSE.001` 关闭。

| ID | 级别 | 名称 | 判定 | 建议 |
|---|---|---|---|---|
| ARG.001 | warning | LIKE 前缀通配符 | `LIKE '%x'` / `'_x'` 模式 | 搜索引擎或覆盖索引+延迟关联 |
| ARG.004 | error | IN (NULL) 恒不为真 | IN 列表含 NULL 字面量 | 疑似笔误，确认语义 |
| ARG.005 | warning | IN 列表元素过多 | 元素数 > in_list | 临时表 JOIN 或分批 |
| ARG.006 | info | 对列判 NULL | `IS [NOT] NULL` | 考虑默认值语义替代 |
| ARG.011 | warning | 负向查询 | NOT IN / NOT LIKE | 通常退化为全表扫描 |
| CLA.001 | warning | SELECT 无 WHERE | SELECT 带表无 WHERE | 确认全表扫描必要性 |
| CLA.002 | error | ORDER BY RAND() | 排序表达式为 RAND() | 应用侧随机或随机主键法 |
| CLA.003 | warning | 大 OFFSET 分页 | OFFSET > offset | 书签（keyset）分页 |
| CLA.015 | error | UPDATE 无 WHERE | UPDATE 无 WHERE | 全表更新确认非误写 |
| COL.001 | warning | SELECT * | select 含 * | 显式列名，防结构漂移 |
| COL.002 | warning | INSERT 未指定列名 | INSERT 目标无列清单 | 显式列名 |
| COL.005 | info | 列缺注释 | CREATE TABLE 列无 COMMENT | 补业务含义注释 |
| COL.013 | warning | TIMESTAMP 列无默认值 | TIMESTAMP 列无 DEFAULT | 严格模式插入会报错 |
| DIS.001 | info | 疑似多余 DISTINCT | DISTINCT 作用于含 id 列或 * | 含主键时无效果 |
| FUN.001 | warning | WHERE 列上函数/运算 | 列被函数或算术包裹 | 改写常量侧或 8.0+ 函数索引 |
| FUN.005 | info | COUNT(col) | COUNT 非星号参数 | 统计行数用 COUNT(*) |
| JOI.001 | warning | 逗号 JOIN 混用 | 有 ON 的 JOIN 与无 ON 的 JOIN 并存 | 统一 ANSI JOIN |
| KEY.002 | error | 表无主键/唯一键 | CREATE TABLE 无 PK/UNIQUE | 阻塞 gh-ost/pt-osc 在线变更 |
| KEY.005 | warning | 单表索引数过多 | 二级索引数 > index_count（含表级 UNIQUE KEY 与列级 UNIQUE，不含主键） | 合并或删除低价值索引 |
| KEY.007 | warning | 主键应为整型 | PK 列类型非整型族 | 聚簇代价与二级索引膨胀 |
| LCK.002 | warning | INSERT ON DUPLICATE KEY UPDATE | 语句含 conflict 子句 | 自增暴涨/主从不一致风险 |
| RES.002 | warning | LIMIT 无 ORDER BY | LIMIT 缺 ORDER BY | 结果集不确定 |
| RES.003 | error | UPDATE/DELETE 带 LIMIT | DML 带 LIMIT | 主从执行序不一致风险 |
| SEC.002 | error | 疑似明文密码列 | 密码类列名 + 字符类型（哈希命名豁免） | 存哈希不存明文 |
| STA.003 | info | 索引命名前缀 | 表级二级索引非 `idx_`、表级唯一索引非 `uk_`（FULLTEXT/SPATIAL 豁免；列级 UNIQUE 由 MySQL 自动命名，不判） | 统一命名规范 |
| SUB.002 | info | UNION 应为 UNION ALL | UNION（去重） | 无重复可能时改 UNION ALL |

## 排除项与边界

- **ARG.003（隐式类型转换）**：精确判定需列类型（schema-aware），无 schema 时只可能
  误报——列为后续带 schema 模式的扩展；
- **KEY.009（唯一索引前查重）**：需连库查数据，非静态；
- **SEC.003（高危操作前备份）**：流程性要求，无法静态判定；
- 解析口径：sqlglot 对乱码宽容（未知词解析为标识符），残缺结构（未闭合引号等）
  才判定为不可解析 → 整体退出码 2 并指认文件与行号；审核对象即 DDL 语句本身时
  纯静态；变更集目录输入只审 SQL 内容，不做 manifest 校验（那是 pack 的职责）。
