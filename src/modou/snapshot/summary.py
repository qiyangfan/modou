"""生成供 CLI 和 MCP 共用的快照元数据摘要，不包含采样数据行。"""

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
