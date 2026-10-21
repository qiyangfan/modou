"""快照摘要测试：MCP 与 CLI 共用同一份输出。"""

from __future__ import annotations

from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    Snapshot,
    SnapshotMeta,
    TableDef,
    TableSample,
)
from modou.snapshot.summary import snapshot_summary


def _snapshot() -> Snapshot:
    table = TableDef(
        name="orders",
        engine="InnoDB",
        collation="",
        comment="",
        create_options="",
        ddl="CREATE TABLE orders (id int PRIMARY KEY)",
        columns=[
            ColumnDef("id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("user_id", 2, "int", True, None, "", None, "", ""),
        ],
        indexes=[],
        sample=TableSample(columns=["id"], rows=[[1]], sampled_rows=2),
    )
    return Snapshot(
        format_version=2,
        tool_version="0.5.0",
        captured_at="2026-10-16T00:00:00+00:00",
        meta=SnapshotMeta("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
        databases={
            "shop": DatabaseInventory(
                name="shop",
                charset="utf8mb4",
                collation="",
                tables={"orders": table},
            )
        },
    )


class TestSnapshotSummary:
    def test_shape_counts_and_table_details(self) -> None:
        summary = snapshot_summary(_snapshot())
        assert summary["server_version"] == "8.4.6"
        (db,) = summary["databases"].values()
        assert db["tables"] == 1
        assert db["views"] == 0 and db["procedures"] == 0
        (detail,) = db["table_details"]
        assert detail == {"table": "orders", "columns": 2, "indexes": 0, "sampled_rows": 2}

    def test_metadata_only_no_sample_rows_leaked(self) -> None:
        """摘要只含元数据，采样数据行不得出现。"""
        import json

        text = json.dumps(snapshot_summary(_snapshot()), ensure_ascii=False)
        assert "SECRET" not in text
        assert "[[1]]" not in text

    def test_empty_snapshot_yields_empty_databases(self) -> None:
        empty = Snapshot(
            format_version=2,
            tool_version="t",
            captured_at="c",
            meta=SnapshotMeta("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
            databases={},
        )
        assert snapshot_summary(empty) == {"server_version": "8.4.6", "databases": {}}
