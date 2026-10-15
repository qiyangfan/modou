"""副作用检查测试：冗余三情形（sys.schema_redundant_indexes 语义）、唯一性语义
保留、外键依赖、索引数上限与写放大提示。"""

from __future__ import annotations

from modou.optimize.sideeffects import (
    IndexView,
    check_candidate_side_effects,
    find_redundant_pairs,
    fk_required_index_names,
    index_views_from_table,
)
from modou.snapshot.model import (
    ColumnDef,
    ForeignKeyDef,
    IndexDef,
    IndexPart,
    TableDef,
)


def _index(name: str, columns: list[str], unique: bool = False) -> IndexDef:
    return IndexDef(name, unique, [IndexPart(i + 1, col, None, "A", None) for i, col in enumerate(columns)])


def _table(indexes: list[IndexDef], foreign_keys: list[ForeignKeyDef] | None = None) -> TableDef:
    return TableDef(
        name="orders",
        engine="InnoDB",
        collation="",
        comment="",
        create_options="",
        ddl="",
        columns=[
            ColumnDef("a", 1, "int", True, None, "", None, "", ""),
            ColumnDef("b", 2, "int", True, None, "", None, "", ""),
        ],
        indexes=indexes,
        foreign_keys=foreign_keys or [],
    )


class TestRedundantPairs:
    def test_case1_duplicate_columns(self) -> None:
        pool = [IndexView("idx_a", ["a"], False, False), IndexView("idx_a2", ["a"], False, False)]
        redundant = find_redundant_pairs(pool)
        assert [(r.name, d.name, case) for r, d, case in redundant] == [("idx_a", "idx_a2", "duplicate")]

    def test_case2_nonunique_prefix_redundant(self) -> None:
        pool = [IndexView("idx_a", ["a"], False, False), IndexView("idx_ab", ["a", "b"], False, False)]
        redundant = find_redundant_pairs(pool)
        assert [(r.name, d.name, case) for r, d, case in redundant] == [("idx_a", "idx_ab", "prefix_non_unique")]

    def test_case3_unique_prefix_makes_longer_redundant(self) -> None:
        pool = [IndexView("idx_ab", ["a", "b"], False, False), IndexView("uk_a", ["a"], True, False)]
        redundant = find_redundant_pairs(pool)
        assert [(r.name, d.name, case) for r, d, case in redundant] == [("idx_ab", "uk_a", "unique_prefix")]

    def test_unique_index_never_redundant_as_prefix_side(self) -> None:
        """唯一性语义不可丢：唯一索引不能被更长的索引冗余掉。"""
        pool = [IndexView("uk_a", ["a"], True, False), IndexView("idx_ab", ["a", "b"], False, False)]
        redundant = find_redundant_pairs(pool)
        # 顺序无关：仍是长索引被判冗余
        assert all(r.name != "uk_a" for r, _d, _c in redundant)

    def test_no_false_positive_on_sibling_columns(self) -> None:
        pool = [IndexView("idx_b", ["b"], False, False), IndexView("idx_ab", ["a", "b"], False, False)]
        assert find_redundant_pairs(pool) == []


class TestCandidateSideEffects:
    def test_candidate_redundant_by_existing_prefix(self) -> None:
        table = _table([_index("idx_ab", ["a", "b"])])
        notes = check_candidate_side_effects(["a"], table, index_count_limit=10)
        kinds = [n.kind for n in notes]
        assert "CANDIDATE_REDUNDANT" in kinds
        redundant_note = next(n for n in notes if n.kind == "CANDIDATE_REDUNDANT")
        assert "idx_ab" in redundant_note.message

    def test_candidate_makes_existing_redundant(self) -> None:
        table = _table([_index("idx_a", ["a"])])
        notes = check_candidate_side_effects(["a", "b"], table, index_count_limit=10)
        kinds = [n.kind for n in notes]
        assert "EXISTING_BECOMES_REDUNDANT" in kinds

    def test_candidate_duplicate_of_existing(self) -> None:
        table = _table([_index("idx_a", ["a"])])
        notes = check_candidate_side_effects(["a"], table, index_count_limit=10)
        assert any(n.kind == "CANDIDATE_REDUNDANT" for n in notes)

    def test_fk_protected_existing_not_suggested_for_drop(self) -> None:
        fk = ForeignKeyDef("fk_a", ["a"], "users", ["id"], "NO ACTION", "NO ACTION")
        table = _table([_index("idx_a", ["a"])], foreign_keys=[fk])
        notes = check_candidate_side_effects(["a", "b"], table, index_count_limit=10)
        # 现有 idx_a 被 FK 依赖：不能建议 DROP，只能提示依赖保留
        assert any(n.kind == "FK_DEPENDENCY" for n in notes)
        assert not any(n.kind == "EXISTING_BECOMES_REDUNDANT" for n in notes)

    def test_index_count_limit(self) -> None:
        table = _table([_index(f"idx_{i}", [f"c{i}"]) for i in range(10)])
        notes = check_candidate_side_effects(["z"], table, index_count_limit=10)
        assert any(n.kind == "INDEX_COUNT" for n in notes)
        # 未超限时不告警
        table2 = _table([_index(f"idx_{i}", [f"c{i}"]) for i in range(3)])
        assert not any(
            n.kind == "INDEX_COUNT" for n in check_candidate_side_effects(["z"], table2, index_count_limit=10)
        )

    def test_write_amplification_note_always_present(self) -> None:
        table = _table([])
        notes = check_candidate_side_effects(["a"], table, index_count_limit=10)
        assert any(n.kind == "WRITE_AMPLIFICATION" for n in notes)

    def test_expression_only_index_skipped_in_comparisons(self) -> None:
        """函数/表达式索引没有可比的普通列序：跳过比较而非误判。"""
        table = _table([IndexDef("idx_expr", False, [IndexPart(1, None, None, "", "upper(`a`)")])])
        notes = check_candidate_side_effects(["a"], table, index_count_limit=10)
        assert not any(n.kind == "CANDIDATE_REDUNDANT" for n in notes)


class TestFkRequiredIndexes:
    def test_prefix_match_detected(self) -> None:
        fk = ForeignKeyDef("fk_a", ["a"], "users", ["id"], "NO ACTION", "NO ACTION")
        table = _table([_index("idx_ab", ["a", "b"])], foreign_keys=[fk])
        assert fk_required_index_names(table) == {"idx_ab"}

    def test_unrelated_index_not_required(self) -> None:
        fk = ForeignKeyDef("fk_a", ["a"], "users", ["id"], "NO ACTION", "NO ACTION")
        table = _table([_index("idx_b", ["b"])], foreign_keys=[fk])
        assert fk_required_index_names(table) == set()


class TestIndexViewsFromTable:
    def test_expression_parts_excluded_from_columns(self) -> None:
        table = _table([_index("idx_a", ["a"])])
        table.indexes.append(
            IndexDef(
                "idx_expr", False, [IndexPart(1, "a", None, "A", None), IndexPart(2, None, None, "", "upper(`b`)")]
            )
        )
        views = {v.name: v for v in index_views_from_table(table)}
        assert views["idx_a"].columns == ["a"]
        assert views["idx_expr"].columns == ["a"]  # 表达式部分不计入列序
        # 混合表达式索引整条不可比（最左前缀是表达式，普通列序比较会误判冗余）
        assert views["idx_expr"].expression_only is True

    def test_full_expression_index_flagged(self) -> None:
        table = _table([IndexDef("idx_expr", False, [IndexPart(1, None, None, "", "upper(`b`)")])])
        views = index_views_from_table(table)
        assert views[0].expression_only is True


class TestPrefixIndexSemantics:
    def test_full_column_candidate_not_redundant_with_prefix_index(self) -> None:
        """前缀索引 a(64) 与完整列索引不等价：候选不得被判冗余而跳过实证。"""
        from modou.snapshot.model import IndexDef, IndexPart, TableDef

        table = TableDef(
            name="t",
            engine="InnoDB",
            collation="",
            comment="",
            create_options="",
            ddl="",
            indexes=[
                IndexDef("idx_a_prefix", False, [IndexPart(1, "a", 64, "A", None)]),
            ],
        )
        notes = check_candidate_side_effects(["a"], table)
        assert not any(note.kind == "CANDIDATE_REDUNDANT" for note in notes)

    def test_full_column_existing_still_duplicate(self) -> None:
        from modou.snapshot.model import IndexDef, IndexPart, TableDef

        table = TableDef(
            name="t",
            engine="InnoDB",
            collation="",
            comment="",
            create_options="",
            ddl="",
            indexes=[IndexDef("idx_a", False, [IndexPart(1, "a", None, "A", None)])],
        )
        notes = check_candidate_side_effects(["a"], table)
        assert any(note.kind == "CANDIDATE_REDUNDANT" for note in notes)


class TestMixedExpressionIndex:
    def test_mixed_expression_index_not_compared_by_column_tail(self) -> None:
        """(LOWER(name), age) 的最左前缀是表达式：候选 (age) 不得被判冗余跳过实证。"""
        from modou.snapshot.model import IndexDef, IndexPart, TableDef

        table = TableDef(
            name="t",
            engine="InnoDB",
            collation="",
            comment="",
            create_options="",
            ddl="",
            indexes=[
                IndexDef(
                    "idx_name_age",
                    False,
                    [
                        IndexPart(1, None, None, "", "LOWER(`name`)"),
                        IndexPart(2, "age", None, "A", None),
                    ],
                )
            ],
        )
        notes = check_candidate_side_effects(["age"], table)
        assert not any(note.kind == "CANDIDATE_REDUNDANT" for note in notes)
