# 巡检调度（外部调度器承载）

墨斗巡检是**一次性命令**（进程结束即退），不做常驻守护与自调度（ADR-0002 零平台化）。
定时由外部调度器承载，两种常见形态：

## cron

```cron
# 每天凌晨 3 点漂移巡检（基线与当日实采对比）
0 3 * * * cd /opt/modou-workdir && /usr/local/bin/modou patrol drift \
    --baseline baselines/prod.json --dsn "$MOUDO_DSN" -d shop -d config \
    --report-json reports/drift-$(date +\%F).json >> logs/patrol.log 2>&1

# 每周一 4 点索引巡检（连库未用分层 + 快照冗余）
0 4 * * 1 cd /opt/modou-workdir && /usr/local/bin/modou patrol unused-indexes \
    --dsn "$MOUDO_DSN" -d shop --observe-days 14 \
    --snapshot baselines/prod.json \
    --report-json reports/indexes-$(date +\%F).json >> logs/patrol.log 2>&1

# 每天凌晨 5 点慢日志指纹聚合（日志按天轮转后解析昨日文件）
0 5 * * * /usr/local/bin/modou patrol slowlog \
    /var/log/mysql/mysql-slow.log.1 \
    --report-json reports/slowlog-$(date +\%F).json >> logs/patrol.log 2>&1
```

## systemd timer

```ini
# /etc/systemd/system/modou-patrol.service
[Unit]
Description=modou drift patrol (one-shot)

[Service]
Type=oneshot
WorkingDirectory=/opt/modou-workdir
Environment=MOUDO_MYSQL_PASSWORD_FILE=/etc/modou/mysql-password
ExecStart=/usr/local/bin/modou patrol drift \
    --baseline baselines/prod.json --dsn mysql://patrol@10.0.0.9:3306 \
    -d shop --report-json reports/drift-latest.json
```

```ini
# /etc/systemd/system/modou-patrol.timer
[Unit]
Description=Run modou drift patrol daily at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`systemctl enable --now modou-patrol.timer` 启用。

## 口径与红线

- **观察窗**：未用索引判定依赖 uptime ≥ 观察窗（默认 7 天）；统计会被服务器重启 /
  TRUNCATE 汇总表 / 索引 DDL 重置——调度周期应避开已知变更窗口，报告附 uptime 交叉；
- **口令**：`MOUDO_MYSQL_PASSWORD` 环境变量或 `--password`；DSN 内嵌口令显式优先，
  不建议写进 crontab 明文（用 `Environment=` + 受限权限文件或 secrets 管理）；
- **输出落盘与轮转**：报告 JSON 按日期命名（示例用 `$(date +%F)`），建议配 logrotate
  或定期清理，避免巡检目录无限增长；
- **数据不出本地**：巡检报告含 schema 元数据，落盘目录权限应收紧（0700）。
