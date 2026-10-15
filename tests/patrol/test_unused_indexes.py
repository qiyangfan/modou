"""未用索引分层判定测试（纯逻辑，计数与 uptime 注入）。"""

from __future__ import annotations

import pytest

from modou.optimize.sideeffects import IndexView, find_redundant_pairs
from modou.patrol.unused_indexes import (
    STATUS_CONFIRMED_UNUSED,
    STATUS_EXCLUDED_FK,
    STATUS_EXCLUDED_UNIQUE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_LOW_USE,
    find_redundant_from_inventory,
    judge_unused_indexes,
)
from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    ForeignKeyDef,
    IndexDef,
    IndexPart,
    TableDef,
)

SEVEN_DAYS = 7 * 86400


def _table(
    name: str = "orders", indexes: list[IndexDef] | None = None, fks: list[ForeignKeyDef] | None = None
) -> TableDef:
    return TableDef(
        name=name,
        engine="InnoDB",
        collation="",
        comment="",
        create_options="",
        ddl="",
        columns=[
            ColumnDef("id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("user_id", 2, "int", True, None, "", None, "", ""),
            ColumnDef("b", 3, "int", True, None, "", None, "", ""),
        ],
        indexes=indexes or [],
        foreign_keys=fks or [],
    )


def _idx(name: str, cols: list[str], unique: bool = False) -> IndexDef:
    return IndexDef(name, unique, [IndexPart(i + 1, c, None, "A", None) for i, c in enumerate(cols)])


def _inv(tables: list[TableDef]) -> DatabaseInventory:
    return DatabaseInventory(name="shop", charset="utf8mb4", collation="", tables={t.name: t for t in tables})


class TestLayeredJudgment:
    def test_confirmed_unused(self) -> None:
        inv = _inv([_table(indexes=[_idx("idx_dead", ["b"])])])
        usages = judge_unused_indexes(inv, {}, uptime_seconds=SEVEN_DAYS, observe_days=7)
        assert usages[0].status == STATUS_CONFIRMED_UNUSED
        assert usages[0].drop_statement is not None
        assert "DROP INDEX" in usages[0].drop_statement

    def test_insufficient_data_when_uptime_short(self) -> None:
        inv = _inv([_table(indexes=[_idx("idx_dead", ["b"])])])
        usages = judge_unused_indexes(inv, {}, uptime_seconds=3600, observe_days=7)
        assert usages[0].status == STATUS_INSUFFICIENT_DATA

    def test_low_use_with_metrics(self) -> None:
        inv = _inv([_table(indexes=[_idx("idx_a", ["user_id"]), _idx("idx_b", ["b"])])])
        counts = {("orders", "idx_a"): 100, ("orders", "idx_b"): 10}
        usages = judge_unused_indexes(inv, counts, uptime_seconds=SEVEN_DAYS)
        low = {u.index_name: u for u in usages if u.status == STATUS_LOW_USE}
        assert set(low) == {"idx_a", "idx_b"}
        assert low["idx_b"].table_share_pct == pytest.approx(9.09, rel=0.01)
        assert low["idx_a"].daily_average == pytest.approx(100 / 7, rel=0.01)

    def test_unique_index_excluded_with_reason(self) -> None:
        inv = _inv([_table(indexes=[_idx("uk_b", ["b"], unique=True)])])
        usages = judge_unused_indexes(inv, {}, uptime_seconds=SEVEN_DAYS)
        assert usages[0].status == STATUS_EXCLUDED_UNIQUE
        assert "唯一" in usages[0].note

    def test_fk_dependent_index_excluded(self) -> None:
        fk = ForeignKeyDef("fk_user", ["user_id"], "users", ["id"], "NO ACTION", "NO ACTION")
        inv = _inv([_table(indexes=[_idx("idx_user", ["user_id"])], fks=[fk])])
        usages = judge_unused_indexes(inv, {}, uptime_seconds=SEVEN_DAYS)
        assert usages[0].status == STATUS_EXCLUDED_FK

    def test_primary_key_never_judged(self) -> None:
        inv = _inv([_table(indexes=[IndexDef("PRIMARY", True, [IndexPart(1, "id", None, "A", None)])])])
        assert judge_unused_indexes(inv, {}, uptime_seconds=SEVEN_DAYS) == []


class TestRedundantOffline:
    def test_prefix_case_with_drop_statement(self) -> None:
        inv = _inv([_table(indexes=[_idx("idx_a", ["user_id"]), _idx("idx_ab", ["user_id", "b"])])])
        redundancies = find_redundant_from_inventory(inv)
        assert len(redundancies) == 1
        assert redundancies[0].redundant_index == "idx_a"
        assert redundancies[0].dominant_index == "idx_ab"
        assert "DROP INDEX `idx_a`" in redundancies[0].drop_statement

    def test_fk_protected_redundancy_flagged(self) -> None:
        fk = ForeignKeyDef("fk_user", ["user_id"], "users", ["id"], "NO ACTION", "NO ACTION")
        inv = _inv([_table(indexes=[_idx("idx_ab", ["user_id", "b"])], fks=[fk])])
        # idx_ab 是 FK 依赖索引且被 PRIMARY 前缀覆盖？PRIMARY 未列出，不判冗余；
        # 构造 UNIQUE(user_id) 使 idx_ab 冗余但 idx_ab 被 FK 保护
        inv.tables["orders"].indexes.append(_idx("uk_user", ["user_id"], unique=True))
        redundancies = find_redundant_from_inventory(inv)
        target = [r for r in redundancies if r.redundant_index == "idx_ab"]
        assert target and target[0].fk_protected is True

    def test_unique_never_redundant_side(self) -> None:
        inv = _inv([_table(indexes=[_idx("uk_a", ["user_id"], unique=True), _idx("idx_ab", ["user_id", "b"])])])
        redundancies = find_redundant_from_inventory(inv)
        assert all(r.redundant_index != "uk_a" for r in redundancies)

    def test_pair_function_contract(self) -> None:
        """三情形与 optimize 侧共享同一实现（防两处漂移）。"""
        pool = [IndexView("a", ["x"], False, False), IndexView("b", ["x", "y"], False, False)]
        redundant = find_redundant_pairs(pool)
        assert (redundant[0][0].name, redundant[0][2]) == ("a", "prefix_non_unique")


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self._last = sql

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class TestReadUptime:
    def test_missing_uptime_row_is_value_error(self) -> None:
        """uptime 缺行是环境异常（ValueError→退出码 2 口径），不是 p_s 关闭。"""
        from modou.patrol.unused_indexes import read_uptime

        with pytest.raises(ValueError, match="uptime"):
            read_uptime(_FakeConn([]))
