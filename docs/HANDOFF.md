# HANDOFF — modou

## 现状（2026-10-14，v0.1 变更车道纵切面已落地）

治理层全量就位：宪法（openspec/project.md，六条红线）、目标体系（docs/goals.md）、
ADR 0001~0008、AGENTS.md（门禁单源）、CI（core 门禁 + ui Node 24 预留 job）。
变更车道全链路已实现并通过影子库实证：`changeset/`（发现/manifest/pack 预警）、
`snapshot/`（只读采集/灌入）、`replay/`（容器编排/切分/回放/环境检查）、
`diff/`（维度级三方 diff + verify 管线）、`report/`（文本 + JSON 双出口，v0.1 契约冻结）。
数据格式契约见 [formats.md](formats.md)。优化/审核/巡检车道未开工，无业务库连接代码之外的
网络行为（BYOK 红线未动）。

## 口径

- 名字读作**墨斗**（木匠弹线工具），非"魔豆"。
- 决策单源在 docs/adr/；架构事实在 architecture.md；竞品数据快照在 research-2026-10.md
  （引用前复核时效）。
- 门禁单源在 AGENTS.md（ruff format/check + pytest + CLI 冒烟），CI 同款
  （`.github/workflows/ci.yml` 冒烟用 `modou --help`，与门禁同文）。
- 退出码契约：verify 0=全部一致 / 1=存在差异 / 2=环境或输入错误，多库取最严重档；
  pack/capture 各自的退出码语义见 formats.md「各命令退出码语义」（pack 1=拒绝交付，
  capture 一律 0/2）。

## 关键设计口径（代码之外的必要事实）

- **影子容器经 podman/docker CLI 编排**（`replay/container.py`），不用 testcontainers：
  零重依赖，podman/docker 命令面同构。镜像默认从基线快照的版本序列推导（如 `mysql:8.4`），
  版本序列与 `lower_case_table_names` 不匹配直接退出码 2（ADR-0005）。
- **三方 diff 分类在维度/条目粒度**（`diff/threeway.py`）：一个对象多个维度可产生不同
  类别（索引漏执行 + 列定义错执行各自成条）。对象级整表比较会把「建表后漏加一列」
  误判为错执行——不要改回去。
- **跨库变更集靠 USE/限定名**；无 USE 且未给 `--default-database` 时，首个未限定语句
  由 MySQL 报 1046、verify 退出 2 并给提示。回放连接与灌入连接分离（restore 会把
  会话库残留在最后一个灌入的库上，复用会掩盖 1046）。
- **影子会话 sql_mode 强制对齐基线**（restore 与回放两个会话都 `SET SESSION sql_mode`）：
  同版本服务器的全局 sql_mode 也可能不同，不对齐会让期望态静默失真。
- **基线缺库 = 新建库场景**，可验收（三方 diff 支持 None 基线）；回放后影子中仍无该库
  才算输入错误（退出 2）。
- **pack 拒绝「合并后语句边界漂移」的目录**：某文件末条语句缺分隔符（或 DELIMITER 未
  复位）会让相邻语句粘连、预警序号与回放序号错位，pack 阶段即报错并指认根因文件
  （归因跳过空文件）。另有独立守卫强制「每个文件结束时分隔符已复位为 `;`」——
  仅靠切分数守卫存在盲区：DELIMITER 块留到 EOF 且后文件语句数恰好补平时不报警。
  pack 的预警/诊断信息一律走 stderr，stdout 只承载 SQL 产物（缺省 --output 即 stdout，
  重定向交付不得混入非 SQL 文本）。
- **采集/verify 的版本地板是 MySQL 8.0**（`replay/env.unsupported_version_errors`）：
  内省依赖 8.0 专有元数据（STATISTICS.expression、CHECK_CONSTRAINTS），更老版本在
  入口处显式拒绝（退出 2）；5.7 仅 `pack --target-major 5.7` 锁风险注记口径。采集
  账号需全量元数据可见——information_schema 按权限静默过滤行，工具无法自检「少看
  了对象」（见 formats.md「采集口径与限制」）。
- **快照灌入的依赖收敛池跨库共享**（`snapshot/restore.py`）：db1 视图引用 db2 视图
  等跨库依赖只有全局池可解，按库分池必然误报不收敛。
- 采集 fail-loud：权限不足（如缺 SHOW CREATE ROUTINE）直接报错而非静默跳过对象——
  静默缺口会变成 diff 的「漏执行」假结论，危害更大。快照 warnings 字段为预留（恒空）。
- 容器集成测试默认跳过，`MOUDO_TEST_SHADOW=1` 开启（镜像可用 `MOUDO_TEST_MYSQL_IMAGE`
  覆盖，默认 `mysql:8.4`；CI 门禁语境加 `MOUDO_TEST_SHADOW_STRICT=1` 使拉起失败改为
  fail 而非 skip）。CI core 门禁不含容器层：owner 2026-10-14 定调**不接入，维持本地
  门禁**（复核条件见「未完成」第 1 条）。

## 常见坑（已实证，2026-10-14；原型阶段完成增补）

- **SHOW CREATE 的结果集按列名取**：TRIGGER/PROCEDURE/FUNCTION/EVENT 的第 2 列是
  `sql_mode` 不是 DDL（TABLE/VIEW 才是）。按位置 `[1]` 取会把 sql_mode 当 DDL 存下来，
  灌入时当 SQL 执行报 1064。已按列名映射（`introspect._DDL_COLUMN_BY_KIND`）。
- **表 DDL 文本不参与比较**：库默认 collation 非服务器默认时（如 utf8mb4_unicode_ci），
  列上 COLLATE 注记在重灌后从继承态变显式态，第二轮收敛。结构化字段 round-trip 全等，
  见 formats.md「已证实的 round-trip 行为」。
- **8.4 的 information_schema.CHECK_CONSTRAINTS 没有 ENFORCED 列**（8.0 有），
  enforced 从 TABLE_CONSTRAINTS.ENFORCED 取（两代都有）。
- **mysqldump 产物的列级字符集注记**：建表文本对列携带显式 `CHARACTER SET <cs>` 子句，
  空库回放的规范渲染在列字符集等于表缺省时省略该子句——DDL 文本比对必出假差异。
  未来若支持灌入 mysqldump 基线，比对必须走 information_schema 结构化字段（本仓实现即如此）。
- **容器内 mysql 客户端会话默认 latin1**：`podman exec … mysql < 脚本` 灌 UTF-8 文本时
  中文被双重编码固化（HEX 证据：`订`=E8AEA2 → 存成 C3A8C2AEC2A2）。模拟执行/交付脚本必须
  加 `--default-character-set=utf8mb4`。verify 会把这种执行事故作为错执行抓出（表选项/
  列维度），属真实差异而非假差异。
- MySQL 无 HypoPG：索引实证只能真建，大表注意影子库灌入耗时（必要时采样子集）。
- 快照灌入用 `SET FOREIGN_KEY_CHECKS=0` 解 FK 建表顺序约束；灌入前先 `select_db`
  （SHOW CREATE 的对象名不带库前缀）。

## 仓外参考

- `~/workspace/java/energy-ai-platform/ops/prod-bootstrap/regenerate.sh`：同痛点手工解法
  （基线+增量交付，双库对照生成增量 + 回放闭环自证）。其等价性验证半区是 modou verify
  的两库特例，可作首批试点替换对象；其生成半区（awk 解析 DDL 拼 ALTER）是 ADR-0004
  拒绝的路径，仅当未来做"修复建议"时参考其 DROP 先行安全序与 AFTER/FIRST 列位锚定。
  可借鉴的运维守卫：链回退检测（边界版本 > 链头即失败）、交付物只增不改 +
  同日重跑保护、空净效果不产出文件（多次迭代/交付状态管理立项时再看）。

## 可复现

```bash
cd ~/workspace/longzhong/modou
uv sync                        # 安装依赖（生成 uv.lock 与 .venv）
uv run pytest                  # 单测（容器层默认跳过）
MOUDO_TEST_SHADOW=1 uv run pytest tests/integration   # 影子库全量（本机 podman）
uv run ruff format --check . && uv run ruff check . && uv run pytest
uv run modou --help            # CLI 冒烟
```

端到端演示（样例变更集：`examples/changeset-demo/`）：

```bash
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 -o before.json   # 运维执行前
modou pack examples/changeset-demo -o packed.sql                                  # 打包+预警
# ……运维执行 packed.sql……
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 -o after.json    # 执行后
modou verify examples/changeset-demo --baseline before.json --after after.json \
    --default-database 库名 --report-json report.json
```

## 实证记录（2026-10-14，本机 podman + mysql:8.4）

- 影子库集成 21 用例全绿：round-trip 保真（字符集继承/生成列/函数索引/过程/触发器/事件/
  中文注释/AUTO_INCREMENT 计数器）、回放失败语句指认（1064 @ 序号）、DELIMITER 过程体
  完整回放并可调用、DROP 正确落地=退出 0、变更集新建库=可验收、灌入收敛循环可解多层
  视图依赖。
- 独立代码评审（子代理）5 项必修缺陷已全部修复并附回归测试：diff 在「正确 DROP」场景
  崩溃、影子阶段 pymysql 异常穿透破坏退出码契约、灌入依赖重试只走一轮、pack 序号在
  缺分隔符目录下与回放序号错位、多库报告库头误显全局计数。
- verify 端到端 8 场景：全部落地=退出 0；漏执行（索引/存储过程）=退出 1 且指认对象与维度；
  索引列序建错=错执行；无关并行改动=历史漂移隔离；双库 USE 变更集按库分组聚合取最严重档；
  语法错误=退出 2 + 语句序号；版本序列不匹配=退出 2；缺 default-database=1046 退出 2 带提示。
- CLI 全链路实证（examples/changeset-demo）：capture → 人工漏执行 V03/V04 → capture →
  pack（INSTANT/INPLACE 锁风险 + unparseable 预警）→ verify 退出 1 指认 `orders` 的
  `idx_user_amount` 与 `sp_order_count`；跨库（shop_a/shop_b）USE 变更集按库分组，
  shop_b 漏执行索引被指认，多余过程对象被归为历史漂移（非本次变更），退出码 1。
- **端到端单迭代计时（v0.1 第 5 条判据，2026-10-14）**：capture 前 0.6s + pack 0.4s +
  运维执行 1.7s + capture 后 0.4s + verify 26s~75s（含影子容器冷启动，启动抖动大），
  全迭代 < 2 分钟，远低于 ≤10 分钟阈值。**v0.1 五条判据全部实证达标**。
- 运维字符集事故场景（latin1 客户端灌 UTF-8 变更集）：verify 退出 1、表选项维度报
  错执行；该场景曾暴露新建表（基线无此表）+ 表选项差异时 `_table_dimension_findings`
  的 NoneType 崩溃，已修（`options_b` 以 None 参与分类，归错执行），回归测试
  `test_new_table_options_mismatch_is_wrong_execution`。
- 全量门禁（2026-10-14 评审收官态）：`ruff format --check` / `ruff check` / pytest
  121 passed（98 单测 + 23 容器集成，无跳过）/ CLI 冒烟，全绿。
- 全量代码评审（2026-10-14，两轮）：两独立子代理 + 主对话交叉共 30+ 条候选，逐条溯源
  核验后修复 20 项（含库级 charset 维度守卫错侧、FK JOIN 缺表名关联、restore 跨库
  收敛池、异常网缺口、DSN 空口令丢失、pack stdout 污染、DELIMITER 复位守卫盲区、
  版本地板显式拒绝等），全部附回归测试；第二轮增量复核确认无新引入缺陷。

## 未完成（按优先级）

1. **影子层接入 CI——已定调关闭（owner 2026-10-14）**：
   影子层不接入仓库 CI，维持本地门禁（`MOUDO_TEST_SHADOW=1`）。定调依据：产品定位是
   本地独立工具零侵入；verify 快照含生产 schema 全文，进托管 CI 即数据出本地（红线）；
   容器 CLI 已参数化（podman/docker 同构命令面，托管 runner 预装 docker 可零安装），
   成本不构成障碍，数据红线才是。唯一适合 CI 的切片是 pack 预警（纯静态、零容器、
   零数据库连接），即 v0.3 判据「GitHub Actions 示例」的形态——示例文档而非插件，
   不新增维护面。复核条件：多人协作、或 v0.2 使影子层成为核心路径时，重新评估
   仓库 CI 增设容器层。
2. **优化车道真值验证（v0.2，需先立 change）**：影子库建建议索引 → EXPLAIN 前后对比
   → 代价未降自动标"未验证"。
3. v0.2 优化车道、v0.3 MCP server、v0.4 lint/patrol/ui（见 architecture.md 模块地图）。
