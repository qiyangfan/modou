# CI 集成（pack 预警门禁示例）

[pack-gate.yml](pack-gate.yml) 是 GitHub Actions 上的**纯静态**集成示例：PR 触发
`modou pack`，把破坏性语句与锁风险预警回贴到 job summary，并演示一个可选的
destructive 卡点。

## 为什么只有 pack

宪法红线 4（数据不出本地）：`verify` / `optimize` / `snapshot capture` 的输入是
**含生产 schema 全文的快照**，进入托管 CI 即数据出本地。owner 定调（2026-10-14）：
影子层不接入托管 CI，唯一适合 CI 的切片是 pack 预警——纯静态、零容器、零数据库
连接。需要 CI 化验收的团队请在本机 runner 自跑（本地门禁口径）。

## 使用

1. 复制 `pack-gate.yml` 到 `.github/workflows/`，改 `CHANGESET_DIR` 与触发路径；
2. 按团队口径取舍「可选卡点」（`level: high` 即失败 / 仅提示）。

## 红线声明

**验收类命令（verify / optimize / snapshot capture）禁止进入托管 CI。**
其产物含生产 schema 全文；示例只含 pack（零连接、零数据出本地）。
