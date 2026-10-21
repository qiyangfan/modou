"""optimize 测试共用夹具：构造结构/采样快照。"""

from __future__ import annotations

from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    IndexDef,
    IndexPart,
    Snapshot,
    SnapshotMeta,
    TableDef,
    TableSample,
)


def make_orders_table(*, with_sample: bool = False, extra_indexes: list[IndexDef] | None = None) -> TableDef:
    table = TableDef(
        name="orders",
        engine="InnoDB",
        collation="utf8mb4_0900_ai_ci",
        comment="",
        create_options="",
        ddl=(
            "CREATE TABLE `orders` ("
            "`id` int NOT NULL, "
            "`user_id` int DEFAULT NULL, "
            "`amount` decimal(10,2) DEFAULT NULL, "
            "`status` int DEFAULT NULL, "
            "PRIMARY KEY (`id`)"
            ")"
        ),
        columns=[
            ColumnDef("id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("user_id", 2, "int", True, None, "", None, "", ""),
            ColumnDef("amount", 3, "decimal(10,2)", True, None, "", None, "", ""),
            ColumnDef("status", 4, "int", True, None, "", None, "", ""),
        ],
        indexes=[IndexDef("PRIMARY", True, [IndexPart(1, "id", None, "A", None)]), *(extra_indexes or [])],
    )
    if with_sample:
        table.sample = TableSample(
            columns=["id", "user_id", "amount", "status"],
            rows=[[i, i % 50, i * 1.5, i % 3] for i in range(1, 201)],
            sampled_rows=200,
            estimated_rows=2000,
            method="primary_key_asc",
        )
    return table


def make_snapshot(
    *, with_sample: bool = False, format_version: int = 2, tables: list[TableDef] | None = None
) -> Snapshot:
    table_map = {t.name: t for t in (tables if tables is not None else [make_orders_table(with_sample=with_sample)])}
    return Snapshot(
        format_version=format_version,
        tool_version="0.2.0",
        captured_at="2026-10-15T00:00:00+00:00",
        meta=SnapshotMeta(
            server_version="8.4.6",
            version_comment="MySQL Community Server - GPL",
            character_set_server="utf8mb4",
            collation_server="utf8mb4_0900_ai_ci",
            lower_case_table_names=0,
            sql_mode="ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES",
        ),
        databases={
            "shop": DatabaseInventory(
                name="shop",
                charset="utf8mb4",
                collation="utf8mb4_0900_ai_ci",
                tables=table_map,
            )
        },
    )
