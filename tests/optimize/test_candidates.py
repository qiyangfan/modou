"""规则初筛层测试：谓词列提取 → 索引候选 + 确定性发现（纯静态，sqlglot AST）。"""

from __future__ import annotations

import pytest

from modou.optimize.candidates import (
    IndexCandidate,
    StatementTypeError,
    analyze_statement,
    build_index_ddl,
    is_covered_by_existing,
)


class TestStatementTypeGuard:
    def test_ddl_rejected(self) -> None:
        with pytest.raises(StatementTypeError):
            analyze_statement("CREATE TABLE t (id int)", "shop")

    def test_supported_statement_types(self) -> None:
        for sql in (
            "SELECT * FROM orders WHERE user_id = 1",
            "UPDATE orders SET status = 1 WHERE id = 2",
            "DELETE FROM orders WHERE id = 3",
        ):
            analysis = analyze_statement(sql, "shop")
            assert analysis.table


class TestPredicateExtraction:
    def test_equality_then_range_column_order(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = 1 AND created_at > '2026-01-01'", "shop")
        candidates = analysis.candidates
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.table == "orders"
        assert candidate.columns == ["user_id", "created_at"]
        assert candidate.database == "shop"

    def test_range_only_candidate(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE amount > 100", "shop")
        assert analysis.candidates[0].columns == ["amount"]

    def test_in_predicate_counts_as_equality(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE status IN (1, 2, 3)", "shop")
        assert analysis.candidates[0].columns == ["status"]

    def test_prefix_like_counts_as_equality(self) -> None:
        analysis = analyze_statement("SELECT * FROM users WHERE name LIKE 'zh%'", "shop")
        assert analysis.candidates[0].columns == ["name"]

    def test_order_by_appended_when_equality_only(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = 1 ORDER BY created_at DESC LIMIT 10", "shop")
        assert analysis.candidates[0].columns == ["user_id", "created_at"]

    def test_order_by_not_appended_when_range_present(self) -> None:
        analysis = analyze_statement(
            "SELECT * FROM orders WHERE user_id = 1 AND amount > 5 ORDER BY created_at", "shop"
        )
        assert analysis.candidates[0].columns == ["user_id", "amount"]

    def test_join_column_candidate_for_inner_table(self) -> None:
        analysis = analyze_statement(
            "SELECT * FROM orders o JOIN users u ON o.user_id = u.id WHERE o.amount > 10", "shop"
        )
        by_table = {c.table: c.columns for c in analysis.candidates}
        assert by_table["users"] == ["id"]
        assert "user_id" in by_table.get("orders", [])

    def test_update_and_delete_where_extracted(self) -> None:
        update = analyze_statement("UPDATE orders SET status = 2 WHERE order_no = 'A1'", "shop")
        delete = analyze_statement("DELETE FROM orders WHERE order_no = 'A1'", "shop")
        assert update.candidates[0].columns == ["order_no"]
        assert delete.candidates[0].columns == ["order_no"]

    def test_or_branches_skipped_for_candidates(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = 1 OR user_id = 2", "shop")
        # OR 下不做单一列序结论（候选可能误导），仅产出发现
        assert analysis.candidates == []


class TestDeterministicFindings:
    def test_full_wildcard_like(self) -> None:
        analysis = analyze_statement("SELECT * FROM users WHERE name LIKE '%zh'", "shop")
        codes = [f.code for f in analysis.findings]
        assert "FULL_WILDCARD_LIKE" in codes

    def test_function_on_column(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE DATE(created_at) = '2026-01-01'", "shop")
        assert any(f.code == "FUNCTION_ON_COLUMN" for f in analysis.findings)
        # 列被函数包裹时不再产出候选（该列走不了索引）
        assert analysis.candidates == []

    def test_arithmetic_on_column(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE id + 1 = 3", "shop")
        assert any(f.code == "FUNCTION_ON_COLUMN" for f in analysis.findings)

    def test_or_condition_finding(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = 1 OR user_id = 2", "shop")
        assert any(f.code == "OR_CONDITION" for f in analysis.findings)

    def test_update_without_where(self) -> None:
        analysis = analyze_statement("UPDATE orders SET status = 1", "shop")
        assert any(f.code == "NO_WHERE" for f in analysis.findings)

    def test_select_without_where(self) -> None:
        analysis = analyze_statement("SELECT id FROM orders", "shop")
        assert any(f.code == "NO_WHERE" for f in analysis.findings)

    def test_delete_without_where(self) -> None:
        analysis = analyze_statement("DELETE FROM orders", "shop")
        assert any(f.code == "NO_WHERE" for f in analysis.findings)


class TestCandidateDedupAndCoverage:
    def test_duplicate_candidates_deduped(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = 1 AND user_id = 1 AND shop_id = 2", "shop")
        columns = [tuple(c.columns) for c in analysis.candidates]
        assert len(columns) == len(set(columns))

    def test_candidate_capped(self) -> None:
        conditions = " AND ".join([f"col_{i} = {i}" for i in range(20)])
        analysis = analyze_statement(f"SELECT * FROM wide WHERE {conditions}", "shop")
        assert len(analysis.candidates) <= 5

    def test_covered_by_existing_index(self) -> None:
        from modou.snapshot.model import IndexDef, IndexPart, TableDef

        table = TableDef(
            name="orders",
            engine="InnoDB",
            collation="",
            comment="",
            create_options="",
            ddl="",
            indexes=[
                IndexDef(
                    "idx_user_created",
                    False,
                    [IndexPart(1, "user_id", None, "A", None), IndexPart(2, "created_at", None, "A", None)],
                )
            ],
        )
        assert is_covered_by_existing(["user_id"], table) == "idx_user_created"
        assert is_covered_by_existing(["user_id", "created_at"], table) == "idx_user_created"
        assert is_covered_by_existing(["created_at"], table) is None


class TestIndexDdl:
    def test_basic_ddl(self) -> None:
        ddl = build_index_ddl(IndexCandidate("shop", "orders", ["user_id", "created_at"], "reason"))
        assert ddl == "ALTER TABLE `shop`.`orders` ADD INDEX `idx_user_id_created_at` (`user_id`, `created_at`)"

    def test_text_column_gets_prefix_length(self) -> None:
        from modou.snapshot.model import ColumnDef

        ddl = build_index_ddl(
            IndexCandidate("shop", "logs", ["message"], "reason"),
            columns_meta={"message": ColumnDef("message", 1, "text", True, None, "", None, "", "")},
        )
        assert "(`message`(64))" in ddl

    def test_no_database_ddl(self) -> None:
        ddl = build_index_ddl(IndexCandidate(None, "orders", ["id"], "reason"))
        assert ddl == "ALTER TABLE `orders` ADD INDEX `idx_id` (`id`)"


class TestAliasAndQualification:
    """覆盖别名、混合库限定和派生表中的候选解析。"""

    def test_alias_target_resolved_to_default_database(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders o WHERE o.user_id = 1", "shop")
        assert analysis.candidates[0].database == "shop"
        assert analysis.candidates[0].table == "orders"

    def test_mixed_qualified_and_unqualified_tables_no_crash(self) -> None:
        analysis = analyze_statement(
            "SELECT * FROM orders o JOIN shop.users u ON o.user_id = u.id WHERE o.amount > 10 AND u.status = 1",
            "shop",
        )
        by_table = {(c.database, c.table): c.columns for c in analysis.candidates}
        assert ("shop", "orders") in by_table
        assert ("shop", "users") in by_table

    def test_unqualified_alias_without_default_database_keeps_none(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders o WHERE o.user_id = 1", None)
        assert analysis.candidates[0].database is None

    def test_between_produces_range_candidate(self) -> None:
        analysis = analyze_statement(
            "SELECT * FROM orders WHERE created_at BETWEEN '2026-01-01' AND '2026-02-01'", "shop"
        )
        assert not any(f.code == "FUNCTION_ON_COLUMN" for f in analysis.findings)
        assert analysis.candidates[0].columns == ["created_at"]

    def test_is_null_and_not_are_not_function_findings(self) -> None:
        for sql in (
            "SELECT * FROM orders WHERE user_id IS NULL",
            "SELECT * FROM orders WHERE NOT user_id = 1",
        ):
            analysis = analyze_statement(sql, "shop")
            assert not any(f.code == "FUNCTION_ON_COLUMN" for f in analysis.findings), sql

    def test_wrapped_column_message_names_the_wrapped_side(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE amount + 1 < user_id", "shop")
        messages = [f.message for f in analysis.findings if f.code == "FUNCTION_ON_COLUMN"]
        assert any("amount" in m for m in messages)

    def test_subquery_comparison_not_mislabeled(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = (SELECT max(id) FROM users)", "shop")
        assert not any(f.code == "FUNCTION_ON_COLUMN" for f in analysis.findings)

    def test_derived_table_produces_no_sentinel_candidate(self) -> None:
        analysis = analyze_statement("SELECT * FROM (SELECT id, user_id FROM orders) t WHERE t.user_id = 1", "shop")
        assert analysis.table == "?"
        assert all(c.table != "?" for c in analysis.candidates)

    def test_referenced_tables_normalized(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders o JOIN users u ON o.user_id = u.id", "shop")
        assert ("shop", "orders") in analysis.referenced_tables
        assert ("shop", "users") in analysis.referenced_tables


class TestCteAndWrappedBetween:
    def test_cte_statement_not_rejected_as_unknown_table(self) -> None:
        """CTE 名不是快照表：引用表校验不得要求快照包含 WITH 别名。"""
        analysis = analyze_statement("WITH top AS (SELECT id FROM orders) SELECT * FROM top WHERE id = 1", "shop")
        assert all(db_table[1] != "top" for db_table in analysis.referenced_tables)
        assert ("shop", "orders") in analysis.referenced_tables

    def test_between_with_wrapped_left_reports_finding(self) -> None:
        analysis = analyze_statement("SELECT * FROM orders WHERE ABS(amount) BETWEEN 1 AND 5", "shop")
        assert any(f.code == "FUNCTION_ON_COLUMN" and "amount" in f.message for f in analysis.findings)
