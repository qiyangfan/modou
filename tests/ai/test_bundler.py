"""变更分包器测试（design §4：按库/语句组分包，并发单轮聚合的确定性前提）。"""

from __future__ import annotations

from modou.ai.bundler import StatementUnit, bundle_units


def _unit(sql: str, database: str | None = None, file: str = "V01__x.sql", line: int = 1) -> StatementUnit:
    return StatementUnit(file=file, line=line, sql=sql, database=database)


class TestBundleUnits:
    def test_groups_by_database_never_mixes(self) -> None:
        units = [_unit("A1", "a"), _unit("A2", "a"), _unit("B1", "b"), _unit("N1", None)]
        batches = bundle_units(units, max_statements=10, max_chars=100000)
        dbs_per_batch = [{u.database for u in batch} for batch in batches]
        assert all(len(dbs) == 1 for dbs in dbs_per_batch)
        # 组顺序 = 库首次出现序
        assert [next(iter(dbs)) for dbs in dbs_per_batch] == ["a", "b", None]

    def test_respects_max_statements(self) -> None:
        units = [_unit(f"S{i}", "a") for i in range(5)]
        batches = bundle_units(units, max_statements=2, max_chars=100000)
        assert [len(batch) for batch in batches] == [2, 2, 1]

    def test_respects_char_budget(self) -> None:
        units = [_unit("x" * 100, "a"), _unit("y" * 100, "a"), _unit("z" * 100, "a")]
        batches = bundle_units(units, max_statements=10, max_chars=250)
        assert all(sum(len(u.sql) for u in batch) <= 250 for batch in batches)

    def test_oversized_unit_stays_alone_not_dropped(self) -> None:
        big = _unit("b" * 500, "a")
        batches = bundle_units([big, _unit("small", "a")], max_statements=10, max_chars=100)
        flattened = [u for batch in batches for u in batch]
        assert flattened == [big, _unit("small", "a")]
        assert [len(batch) for batch in batches] == [1, 1]

    def test_all_units_present_exactly_once(self) -> None:
        units = [_unit(f"S{i}", db) for i, db in enumerate(["a", "b", "a", None, "b", "a"])]
        flattened = [u for batch in bundle_units(units) for u in batch]
        assert sorted(u.sql for u in flattened) == sorted(u.sql for u in units)
        assert len({id(u) for u in flattened}) == len(units)

    def test_empty_input(self) -> None:
        assert bundle_units([]) == []
