# 变更集规范

墨斗的变更集(change set)是一个目录:按序执行的 SQL 文件 + 一份 manifest。
`pack` 把它合并为可交付脚本并做破坏性预警,`verify` 用它作为回放输入推导期望态。
本规范是 `pack` / `verify` 共同遵守的契约。

参考实例:[examples/changeset-demo](../examples/changeset-demo/)。

## 目录结构

```
my-changeset/
├── manifest.txt
├── V01__create_orders.sql
├── V02__alter_orders_add_remark.sql
├── V03__add_index_user_amount.sql
└── V04__create_procedure_order_count.sql
```

- **V 命名**:`V<序号>__<描述>.sql`,按序号数值排序执行(非字典序拼名);
- 一个文件可以包含多条语句;序号间留空隙是允许的(迭代历史使然),`pack` 按数值序合并。

## manifest.txt

manifest 是文件清单声明(迭代说明 + 文件序),`pack` 校验目录内容与清单一致,
防漏文件与防多交付:

```
# 迭代 32:订单域 — 示例变更集(modou pack/verify 演示与冒烟用)
V01__create_orders.sql
V02__alter_orders_add_remark.sql
V03__add_index_user_amount.sql
V04__create_procedure_order_count.sql
```

- `#` 开头的注释行与空行忽略(惯例:首行注记迭代说明),其余每行一个文件名;
- 目录里存在 manifest 未声明的 SQL 文件,或 manifest 声明了不存在的文件 → `pack`
  拒绝交付(退出码 1),指认差异。

## 语句边界与 DELIMITER

- 默认分隔符 `;`;存储过程/触发器/事件体内需要 `DELIMITER <token>` 切换;
- **每个文件结束时必须把分隔符复位为 `;`**——`pack` 有独立守卫强制这一点:
  DELIMITER 块留到 EOF 时,合并产物对 DELIMITER 感知的客户端会跨文件粘连语句,
  且逐文件预警序号错位,`pack` 在打包阶段即报错并指认根因文件;
- 某文件最后一条语句缺分隔符(或 DELIMITER 未复位导致语句粘连)同理在 `pack`
  阶段拒绝——这是「合并后语句边界漂移」守卫,防止预警序号与回放序号错位。

## 多库变更

- 跨库语句用 `USE db;` 切换或显式限定名(`db.table`);
- 无 USE 且未给 `--default-database` 时,首个未限定语句由 MySQL 报 1046、
  `verify` 退出码 2 并给提示;
- 多库变更集的验收报告按库分组,退出码取最严重档。

## 破坏性预警(pack)

`pack` 在合并时做静态预警(不阻断交付,出现在 stderr 与报告里):

- `DROP TABLE` / `DROP COLUMN` / 范围收窄等不可逆 DDL;
- 锁风险:ALGORITHM 瞬时性判定(INSTANT/INPLACE/COPY 口径);
- 无法解析的语句(PARSE.001,warning 级):版本条件注释、存储过程体等解析器
  不支持的形态逐条披露、整轮不中断——结论级输出不依赖解析。

**stdout 只承载 SQL 产物**:`pack` 的预警/诊断一律走 stderr,`--output` 缺省即
stdout,重定向交付不会混入非 SQL 文本。

## 交付与验收流程

```
开发侧                                运维侧
──────                                ──────
my-changeset/ 目录
  │ modou pack ──→ packed.sql ──────→ 交付运维
  │                                     │ 执行
                                      执行前:modou snapshot capture(before)
                                      执行 packed.sql
                                      执行后:modou snapshot capture(after)
  └────────────── modou verify ──────→ 三方 diff:漏执行 / 错执行 / 历史漂移
```

- `verify` 的期望态由影子库(同版本本地容器)回放变更集推导,不靠 DDL 解析拼终态;
- 交付物**只增不改**:已交付的变更集目录事后不要修改(历史漂移的归因依赖
  「本次变更集内容」与「库里既有状态」的可信边界);同日重复迭代请用新序号新文件。
- 采集/验收的版本地板是 MySQL 8.0(内省依赖 8.0 专有元数据),更老版本入口处
  显式拒绝(退出码 2)。

## 退出码

| 命令 | 0 | 1 | 2 |
|---|---|---|---|
| `pack` | 打包成功 | 拒绝交付(manifest 不符/边界漂移) | 环境或输入错误 |
| `verify` | 全部一致 | 存在差异结论 | 环境或输入错误 |

完整语义见 [formats.md](formats.md)「各命令退出码语义」。
