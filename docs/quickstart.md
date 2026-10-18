# 快速上手

五分钟走通四车道最小链路。前置:Python 3.12+、`uv tool install modou`(或源码
`uv sync`)、一个可连接的 MySQL 8.0+ 与本地 podman 或 docker(verify/optimize
的影子库用,lint 不需要)。

约定:下文 `--dsn mysql://user:pass@host:3306` 处替换为你的连接串;`库名` 替换为
目标库。账号需全量元数据可见(information_schema 按权限静默过滤,工具无法自检
「少看了对象」)。

## 1. 变更验收(pack + verify)——交棒防漏

```bash
# 运维执行前:只读快照(期望态基线)
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 -o before.json

# 开发侧:变更集打包(合并脚本 + 清单校验 + 破坏性预警)
modou pack my-changeset/ -o packed.sql

# ……运维执行 packed.sql……

# 运维执行后:只读快照(实际态)
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 -o after.json

# 三方 diff 验收:漏执行 / 错执行 / 历史漂移,一次说清
modou verify my-changeset/ --baseline before.json --after after.json \
    --default-database 库名 --report-json report.json
```

退出码契约(可作 CI 卡点):**0** = 全部一致;**1** = 存在差异结论(报告指认对象与
维度);**2** = 环境或输入错误。多库聚合取最严重档。

```bash
# 本机浏览器看报告(仅 localhost,只读,无登录)
modou ui --report report.json
```

变更集怎么写(目录结构、manifest、DELIMITER、多库约定)见
[changeset-spec.md](changeset-spec.md);端到端案例(含真实输出)见
[examples/changeset-demo](../examples/changeset-demo/)。

## 2. SQL 优化(optimize)——建议必须过实证关

```bash
# 采样快照(带确定性样本数据,供影子库实证)
modou snapshot capture --dsn mysql://user:pass@host:3306 -d 库名 \
    --sample-rows 500 -o baseline.json

# 慢语句文件:一条或数条 SELECT/UPDATE/DELETE
modou optimize slow-sql.sql --baseline baseline.json --default-database 库名
```

每条候选带两级状态:**实测提升 X%**(影子库建索引前后 EXPLAIN 代价对比,统计
显式拉平)或 **未验证**(实证关未过,如代价未降低/冗余索引/影子阶段失败)。
配置 BYOK 三元组后另有 AI 诊断(可选,观点不影响结论分级)。
端到端案例见 [examples/optimize-demo](../examples/optimize-demo/)。

## 3. 规则审核(lint)——零数据库,可进 pre-commit

```bash
modou lint path/to/sql/            # 目录或文件,静态规则,零网络
modou lint my.sql --report-json lint-report.json
```

26 条 SOAR 子集规则,清单与阈值见 [rules.md](rules.md);`modou.toml` 可禁用规则
或调阈值,`--skip-rule` 单次跳过。任意已启用规则命中 → 退出码 1。

## 4. 漂移洞察(patrol)

```bash
# 两轮快照的结构漂移
modou patrol drift --baseline before.json --after after.json --report-json drift.json

# 未用索引分层判定(观察窗内低用 → 确认未用,附 DROP 语句)
modou patrol unused-indexes --dsn mysql://user:pass@host:3306 -d 库名 \
    --observe-days 7 --report-json unused.json

# 慢日志指纹聚合(pt-query-digest 口径)
modou patrol slowlog mysql-slow.log --report-json slowlog.json

# 跨信号综合摘要(可选 AI 叙事,未配置零网络)
modou patrol summarize --drift drift.json --unused unused.json \
    --report-json summary.json
```

## 下一步

- 变更集规范:[changeset-spec.md](changeset-spec.md)
- MCP 接入(宿主 Agent 委托):[demo-agent.md](demo-agent.md)
- 退出码与数据格式契约:[formats.md](formats.md)
