# 案例一:交棒漏执行,机器验收兜底

一个真实形态的事故:开发交付 4 个文件的变更集,运维合并执行时漏了后两个——
没有机器验收时,这种漏要等到业务报错(订单按金额统计查不到索引、存储过程调用
失败)才会暴露,且排查成本远高于执行成本。

本目录既是 `pack` / `verify` 的演示素材,也是完整案例:下面的所有命令输出均为
本机 podman + mysql:8.4 影子库的真实运行结果(2026-10-18,墨斗 1.0.0)。
场景为脱敏合成数据,不包含任何生产数据。

## 变更集内容

| 文件 | 内容 | 说明 |
|---|---|---|
| `V01__create_orders.sql` | 建 `orders` 表 | 含中文注释、utf8mb4 |
| `V02__alter_orders_add_remark.sql` | 加 `remark` 列 | ADD COLUMN,可 INSTANT |
| `V03__add_index_user_amount.sql` | 加 `idx_user_amount` 复合索引 | INPLACE,大表注意耗时 |
| `V04__create_procedure_order_count.sql` | 建存储过程 `sp_order_count` | DELIMITER 块,EOF 复位 |

`manifest.txt` 声明文件清单(格式见 [docs/changeset-spec.md](../../docs/changeset-spec.md))。

## 第一步:运维执行前,只读快照

```console
$ modou snapshot capture --dsn "$DSN" -d shop -o before.json
captured 1 database(s) (server 8.4.11) -> before.json
  shop: 0 tables (0 sampled), 0 views, 0 procedures, 0 functions, 0 triggers, 0 events
```

## 第二步:运维执行(本案例模拟"漏执行后两个文件")

```console
$ modou pack examples/changeset-demo -o packed.sql        # 打包 + 破坏性预警(stderr)
$ # ……运维执行 packed.sql,本案例只执行了 V01、V02……
```

## 第三步:执行后快照 + 三方验收

```console
$ modou snapshot capture --dsn "$DSN" -d shop -o after.json
captured 1 database(s) (server 8.4.11) -> after.json
  shop: 1 tables (0 sampled), 0 views, 0 procedures, 0 functions, 0 triggers, 0 events

$ modou verify examples/changeset-demo \
      --baseline before.json --after after.json --default-database shop
墨斗验收报告
＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝

── 打包预警（不影响验收结论）──
  [lock_risk] V02__alter_orders_add_remark.sql #2：ALTER orders：ADD COLUMN 可走 INSTANT（8.0.12+），通常秒级完成；若失败会以报错快速终止，可显式指定 ALGORITHM=INSTANT 验证。
  [lock_risk] V03__add_index_user_amount.sql #3：ALTER orders：ADD INDEX/约束走 INPLACE：不阻塞写但需构建索引树，大表注意耗时与临时磁盘。
  [unparseable] V04__create_procedure_order_count.sql #4：语句无法解析，请人工复核其影响（预警不因解析失败阻塞打包）。

── 库 shop（漏执行 2 · 错执行 0 · 历史漂移 0）──
  [漏执行] 表 `orders`（索引）
      idx_user_amount: 期望 index(user_id,amount)
      idx_user_amount: 实际 <missing>
  [漏执行] 存储过程 `sp_order_count`（存在性）
      sp_order_count: 期望 exists
      sp_order_count: 实际 <missing>

退出码：1（0=全部一致，1=存在差异，2=环境或输入错误）
```

**退出码 1 实测确认**(`echo $?` → `1`)——这就是 CI 卡点的接口:验收不通过,
流水线在此停住,报告指认到对象与维度(哪个索引、哪个过程、期望什么、实际什么),
运维按单补执行即可。补执行后再跑一轮 `capture` + `verify`,退出码归 0。

## 这份报告里还能看到什么

- **打包预警三态**:V02 的锁风险提示(INSTANT 可选)、V03 的 INPLACE 耗时提示、
  V04 的解析预警(存储过程体超出解析器能力,逐条披露、不阻塞打包——结论由
  回放实证给出,不依赖解析);
- **漏执行与错执行是不同结论**:漏执行 = 期望有实际没有;错执行 = 执行了但
  结果与期望不符(如索引列序建错);另有历史漂移(库里与本次变更无关的既有
  差异)单列隔离,不与本次变更混判;
- **中文注释 round-trip 保真**:V01 的中文列注释经快照→影子库回放→diff 全程
  无假差异(HEX 级验证过的口径,见 docs/formats.md)。

## 本地复现

```bash
podman run -d --name modou-case1 -e MYSQL_ROOT_PASSWORD=case1pass \
    -p 127.0.0.1:33307:3306 mysql:8.4
# 等容器就绪后:
podman exec modou-case1 mysql -uroot -pcase1pass -e \
    "CREATE DATABASE shop CHARACTER SET utf8mb4"
DSN="mysql://root:case1pass@127.0.0.1:33307"
modou snapshot capture --dsn "$DSN" -d shop -o before.json
# 模拟漏执行:只执行 V01/V02
podman exec -i modou-case1 mysql --default-character-set=utf8mb4 \
    -uroot -pcase1pass shop < V01__create_orders.sql
podman exec -i modou-case1 mysql --default-character-set=utf8mb4 \
    -uroot -pcase1pass shop < V02__alter_orders_add_remark.sql
modou snapshot capture --dsn "$DSN" -d shop -o after.json
modou verify . --baseline before.json --after after.json --default-database shop
podman rm -f modou-case1   # 用后即焚
```

> 注意灌 UTF-8 文本必须给容器内 mysql 客户端加 `--default-character-set=utf8mb4`
> (客户端会话默认 latin1,中文会被双重编码固化成真实差异)。
