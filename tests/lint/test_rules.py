"""26 条规则逐条正反例（spec：每条规则正例命中、反例不命中）。"""

from __future__ import annotations

import pytest

from modou.lint import RULES, Thresholds, lint_paths, lint_sql_text
from modou.lint.rules import get_rule

POSITIVE_CASES: dict[str, str] = {
    "ARG.001": "SELECT * FROM users WHERE name LIKE '%zh'",
    "ARG.004": "SELECT * FROM t WHERE a IN (1, NULL)",
    "ARG.005": "SELECT * FROM t WHERE a IN (" + ", ".join(str(i) for i in range(101)) + ")",
    "ARG.006": "SELECT * FROM t WHERE a IS NULL",
    "ARG.011": "SELECT * FROM t WHERE a NOT IN (1, 2)",
    "CLA.001": "SELECT id FROM orders",
    "CLA.002": "SELECT id FROM orders ORDER BY RAND()",
    "CLA.003": "SELECT id FROM orders WHERE a = 1 LIMIT 10 OFFSET 20000",
    "CLA.015": "UPDATE orders SET status = 1",
    "COL.001": "SELECT * FROM orders WHERE id = 1",
    "COL.002": "INSERT INTO orders VALUES (1, 'a')",
    "COL.005": "CREATE TABLE t (id INT COMMENT 'ok', name VARCHAR(50))",
    "COL.013": "CREATE TABLE t (id INT, ts TIMESTAMP NOT NULL)",
    "DIS.001": "SELECT DISTINCT id, name FROM users",
    "FUN.001": "SELECT * FROM orders WHERE DATE(created_at) = '2026-01-01'",
    "FUN.005": "SELECT COUNT(name) FROM users WHERE a = 1",
    "JOI.001": "SELECT * FROM a JOIN b ON a.id = b.id, c WHERE c.x = 1",
    "KEY.002": "CREATE TABLE t (id INT, name VARCHAR(50))",
    "KEY.005": "CREATE TABLE t (id INT, " + ", ".join(f"KEY idx_c{i} (c{i})" for i in range(11)) + ")",
    "KEY.007": "CREATE TABLE t (id VARCHAR(36) NOT NULL, PRIMARY KEY (id))",
    "LCK.002": "INSERT INTO t (a) VALUES (1) ON DUPLICATE KEY UPDATE a = 1",
    "RES.002": "SELECT id FROM orders WHERE a = 1 LIMIT 10",
    "RES.003": "DELETE FROM orders WHERE a = 1 LIMIT 5",
    "SEC.002": "CREATE TABLE users (id INT, password VARCHAR(64))",
    "STA.003": "CREATE TABLE t (id INT, KEY name (id))",
    "SUB.002": "SELECT a FROM x UNION SELECT a FROM y",
}

NEGATIVE_CASES: dict[str, str] = {
    "ARG.001": "SELECT * FROM users WHERE name LIKE 'zh%'",
    "ARG.004": "SELECT * FROM t WHERE a IN (1, 2)",
    "ARG.005": "SELECT * FROM t WHERE a IN (1, 2, 3)",
    "ARG.006": "SELECT * FROM t WHERE a = 1",
    "ARG.011": "SELECT * FROM t WHERE a IN (1, 2) AND b LIKE 'x%'",
    "CLA.001": "SELECT id FROM orders WHERE id = 1",
    "CLA.002": "SELECT id FROM orders ORDER BY created_at",
    "CLA.003": "SELECT id FROM orders WHERE a = 1 LIMIT 10 OFFSET 20",
    "CLA.015": "UPDATE orders SET status = 1 WHERE id = 2",
    "COL.001": "SELECT id, name FROM orders WHERE id = 1",
    "COL.002": "INSERT INTO orders (id, name) VALUES (1, 'a')",
    "COL.005": "CREATE TABLE t (id INT COMMENT 'pk', name VARCHAR(50) COMMENT 'nm')",
    "COL.013": "CREATE TABLE t (id INT, ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "DIS.001": "SELECT DISTINCT name FROM users",
    "FUN.001": "SELECT * FROM orders WHERE created_at = '2026-01-01'",
    "FUN.005": "SELECT COUNT(*) FROM users WHERE a = 1",
    "JOI.001": "SELECT * FROM a JOIN b ON a.id = b.id JOIN c ON c.x = b.x",
    "KEY.002": "CREATE TABLE t (id INT NOT NULL, PRIMARY KEY (id))",
    "KEY.005": "CREATE TABLE t (id INT, " + ", ".join(f"KEY idx_c{i} (c{i})" for i in range(3)) + ")",
    "KEY.007": "CREATE TABLE t (id BIGINT UNSIGNED NOT NULL, PRIMARY KEY (id))",
    "LCK.002": "INSERT INTO t (a) VALUES (1)",
    "RES.002": "SELECT id FROM orders WHERE a = 1 ORDER BY id LIMIT 10",
    "RES.003": "DELETE FROM orders WHERE a = 1",
    "SEC.002": "CREATE TABLE users (id INT, password_hash VARCHAR(64))",
    "STA.003": "CREATE TABLE t (id INT, KEY idx_name (id))",
    "SUB.002": "SELECT a FROM x UNION ALL SELECT a FROM y",
}


class TestRulePositiveNegative:
    @pytest.mark.parametrize("rule_id", sorted(POSITIVE_CASES))
    def test_positive_case_hits(self, rule_id: str) -> None:
        sql = POSITIVE_CASES[rule_id]
        hits = lint_sql_text(sql, "t.sql", RULES)
        hit_ids = {h.rule_id for h in hits}
        assert rule_id in hit_ids, f"{rule_id} should hit: {sql!r} -> {sorted(hit_ids)}"

    @pytest.mark.parametrize("rule_id", sorted(NEGATIVE_CASES))
    def test_negative_case_clean(self, rule_id: str) -> None:
        sql = NEGATIVE_CASES[rule_id]
        hits = lint_sql_text(sql, "t.sql", RULES)
        hit_ids = {h.rule_id for h in hits}
        assert rule_id not in hit_ids, f"{rule_id} must not hit: {sql!r} -> {sorted(hit_ids)}"

    def test_registry_has_26_rules(self) -> None:
        assert len(RULES) >= 20
        assert len({r.rule_id for r in RULES}) == len(RULES)
        assert {r.level for r in RULES} <= {"error", "warning", "info"}

    def test_get_rule_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            get_rule("NOPE.001")


class TestEngineBehaviors:
    def test_unparseable_statement_recorded_and_audit_continues(self, tmp_path) -> None:
        """解析失败逐语句记录为工具命中（PARSE.001），整轮不中断。

        真链真实形态：版本条件注释（H2 兼容写法）解析不出表达式，后随可解析语句
        的规则命中必须照常产出（spec 2026-10-15 修订：非静默跳过 → 逐条记录）。
        """
        f = tmp_path / "cond.sql"
        f.write_text(
            "-- 对齐排序规则\n"
            "/*!50700 ALTER TABLE t MODIFY COLUMN c VARCHAR(64) NOT NULL */;\n"
            "UPDATE orders SET status = 1;\n",
            encoding="utf-8",
        )
        result = lint_paths([f], RULES)
        parse_hits = [h for h in result.hits if h.rule_id == "PARSE.001"]
        assert len(parse_hits) == 1
        assert parse_hits[0].level == "warning"
        assert parse_hits[0].line == 1
        assert parse_hits[0].file == str(f)
        assert parse_hits[0].message
        assert any(h.rule_id == "CLA.015" for h in result.hits)
        assert result.exit_code == 1

    def test_unparseable_hit_position_and_skip(self, tmp_path) -> None:
        f = tmp_path / "bad.sql"
        # 字符串引号不闭合 = 真不可解析（sqlglot 对乱码宽容、会把未知词解析成
        # 标识符；残缺结构才抛 ParseError——口径与解析器能力一致）
        f.write_text("SELECT 1;\nSELECT 'unclosed;\n", encoding="utf-8")
        result = lint_paths([f], RULES)
        parse_hits = [h for h in result.hits if h.rule_id == "PARSE.001"]
        assert len(parse_hits) == 1
        assert parse_hits[0].line == 2
        assert parse_hits[0].file == str(f)
        assert result.exit_code == 1
        # 工具命中可被既有跳过机制显式关闭，关闭后恢复 0
        skipped = lint_paths([f], RULES, disabled={"PARSE.001"})
        assert skipped.hits == []
        assert skipped.exit_code == 0

    def test_statement_line_mapping(self) -> None:
        text = "-- 说明\nSELECT id FROM orders;\n\nUPDATE orders SET status = 1;\n"
        hits = lint_sql_text(text, "t.sql", RULES)
        cla015 = [h for h in hits if h.rule_id == "CLA.015"]
        assert cla015 and cla015[0].line == 4

    def test_delimiter_block_preserved(self) -> None:
        text = "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END$$\nDELIMITER ;\nCREATE TABLE t (id INT)\n"
        hits = lint_sql_text(text, "t.sql", RULES)
        assert any(h.rule_id == "KEY.002" for h in hits)

    def test_thresholds_override(self) -> None:
        sql = "CREATE TABLE t (id INT, " + ", ".join(f"KEY idx_c{i} (c{i})" for i in range(4)) + ")"
        assert any(
            h.rule_id == "KEY.005" for h in lint_sql_text(sql, "t.sql", RULES, thresholds=Thresholds(index_count=3))
        )
        assert not any(
            h.rule_id == "KEY.005" for h in lint_sql_text(sql, "t.sql", RULES, thresholds=Thresholds(index_count=10))
        )

    def test_disabled_rules_skipped(self) -> None:
        hits = lint_sql_text("SELECT * FROM t WHERE a = 1", "t.sql", RULES, disabled={"COL.001"})
        assert not any(h.rule_id == "COL.001" for h in hits)
        assert any(h.rule_id == "COL.001" for h in lint_sql_text("SELECT * FROM t WHERE a = 1", "t.sql", RULES))


class TestReviewRegressions:
    """评审回归：sqlglot AST 形态假设逐条实测（列级约束/别名/SERIAL/FULLTEXT）。"""

    def test_key002_column_level_primary_key_no_hit(self) -> None:
        hits = lint_sql_text("CREATE TABLE t (id INT PRIMARY KEY, name VARCHAR(50))", "t.sql", RULES)
        assert not any(h.rule_id == "KEY.002" for h in hits)

    def test_key002_column_level_unique_no_hit(self) -> None:
        hits = lint_sql_text("CREATE TABLE t (id INT, email VARCHAR(200) UNIQUE)", "t.sql", RULES)
        assert not any(h.rule_id == "KEY.002" for h in hits)

    def test_key007_column_level_varchar_primary_key_hits(self) -> None:
        hits = lint_sql_text("CREATE TABLE t (id VARCHAR(36) NOT NULL PRIMARY KEY)", "t.sql", RULES)
        assert any(h.rule_id == "KEY.007" for h in hits)
        assert "id" in next(h.message for h in hits if h.rule_id == "KEY.007")

    def test_key007_serial_and_boolean_primary_keys_pass(self) -> None:
        for ddl in (
            "CREATE TABLE t (id SERIAL PRIMARY KEY)",
            "CREATE TABLE t (id BOOLEAN PRIMARY KEY)",
            "CREATE TABLE t (id BOOL PRIMARY KEY)",
        ):
            hits = lint_sql_text(ddl, "t.sql", RULES)
            assert not any(h.rule_id == "KEY.007" for h in hits), ddl

    def test_fun001_wrapped_on_either_side(self) -> None:
        for sql, wrapped_col in (
            ("SELECT * FROM t WHERE DATE(a) = b", "a"),
            ("SELECT * FROM t WHERE a + 1 = b", "a"),
            ("SELECT * FROM t WHERE a = b + 1", "b"),
        ):
            hits = [h for h in lint_sql_text(sql, "t.sql", RULES) if h.rule_id == "FUN.001"]
            assert hits, sql
            assert wrapped_col in hits[0].message, sql
            assert hits[0].message.count("被函数或运算包裹") == 1

    def test_fun001_bare_comparison_no_hit(self) -> None:
        hits = lint_sql_text("SELECT * FROM t WHERE a = b", "t.sql", RULES)
        assert not any(h.rule_id == "FUN.001" for h in hits)

    def test_sta003_unique_key_requires_uk_prefix(self) -> None:
        hits = lint_sql_text("CREATE TABLE t (id INT, a VARCHAR(9), UNIQUE KEY a (a))", "t.sql", RULES)
        assert any(h.rule_id == "STA.003" and "uk_" in h.message for h in hits)

    def test_sta003_proper_names_pass(self) -> None:
        hits = lint_sql_text(
            "CREATE TABLE t (id INT, a VARCHAR(9), UNIQUE KEY uk_a (a), KEY idx_id (id))", "t.sql", RULES
        )
        assert not any(h.rule_id == "STA.003" for h in hits)

    def test_sta003_fulltext_and_spatial_exempt(self) -> None:
        hits = lint_sql_text(
            "CREATE TABLE t (a TEXT, b GEOMETRY, FULLTEXT KEY ft_a (a), SPATIAL KEY sp_b (b))", "t.sql", RULES
        )
        assert not any(h.rule_id == "STA.003" for h in hits)

    def test_key005_counts_table_level_unique_keys(self) -> None:
        ddl = (
            "CREATE TABLE t (id INT, "
            + ", ".join(f"UNIQUE KEY uk_c{i} (c{i})".replace("c{i}", f"c{i}") for i in range(1, 12))
            + ")"
        )
        # c0 与主键：改用 id 之外的列
        ddl = "CREATE TABLE t (id INT, " + ", ".join(f"UNIQUE KEY uk_c{i} (c{i})" for i in range(11)) + ")"
        # 列不存在不影响 AST 计数（纯语法层判定）
        hits = [h for h in lint_sql_text(ddl, "t.sql", RULES) if h.rule_id == "KEY.005"]
        assert hits and "11" in hits[0].message

    def test_key005_counts_column_level_unique(self) -> None:
        cols = ", ".join(f"c{i} INT UNIQUE" for i in range(11))
        hits = [h for h in lint_sql_text(f"CREATE TABLE t (id INT, {cols})", "t.sql", RULES) if h.rule_id == "KEY.005"]
        assert hits


class TestLintPathsDedup:
    def test_duplicate_paths_audited_once(self, tmp_path) -> None:
        target = tmp_path / "a.sql"
        target.write_text("SELECT * FROM t WHERE a LIKE '%x'\n", encoding="utf-8")
        result = lint_paths([tmp_path, target], RULES)
        assert result.files.count(str(target)) == 1


class TestNamedConstraintForms:
    """评审回归：`CONSTRAINT <名> PRIMARY KEY/UNIQUE` 是 exp.Constraint 包裹
    （mysqldump 高频形态），KEY.002/005/007/STA.003 不得整体漏判。"""

    def test_key002_named_primary_key_no_hit(self) -> None:
        hits = lint_sql_text(
            "CREATE TABLE orders (id bigint unsigned NOT NULL, CONSTRAINT pk_orders PRIMARY KEY (id))",
            "t.sql",
            RULES,
        )
        assert not any(h.rule_id == "KEY.002" for h in hits)

    def test_key007_named_varchar_primary_key_hits(self) -> None:
        hits = lint_sql_text(
            "CREATE TABLE t (id VARCHAR(36) NOT NULL, CONSTRAINT pk_t PRIMARY KEY (id))", "t.sql", RULES
        )
        assert any(h.rule_id == "KEY.007" and "id" in h.message for h in hits)

    def test_key005_named_unique_counts(self) -> None:
        cols = ", ".join(f"c{i} INT" for i in range(11))
        constraints = ", ".join(f"CONSTRAINT uk_c{i} UNIQUE (c{i})" for i in range(11))
        hits = [
            h
            for h in lint_sql_text(f"CREATE TABLE t (id INT, {cols}, {constraints})", "t.sql", RULES)
            if h.rule_id == "KEY.005"
        ]
        assert hits and "11" in hits[0].message

    def test_sta003_named_unique_requires_uk_prefix(self) -> None:
        hits = lint_sql_text("CREATE TABLE t (id INT, a VARCHAR(9), CONSTRAINT a UNIQUE (a))", "t.sql", RULES)
        assert any(h.rule_id == "STA.003" and "uk_" in h.message for h in hits)

    def test_sta003_named_proper_names_pass(self) -> None:
        hits = lint_sql_text(
            "CREATE TABLE t (id INT, a VARCHAR(9), CONSTRAINT uk_a UNIQUE (a), CONSTRAINT idx_id KEY (id))",
            "t.sql",
            RULES,
        )
        assert not any(h.rule_id == "STA.003" for h in hits)

    def test_fun001_subquery_wrapped_column_not_flagged(self) -> None:
        """子查询内的函数包裹属于嵌套查询自己的谓词，不归外层比较。"""
        hits = lint_sql_text("SELECT * FROM t WHERE a = (SELECT MAX(b) FROM u)", "t.sql", RULES)
        assert not any(h.rule_id == "FUN.001" for h in hits)

    def test_fun001_same_level_still_flagged(self) -> None:
        hits = lint_sql_text("SELECT * FROM t WHERE a = DATE(b)", "t.sql", RULES)
        assert any(h.rule_id == "FUN.001" and "b" in h.message for h in hits)
