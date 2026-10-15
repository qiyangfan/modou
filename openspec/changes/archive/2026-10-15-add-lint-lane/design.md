# 设计：v0.4 审核车道（lint）

> 规则调研：SOAR `doc/heuristic.md`（master，125 条）+ `advisor/heuristic.go`
> （dev，实现核对）+ Bytebase SQL Review 分类交叉印证（2026-10）。

## 1. 静态可判定性结论（选型依据）

SOAR 125 条规则中约 120 条是纯离线判定（SQL 文本/AST，TiDB parser + vitess +
正则，不连库）——它根本不做「列无索引」类检查（那属索引建议/EXPLAIN 车道）。
例外三类，**首批全部排除**：

- ARG.003（隐式类型转换）：需列类型/schema 才能精确判定 → 列为后续带 schema
  模式的扩展（无 schema 时只可能误报，宁可不做）；
- KEY.009（加唯一索引前查数据唯一性）：需连库查数据；
- SEC.003（高危操作前备份）：流程性要求，无法静态判定。

Bytebase 分类（Naming / Anti-pattern / Indexing / Locking / Backward-incompatible）
与 SOAR 主题高度同构，两边共识的高频反模式即首批候选——下表即按此交集取 26 条
（≥20 判据留余量），全部单树 AST 可判定。

## 2. 首批规则清单（26 条，冻结）

级别语义：error=正确性/高危问题；warning=性能或工程风险；info=规范建议。
默认任意已启用规则命中即影响退出码（见 §4），级别用于展示与按级过滤。

| ID | 名称 | 一句话 | 级别 |
|---|---|---|---|
| ARG.001 | 前缀通配 LIKE | `LIKE '%x'` 无法走索引 | warning |
| ARG.004 | IN (NULL) | 对 NULL 用 IN 永不为真 | error |
| ARG.005 | IN 列表过多 | 超阈值建议 BETWEEN/临时表 | warning |
| ARG.006 | 对列判 NULL | IS NULL 可能全表扫 | info |
| ARG.011 | 负向查询 | NOT IN/NOT LIKE 全表扫 | warning |
| CLA.001 | SELECT 无 WHERE | 全表查询检查 | warning |
| CLA.002 | ORDER BY RAND() | 随机排序效率极低 | error |
| CLA.003 | 大 OFFSET 分页 | 深翻页建议书签方式 | warning |
| CLA.015 | UPDATE 无 WHERE | 全表更新检查 | error |
| COL.001 | SELECT * | 表结构变更时行为漂移 | warning |
| COL.002 | INSERT 未指定列名 | 须显式列名 | warning |
| COL.005 | 列缺注释 | CREATE TABLE 列须 COMMENT | info |
| COL.013 | TIMESTAMP 无默认值 | 缺省值缺失影响在线变更 | warning |
| DIS.001 | 多余 DISTINCT | 含主键时 DISTINCT 无效 | info |
| FUN.001 | WHERE 列上函数 | 列上函数/运算使索引失效 | warning |
| FUN.005 | COUNT(col) | 应用 COUNT(*) | info |
| JOI.001 | 逗号与 JOIN 混用 | 易引入笛卡尔积错误 | warning |
| KEY.002 | 无主键/唯一键 | 阻塞在线变更工具 | error |
| KEY.005 | 索引数过多 | 超阈值告警 | warning |
| KEY.007 | 主键须整型 | 建议整型无符号主键 | warning |
| LCK.002 | INSERT ON DUPLICATE KEY UPDATE | 自增暴涨/主从不一致 | warning |
| RES.002 | LIMIT 无 ORDER BY | 结果集不确定 | warning |
| RES.003 | UPDATE/DELETE 带 LIMIT | 主从不一致风险 | error |
| SEC.002 | 疑似明文密码列 | 密码类列名+类型启发 | error |
| STA.003 | 索引命名前缀 | 二级 `idx_` / 唯一 `uk_` | info |
| SUB.002 | UNION → UNION ALL | 无需去重时更快 | info |

数值阈值（可配置）：IN 列表元素默认 >100；分页 OFFSET 默认 >10000；单表二级
索引数默认 >10。

## 3. 引擎结构

- 规则注册表：每条规则 = 标识 + 级别 + 说明 + 判定函数（AST 节点访问）+ 文档
  链接（SOAR 原文对照）。ID 沿用 SOAR 编号，输出附 SOAR 原文出处链接。
- 语句切分与位置映射复用 v0.1 splitter（DELIMITER 块完整保留），AST 位置信息
  映射回文件行号，命中输出 file:line。
- DDL 设计类规则（COL/KEY/STA）解析 CREATE TABLE/ALTER 语句本身——审核对象即
  DDL 时天然纯静态；DIS.001 按 SOAR 实现口径简化（DISTINCT 与主键/唯一键并存的
  已知形态提示，不做 schema 反查）。
- 变更集目录输入 = 目录扫描 `.sql` 逐个审核，不校验 manifest（lane 边界：
  清单校验属 pack）。

## 4. 配置与退出码

- 配置文件 `modou.toml`（当前目录查找，`--config` 显式覆盖）：`[lint]` 段起步
  （规则开关 + 阈值），后续车道复用同一文件；未配置 = 默认全开 + 默认阈值。
- `--skip-rule <ID>`（可重复）显式跳过，优先级高于配置文件（显式 > 文件，与
  口令优先级口径一致）。
- 退出码：0=无命中；1=存在已启用规则命中；2=环境或输入错误（文件不可读、语句
  无法解析——解析失败快速失败并指认位置，不静默跳过、不产出半截报告）。

## 5. 测试与文档

- 每条规则正反例各至少一例（52+ fixture），逐条可独立运行——「规则可测」本身
  是 spec 要求。
- `docs/rules.md`：规则清单（标识/级别/说明/示例/SOAR 对照链接），v1.0 文档
  齐备的规则清单打底。

## 出处

- XiaoMi/soar `doc/heuristic.md`（125 条规则文档）与 `advisor/heuristic.go`
  （静态判定核对、阈值配置项）
- Bytebase SQL Review 规则分类（交叉印证高频反模式）
- ADR-0001（承诺三）/ ADR-0003（确定性裁判）/ ADR-0006（唯一解析器）
