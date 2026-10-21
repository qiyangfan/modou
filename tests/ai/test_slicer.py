"""schema 切片器测试：验证上下文按语句触达范围裁剪。"""

from __future__ import annotations

import pytest

from modou.ai.slicer import slice_schema, touched_objects
from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    Snapshot,
    SnapshotMeta,
    TableDef,
)


def _table(name: str, *, columns: str = "int") -> TableDef:
    return TableDef(
        name=name,
        engine="InnoDB",
        collation="",
        comment="",
        create_options="",
        ddl=f"CREATE TABLE {name} (id int PRIMARY KEY)",
        columns=[ColumnDef("id", 1, columns, False, None, "", None, "", "")],
        indexes=[],
    )


def _snapshot() -> Snapshot:
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
                tables={"orders": _table("orders"), "users": _table("users")},
            ),
            "archive": DatabaseInventory(
                name="archive", charset="utf8mb4", collation="", tables={"logs": _table("logs")}
            ),
        },
    )


class TestTouchedObjects:
    def test_single_table_statement(self) -> None:
        touched = touched_objects("ALTER TABLE orders ADD COLUMN c int", default_database="shop")
        assert touched.tables == {("shop", "orders")}

    def test_qualified_table(self) -> None:
        touched = touched_objects("SELECT * FROM archive.logs", default_database=None)
        assert touched.tables == {("archive", "logs")}

    def test_cte_alias_excluded(self) -> None:
        touched = touched_objects(
            "WITH t AS (SELECT 1) SELECT * FROM t JOIN users ON users.id = t.id", default_database="shop"
        )
        assert ("shop", "users") in touched.tables
        assert ("shop", "t") not in touched.tables

    def test_use_statement_carries_context(self) -> None:
        touched = touched_objects("USE shop")
        assert touched.databases == {"shop"}

    def test_unparseable_statement_reports_not_usable(self) -> None:
        # 只有残缺结构才抛解析错误；sqlglot 会把乱码解析成标识符
        touched = touched_objects("SELECT * FROM orders WHERE note = 'unterminated", default_database="shop")
        assert touched.usable is False
        assert touched.tables == set()


class TestSliceSchema:
    def test_slice_keeps_touched_and_drops_unrelated_databases(self) -> None:
        sliced = slice_schema(["SELECT * FROM orders"], _snapshot(), default_database="shop", max_chars=100000)
        names = {(entry["database"], entry["table"]) for entry in sliced}
        assert ("shop", "orders") in names
        assert ("shop", "users") in names  # 同库补充上下文
        assert ("archive", "logs") not in names  # 无关库被裁剪

    def test_touched_entries_survive_tight_budget(self) -> None:
        """触达表必含（预算约束的是补充上下文）；单条目不被截半。"""
        sliced = slice_schema(["SELECT * FROM orders"], _snapshot(), default_database="shop", max_chars=1)
        assert [entry["table"] for entry in sliced] == ["orders"]
        assert sliced[0]["database"] == "shop"

    def test_tight_budget_excludes_cross_database_filler(self) -> None:
        touched_both = ["SELECT * FROM orders", "SELECT * FROM archive.logs"]
        sliced = slice_schema(touched_both, _snapshot(), default_database="shop", max_chars=1)
        names = {(entry["database"], entry["table"]) for entry in sliced}
        assert ("shop", "orders") in names and ("archive", "logs") in names
        assert ("shop", "users") not in names  # 预算耗尽，补充上下文被裁

    def test_no_schema_touch_returns_empty(self) -> None:
        assert slice_schema(["CREATE PROCEDURE p() BEGIN END"], _snapshot(), default_database="shop") == []
        assert slice_schema([], _snapshot(), default_database="shop") == []

    def test_unknown_table_yields_no_entry(self) -> None:
        sliced = slice_schema(["SELECT * FROM ghost"], _snapshot(), default_database="shop", max_chars=100000)
        assert sliced == []

    def test_entry_shape_is_metadata_only(self) -> None:
        (entry,) = slice_schema(["SELECT * FROM orders"], _snapshot(), default_database="shop", max_chars=1)
        assert set(entry) == {"database", "table", "engine", "columns", "indexes"}

    @pytest.mark.parametrize("sql", ["", "   ", ";"])
    def test_blank_statement_is_noop(self, sql: str) -> None:
        assert slice_schema([sql], _snapshot(), default_database="shop") == []
