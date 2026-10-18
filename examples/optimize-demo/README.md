# 案例二:索引建议必须过实证关

SQL 优化的行业现状:建议来自经验、博客或工具的规则推断,"这条索引能不能让查询
变快"没有人真的验证过。墨斗的回答:每条建议都在影子库(同版本本地容器 + 采样
数据)上真建索引、真跑 EXPLAIN,用代价对比给出两级状态——**实测提升 X%** 或
**未验证**。

本目录是完整案例:5 万行确定性合成数据(无随机量,可复现),两条慢语句,一条
过实证关、一条被拦下。以下所有输出均为本机 podman + mysql:8.4 的真实运行结果
(2026-10-18,墨斗 1.0.0,未配置 AI——纯确定性管线)。

## 场景

- 表:`orders`(5 万行,`user_id` 1~100、`amount` 确定性分布、现有索引仅
  `PRIMARY` 与 `idx_user_id(user_id)`);
- 语句一:大额订单明细——`amount` 上无索引,`idx_user_id` 定位到用户后逐行
  回表过滤;
- 语句二:按用户统计已支付订单——教科书会建议 `(user_id, status)` 组合索引,
  但在这个数据规模下未必真有收益。

## 实跑

```console
# 1. 场景搭建(见 setup.sql:建表 + 5 万行合成数据)
$ modou snapshot capture --dsn "$DSN" -d shop_opt --sample-rows 5000 -o baseline.json
captured 1 database(s) (server 8.4.11, sample-rows=5000) -> baseline.json
  shop_opt: 1 tables (1 sampled), 0 views, 0 procedures, 0 functions, 0 triggers, 0 events

# 2. 优化分析(影子库自动拉起 → 建候选索引实测 → 回滚,退出码 0)
$ modou optimize slow-sql.sql --baseline baseline.json --default-database shop_opt
```

真实输出(节选):

```
AI 顾问未配置（MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL），仅规则层产出候选。

── 实证环境（代价为优化器估计（基于采样统计），无官方同值保证；提升幅度 =（基线代价 − 复测代价）/ 基线代价，影子库与目标库大版本一致）──
  shop_opt.orders：采样 5000 行（全表估计 50000 行）

── 库 shop_opt ──

── 语句 #1 ──
  基线代价：17.50
  [实测提升 39.4%]（规则） ALTER TABLE `shop_opt`.`orders` ADD INDEX `idx_user_id_amount` (`user_id`, `amount`)
      代价 17.50 → 10.61
      [附注·EXISTING_BECOMES_REDUNDANT] 候选落地后现有索引 idx_user_id 变冗余（前缀被候选覆盖），建议评估替换
      [附注·WRITE_AMPLIFICATION] 新增二级索引会增加写入开销（每次 INSERT/UPDATE 维护一份索引），请结合写负载评估

── 语句 #2 ──
  基线代价：17.50
  [未验证]（规则）ALTER TABLE `shop_opt`.`orders` ADD INDEX `idx_user_id_status` (`user_id`, `status`)
      原因：代价未降低（复测代价不低于基线）
```

## 怎么读这份报告

- **语句一(实测提升 39.4%)**:`(user_id, amount)` 组合索引把"定位用户后回表
  过滤金额"变成"索引内直接定位",影子库建索引前后代价 17.50 → 10.61。这是
  墨斗唯一允许的建议形态:**带实测数字**。附注同时披露两件你该知道的事——
  候选落地后 `idx_user_id` 变冗余(可评估替换)、新增二级索引有写放大代价;
- **语句二(未验证)**:规则层照样产出了教科书建议 `(user_id, status)`,但
  影子库实测代价未降低——**建议被实证关拦下,明说"未验证"而不是冒充有效**。
  这一条正是本案例的重点:换别的工具,这条建议大概率会带着"推荐"标签直接
  出现在报告里;
- **代价口径**:代价是优化器估计(基于采样统计),提升幅度 = (基线代价 −
  复测代价) / 基线代价;影子库与目标库大版本一致,采样统计在报告中显式披露,
  不假装"官方同值保证";
- **AI 是可选增益**:本案例未配置 BYOK,管线全部确定性(规则初筛 → 影子实证)。
  配置后 AI 参与候选生成,但**同样必须过这条实证关**——AI 建议不过实证标
  "未验证",永不影响退出码。

## 本地复现

```bash
podman run -d --name modou-case2 -e MYSQL_ROOT_PASSWORD=case2pass \
    -p 127.0.0.1:33308:3306 mysql:8.4
# 等容器就绪后:
podman exec modou-case2 mysql -uroot -pcase2pass -e \
    "CREATE DATABASE shop_opt CHARACTER SET utf8mb4"
DSN="mysql://root:case2pass@127.0.0.1:33308"
podman exec -i modou-case2 mysql --default-character-set=utf8mb4 \
    -uroot -pcase2pass shop_opt < setup.sql
modou snapshot capture --dsn "$DSN" -d shop_opt --sample-rows 5000 -o baseline.json
modou optimize slow-sql.sql --baseline baseline.json --default-database shop_opt
podman rm -f modou-case2   # 用后即焚
```

> 数据为确定性合成(递推公式生成,无随机量),样本采集同为确定性排序——
> 你的复现数字应与本文一致(小数点后允许优化器版本差异)。
