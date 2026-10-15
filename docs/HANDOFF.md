# HANDOFF — modou

## 现状（2026-10-15，v0.2~v0.4 全车道落地 + 两轮评审修复 + 五 change 已归档）

治理层全量就位：宪法（openspec/project.md，六条红线）、目标体系（docs/goals.md）、
ADR 0001~0008、AGENTS.md（门禁单源）、CI（core 门禁 + ui Node 24 门禁，ui/ 落地后
自动生效）。四车道三表面全部实现：

- 变更车道（v0.1）：`changeset/`（发现/manifest/pack 预警）、`snapshot/`、`replay/`、
  `diff/`（三方 diff）、`report/`（verify 契约冻结）；
- 优化车道（v0.2）：`optimize/`——采样采集（format v2）→ 影子实证（EXPLAIN
  FORMAT=JSON 代价对比 + 统计对齐）→ 两级状态报告；AI 顾问 BYOK（stdlib 直连
  OpenAI 兼容端点，零额外依赖；载荷仅 SQL+schema 摘要）；
- 审核车道（v0.4a）：`lint/`——SOAR 子集 26 条纯静态规则（docs/rules.md），
  modou.toml 可配置；
- 洞察车道（v0.4b）：`patrol/`——两方漂移 diff / 未用索引分层判定 / 慢日志指纹
  聚合（pt-query-digest 口径）；
- MCP 表面（v0.3）：`server/`——9 工具与 CLI 1:1（parity 测试守护），stdio、
  fastmcp 4.x（可选 extra `mcp`，dev 组含测试依赖）；
- 薄报告层（v0.4c）：`ui/`（前端，无框架 TS+Vite，构建产物随 wheel 分发，
  运行期零 Node）+ `ui/server.py`（回环 HTTP，报告 kind/version 门禁）。

数据格式契约见 [formats.md](formats.md)（v2 快照 + optimize/lint/patrol 报告格式）。
网络行为仅 AI 顾问 BYOK（未配置零联网，红线未动）。

## 口径

- 名字读作**墨斗**（木匠弹线工具），非"魔豆"。
- 决策单源在 docs/adr/；架构事实在 architecture.md；竞品数据快照在 research-2026-10.md
  （引用前复核时效）。
- 门禁单源在 AGENTS.md（ruff format/check + pytest + CLI 冒烟），CI 同款
  （`.github/workflows/ci.yml` 冒烟用 `modou --help`，与门禁同文）。
- **影子层接入仓库 CI——已定调关闭，算完成（owner 2026-10-14，勿再提议/重开）**：
  影子层不接入仓库 CI，维持本地门禁（`MOUDO_TEST_SHADOW=1`）。定调依据是数据红线
  而非成本：verify 快照含生产 schema 全文，进托管 CI 即数据出本地（红线 4）；容器
  CLI 已参数化，成本不构成障碍。唯一适合 CI 的切片是 pack 预警（纯静态、零容器、
  零连接），该切片已交付（examples/ci/，示例文档形态，不新增维护面）。复核条件：
  多人协作、或影子层成为核心路径时，重新评估仓库 CI 增设容器层。
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
- **`innodb_stats_persistent_sample_pages` 是 GLOBAL 变量**：SET SESSION 报 1229，
  只能 SET GLOBAL（无权限时降级跳过，`optimize/explain.refresh_statistics`）。
- **EXPLAIN ANALYZE 会真实执行语句**：只对 SELECT 取实测耗时参考；对 UPDATE/DELETE
  跑 ANALYZE 等于把改写语句真的执行掉（optimize 管线里有显式 is_select 守卫，别拆）。
- **ADD INDEX 无条件刷新该表统计**（无视 auto_recalc）：优化实证的基线与复测两侧
  必须各自显式 ANALYZE 拉平，否则代价对比口径不一致。
- **sqlglot 对乱码宽容**：未知词解析成标识符（`SELEC * FORM x` 能解析），残缺结构
  （未闭合引号、不完整语句）才抛 ParseError/TokenError；lint 用 ErrorLevel.RAISE。
  存储过程体（BEGIN...END、IN/OUT 参数）结构性不支持——见「待确认」第 1 条。
- **typer 的 CommandInfo.name 未显式命名时为 None**：枚举 CLI 子命令要回落
  `callback.__name__`（`server/surface_map._command_name` 单源，parity 守护复用）；
  Select 的 FROM 参数键在新版 sqlglot/typer 里是 `from_`（带下划线）。
- **fastmcp 工具名守 SEP-986 最稳子集**（字母数字下划线 ≤64）：CLI 连字符子命令
  映射工具名时归一为下划线（patrol unused-indexes → patrol_unused_indexes）。
- **`modou ui` 的 serve_forever 在 run_ui 内以守护线程启动**：CLI 主线程只
  Event().wait() 等中断；忘记启动服务线程的症状是端口能连上但请求永远超时。

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
uv sync                        # 安装依赖（生成 uv.lock 与 .venv；fastmcp 在 dev 组，MCP 测试可直接跑）
uv run pytest                  # 单测（容器层默认跳过）
MOUDO_TEST_SHADOW=1 uv run pytest tests/integration tests/mcp/test_demo_flow.py   # 影子库全量（本机 podman）
uv run ruff format --check . && uv run ruff check . && uv run pytest
uv run modou --help            # CLI 冒烟
cd ui && npm ci && npm run typecheck && npm run lint && npm test && npm run build   # ui 门禁（Node 24）
```

MCP 面接入（Claude Code/Cursor 等）：`uv tool install 'modou[mcp]'`，client 配
`command: modou, args: [mcp]`，工具清单与演示链路见 [demo-agent.md](demo-agent.md)。

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

## 实证记录（2026-10-15，v0.2~v0.4 全车道收官，本机 podman + mysql:8.4）

- **v0.2 优化车道**：影子集成 5 用例——采样两次采集样本集一致、数据灌入行数与快照
  记录一致、有效索引实测提升（2000 行表，等值+范围候选代价下降，measured+提升
  百分比）、AI 无效建议（低选择性索引）被实证关拦截标「未验证（代价未降低）」且
  影子索引回滚干净、冗余候选确定性跳过实证。影子 `SET SESSION
  innodb_stats_persistent_sample_pages` 报 1229（GLOBAL 变量）→ 改 SET GLOBAL +
  无权限降级。EXPLAIN ANALYZE 只对 SELECT 执行（DML 会真实生效，绝不跑）。
- **v0.3 MCP 表面**：parity 测试守护 9 工具（pack/verify/snapshot_capture/
  optimize/lint/patrol_drift/patrol_unused_indexes/patrol_slowlog/version）与 CLI
  分析类子命令 1:1（排除 mcp/ui 长驻面）；演示链路（tests/mcp/test_demo_flow.py，
  影子门禁）：单会话 pack → verify（漏执行 exit 1 指认 idx_user_amount/
  sp_order_count）→ optimize（实测建议两级状态）全通。`modou mcp` 未装 fastmcp →
  退出码 2 + 安装指引。工具名连字符归一（unused-indexes → patrol_unused_indexes，
  SEP-986）。接入文档 docs/demo-agent.md；CI 示例 examples/ci/（仅 pack 纯静态 +
  数据红线声明）。
- **v0.4a 审核车道**：26 条规则逐条正反例（52+ 用例）全绿；行号定位用空白不敏感
  顺序扫描（切分器保留语句内注释，直接 find 会失配）；sqlglot 对乱码宽容（解析成
  标识符），残缺结构才判不可解析（口径与解析器能力一致，tests 内注明）。
  docs/rules.md 冻结规则清单。
- **v0.4b 洞察车道**：影子集成 2 用例——FORCE INDEX 读 idx_a/不读 idx_b：低用与
  「确认未用」（观察窗 0 天）分层正确、附 DROP 语句；两轮采集间加索引 → drift
  报「新增」。慢日志聚合：同模板两条（仅字面量不同）合并 count=2、累计 4.0s、
  保留首条样本；log_slow_extra 混行/USE 终止/同秒共享 Time 行均自适应。
- **v0.4c 薄报告层**：前端组件测试 + typecheck/eslint/test(含 build) 全绿；
  Python 侧加载器 kind/version 门禁、非回环拒绝、404、目录穿越防护、回环实证。
  首轮评审曾在真实浏览器证伪「端到端走查」（/api/reports 裸数组 vs 前端取
  `.reports` → 任何报告白屏）；修复后以真实浏览器复核：四类报告侧栏加载、
  点击切换渲染、exit-2 不误标「全部一致」、未采样表可见，全部通过。
  SIGINT 干净退出码 0（用 venv 入口 `.venv/bin/modou` 实证；经 `uv run` 包装时
  信号由 uv 自身先死、退出码 130，是 uv 行为不是工具缺陷）。`ui/dist` 经
  hatch force-include 随 wheel 分发，构建前置 `cd ui && npm run build`。
- **全量门禁（2026-10-15 评审两轮修复后）**：ruff format/check 全绿；pytest
  399 passed + 32 skipped（单元，skip 全为影子门禁），影子集成 32 passed
  （`MOUDO_TEST_SHADOW=1` + STRICT，含生成列采样灌入回归）；CLI 冒烟全绿；
  ui 门禁（typecheck/lint/test=build+vitest 18 用例）全绿。

## 全量代码评审（2026-10-15，第二轮：五车道并行 + 修复循环）

五独立子代理按车道评审（optimize / lint+patrol / MCP+params / snapshot v2 / UI），
主对话逐条溯源核验后确认并修复约 40 项，全部附回归测试。后继者需要知道的
事实与口径决策：

- **修复的证据口径**：lint 规则四条（KEY.002/KEY.007/FUN.001/STA.003）的根因都是
  「sqlglot AST 形态假设未实测」——列级主键是 `PrimaryKeyColumnConstraint`（表级才是
  `exp.PrimaryKey`）、表级 UNIQUE KEY 的名字在 `args["this"].this`（Schema 包裹）、
  FULLTEXT/SPATIAL 标注在 `args["kind"]` 而非 `index_type`（后者恒为 bool）。改规则
  前先写 AST 实验脚本定形，不要凭文档猜。
- **optimize 候选目标键**：一律按 `--default-database` 归一（`_collect_tables`），
  键中不得出现 None 与 str 混排（曾致 sorted TypeError 裸崩、别名语句整体丢候选）。
- **实证失败路径**：影子实证按阶段（apply/refresh/explain/drop）报告失败；
  候选索引删除失败必须在 side_effects 披露 `INDEX_DROP_FAILED`（残留索引会让
  后续候选基线偏高）。前缀长度（sub_part）参与冗余比较：a(64) 与完整列 a 不互判冗余。
- **采样契约**：生成列（generation_expression 非空）不进采样列清单（INSERT 显式
  赋值生成列 = MySQL 3105，容器回归已固化）；截断探测用 LIMIT N+1；时间值保留
  微秒；restore 的 zip 用 strict=True（列宽不符响亮拒绝）。include_data=True 时
  数据在触发器之前灌入（采样 INSERT 不得触发触发器）。
- **UI 契约**：`/api/reports` 返回 `{"reports": [...]}`（对象形，非裸数组）；
  报告 id 是绝对路径，前端必须 `encodeURIComponent`、服务端必须 unquote；
  「全部一致」仅在 exit 0 且无 env_errors/replay_error 时渲染；renderReport 有
  错误卡兜底（畸形报告不白屏）；Host 头非回环一律 403（DNS rebinding 防护）；
  绑定白名单仅 IPv4 回环（::1 从未真正可用）。
- **分发口径**：`ui/dist` 不入 git（构建产物）；CI core 门禁在 `uv sync` 前先
  `npm ci && npm run build`（force-include 是硬前置）；`npm test` = `build && vitest
  run`（零外链扫描永远测当前源码的产物）。
- **MCP 面**：工具描述回退链 `CommandInfo.help or inspect.getdoc(callback)`（typer
  注册期 help 恒为 None，空串会让 parity 守卫空转）；未知 skip_rule 与 observe_days<1
  与 CLI 同语义拒绝；patrol 两工具补齐 host/port/user 参数面。
- **退出码纪律**：所有「用户可修正的输入错误」一律退出码 2（lint 阈值非法、
  slowlog 坏值跳过计数、ui 端口占用等），不得让裸异常掉到退出码 1。
- **第二轮复审（修复面再评审）补修**：具名 `CONSTRAINT <名> PRIMARY KEY/UNIQUE`
  是 exp.Constraint 包裹（KEY 系规则须解包，mysqldump 高频形态）；CTE 别名同为
  exp.Table 节点（引用表校验必须排除 WITH 名）；lint 侧函数包裹判定同样要按
  查询边界剪枝（walk(prune=…)）；混合表达式索引（如 (LOWER(name), age)）整条
  不可比；`exp.Constraint` 内 FULLTEXT 标注仍在 args["kind"]。全部附回归测试。

## 待确认（上报 owner）

1. **lint 对存储过程/触发器体快速失败**：sqlglot 结构性不支持 `BEGIN...END` 过程体
   （IN/OUT 参数模式即报错）。spec（sql-lint）定义「无法解析的语句整体输入错误、
   不静默跳过」——现按 spec 实现（含过程的变更集目录 lint = 退出码 2 并指认文件行）。
   工程上真实变更集常含过程，建议后续 change 引入「程序体语句显式跳过声明
   （报告列明，非静默）」，需 owner 确认后立 delta。
2. **指纹 UNION 分支折叠未实现**：design 列了「相同 UNION 折叠」，spec 未要求，
   实现覆盖 spec 全部要求（字面量/IN/VALUES/内嵌数字/注释/小写），UNION 分支不去重
   （同语句仍稳定聚合）。如需对齐 pt-q-digest 完整口径再补。

## 未完成（按优先级）

1. **v1.0 对外发布**：PyPI 发布、`uv tool install modou` 一条命令、中英双语 README、
   真实场景案例两个（含本团队一次完整迭代）、文档齐备（快速上手/变更集规范/
   规则清单/MCP 接入——rules.md 与 demo-agent.md 已就绪）。发布前注意：wheel 打包
   需先 `cd ui && npm run build`（force-include 读磁盘产物）。

（已完成的历史项：五 change 归档于 2026-10-15 完成——delta 已合并进
openspec/specs/（sql-optimize / sql-lint / db-patrol / mcp-surface / report-ui，
`openspec validate --specs --strict` 全绿），原型归档于 openspec/changes/archive/；
「影子层接入 CI」于 2026-10-14 定调关闭（决策记录见上文「口径」），不再是未完成项。）
