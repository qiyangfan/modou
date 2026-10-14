# 任务：v0.1 变更车道纵切面

## 1. 变更集发现与清单校验

- [x] 测试先行：manifest 缺文件/多文件/序号重复/含下划线命名四类失败用例
- [x] 实现 changeset 发现器：目录扫描、`V<序号>__` 解析、manifest 比对
- [x] 快照采集脚本：只读语句清单 + 导出格式定义（含版本与字符集元信息）

## 2. pack 打包

- [x] 测试先行：合并顺序、分号边界（存储过程/触发器 DELIMITER）、破坏性语句识别
- [x] 实现 `modou pack`：合并产物 + 破坏性预警（DROP/TRUNCATE/无 WHERE 的 UPDATE/DELETE）
- [x] 大表 ALTER 的锁风险标注（按 MySQL 版本给 INSTANT/INPLACE/COPY 与 pt-osc/gh-ost 建议）

## 3. 影子回放

- [x] 容器 fixture：同版本 MySQL 的拉起/灌入/销毁（testcontainers 或 podman）
- [x] 快照灌入器：执行前快照 → 影子库基线；round-trip 保真用例（字符集/触发器/存储过程）
- [x] 回放器：变更集在影子库执行 = 期望态；执行失败产出可读错误

## 4. 三方 diff 与 verify

- [x] 测试先行：漏执行/错执行（类型或索引不一致）/历史漂移三类构造用例
- [x] 结构化 diff：表/列/索引/约束逐维对比，输出统一报告（文本 + JSON）
- [x] `modou verify`：确定性退出码（0=一致；1=发现差异；2=环境错误），多库清单循环

## 5. 端到端验收

- [x] 集成测试：真实形态变更集 + 人工构造漏执行，verify 必须抓到并指认缺失语句
- [x] 实证记录：以本仓自带样例变更集跑通全链路，记录写入 docs/HANDOFF.md
