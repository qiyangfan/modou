"""快照摘要（证据原语，ADR-0009 委托面）：CLI --report-json 与 MCP 工具共用的
单一事实源。

仅元数据：库 → 对象计数 + 表清单（列/索引数、采样行数）——采样数据行绝不进
摘要（数据不出本地）。委托 Agent 据此理解结构；全文结构仍在快照文件本体，
需要时按路径自读。
"""

from __future__ import annotations

from modou.snapshot.model import Snapshot


def snapshot_summary(snapshot: Snapshot) -> dict:
    return {
        "server_version": snapshot.meta.server_version,
        "databases": {
            name: {
                "tables": len(inventory.tables),
                "views": len(inventory.views),
                "procedures": len(inventory.procedures),
                "functions": len(inventory.functions),
                "triggers": len(inventory.triggers),
                "events": len(inventory.events),
                "table_details": [
                    {
                        "table": table.name,
                        "columns": len(table.columns),
                        "indexes": len(table.indexes),
                        "sampled_rows": table.sample.sampled_rows if table.sample is not None else None,
                    }
                    for _, table in sorted(inventory.tables.items())
                ],
            }
            for name, inventory in sorted(snapshot.databases.items())
        },
    }
