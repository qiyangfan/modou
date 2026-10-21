"""漂移巡检测试：三类分类（新增/缺失/定义变更）与多库聚合。"""

from __future__ import annotations

from modou.patrol.drift import CATEGORY_ADDED, CATEGORY_CHANGED, CATEGORY_REMOVED, drift_between_snapshots
from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    IndexDef,
    IndexPart,
    ObjectDef,
    TableDef,
)


def _db(name: str, tables: list[TableDef], views: dict[str, ObjectDef] | None = None) -> DatabaseInventory:
    return DatabaseInventory(
        name=name,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
        tables={t.name: t for t in tables},
        views=views or {},
    )


def _orders(indexes: list[IndexDef] | None = None, columns: list[ColumnDef] | None = None) -> TableDef:
    return TableDef(
        name="orders",
        engine="InnoDB",
        collation="utf8mb4_0900_ai_ci",
        comment="",
        create_options="",
        ddl="CREATE TABLE orders (id int PRIMARY KEY)",
        columns=columns or [ColumnDef("id", 1, "int", False, None, "", None, "", "")],
        indexes=indexes or [IndexDef("PRIMARY", True, [IndexPart(1, "id", None, "A", None)])],
    )


class TestTwoWayDiff:
    def test_no_drift(self) -> None:
        db = _db("shop", [_orders()])
        report = drift_between_snapshots({"shop": db}, {"shop": _db("shop", [_orders()])})
        assert report.exit_code == 0

    def test_index_added(self) -> None:
        before = _db("shop", [_orders()])
        after = _db(
            "shop",
            [
                _orders(
                    indexes=[
                        IndexDef("PRIMARY", True, [IndexPart(1, "id", None, "A", None)]),
                        IndexDef("idx_new", False, [IndexPart(1, "id", None, "A", None)]),
                    ]
                )
            ],
        )
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        conclusions = report.conclusions["shop"]
        added = [c for c in conclusions if c.category == CATEGORY_ADDED]
        assert len(added) == 1
        assert added[0].object_name == "orders"
        assert "indexes" in added[0].dimensions

    def test_table_removed(self) -> None:
        before = _db(
            "shop",
            [_orders(), TableDef(name="logs", engine="InnoDB", collation="", comment="", create_options="", ddl="")],
        )
        after = _db("shop", [_orders()])
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        removed = [c for c in report.conclusions["shop"] if c.category == CATEGORY_REMOVED]
        assert len(removed) == 1
        assert removed[0].object_name == "logs"

    def test_table_added(self) -> None:
        before = _db("shop", [_orders()])
        after = _db(
            "shop",
            [_orders(), TableDef(name="t2", engine="InnoDB", collation="", comment="", create_options="", ddl="")],
        )
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        added = [c for c in report.conclusions["shop"] if c.category == CATEGORY_ADDED]
        assert [c.object_name for c in added] == ["t2"]

    def test_column_changed(self) -> None:
        before = _db("shop", [_orders(columns=[ColumnDef("id", 1, "int", False, None, "", None, "", "")])])
        after = _db("shop", [_orders(columns=[ColumnDef("id", 1, "bigint", False, None, "", None, "", "")])])
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        changed = [c for c in report.conclusions["shop"] if c.category == CATEGORY_CHANGED]
        assert len(changed) == 1
        assert "columns" in changed[0].dimensions

    def test_column_added(self) -> None:
        before = _db("shop", [_orders(columns=[ColumnDef("id", 1, "int", False, None, "", None, "", "")])])
        after = _db(
            "shop",
            [
                _orders(
                    columns=[
                        ColumnDef("id", 1, "int", False, None, "", None, "", ""),
                        ColumnDef("amount", 2, "decimal(10,2)", True, "0", "", None, "", ""),
                    ]
                )
            ],
        )
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        added = [c for c in report.conclusions["shop"] if c.category == CATEGORY_ADDED]
        assert len(added) == 1
        assert "columns" in added[0].dimensions

    def test_view_definition_changed(self) -> None:
        before = _db("shop", [_orders()], views={"v": ObjectDef(name="v", ddl="CREATE VIEW v AS SELECT 1")})
        after = _db("shop", [_orders()], views={"v": ObjectDef(name="v", ddl="CREATE VIEW v AS SELECT 2")})
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        changed = [c for c in report.conclusions["shop"] if c.category == CATEGORY_CHANGED]
        assert len(changed) == 1
        assert changed[0].object_type == "view"

    def test_database_charset_drift(self) -> None:
        before = _db("shop", [_orders()])
        after = DatabaseInventory(
            name="shop", charset="latin1", collation="latin1_swedish_ci", tables={"orders": _orders()}
        )
        report = drift_between_snapshots({"shop": before}, {"shop": after})
        changed = [c for c in report.conclusions["shop"] if c.category == CATEGORY_CHANGED]
        assert any(c.object_type == "database" for c in changed)

    def test_multi_database_aggregation(self) -> None:
        before = {"a": _db("a", [_orders()]), "b": _db("b", [_orders()])}
        after = {"a": _db("a", [_orders()]), "b": _db("b", [])}
        report = drift_between_snapshots(before, after)
        assert set(report.conclusions) == {"b"}
        assert report.count(CATEGORY_REMOVED) >= 1

    def test_new_database_in_current(self) -> None:
        before: dict = {}
        after = {"new": _db("new", [_orders()])}
        report = drift_between_snapshots(before, after)
        added = report.conclusions["new"]
        assert all(c.category == CATEGORY_ADDED for c in added)


class TestWhitespaceOnlyDdl:
    """DDL 仅有空白差异时不报告漂移。"""

    def test_whitespace_only_view_change_is_not_drift(self) -> None:

        from modou.snapshot.model import DatabaseInventory, ObjectDef

        def inventory(view_ddl: str) -> DatabaseInventory:
            return DatabaseInventory(
                name="shop",
                charset="utf8mb4",
                collation="utf8mb4_0900_ai_ci",
                views={"v": ObjectDef(name="v", ddl=view_ddl)},
            )

        baseline = {"shop": inventory("CREATE VIEW v AS\nSELECT\n    id\nFROM t")}
        current = {"shop": inventory("CREATE VIEW v AS SELECT id FROM t")}
        report = drift_between_snapshots(baseline, current)
        assert report.exit_code == 0
        assert report.conclusions == {}
