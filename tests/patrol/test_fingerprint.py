"""查询指纹归一测试（pt-query-digest 口径：字面量→占位符、IN/VALUES 折叠）。"""

from __future__ import annotations

from modou.patrol.fingerprint import fingerprint


class TestFingerprint:
    def test_literals_normalized(self) -> None:
        a = fingerprint("SELECT * FROM orders WHERE user_id = 42 AND note = 'hello'")
        b = fingerprint("select * from orders where user_id = 99 and note = 'world'")
        assert a == b
        assert "?" in a

    def test_in_list_collapsed_regardless_of_cardinality(self) -> None:
        one = fingerprint("SELECT * FROM t WHERE id IN (1)")
        many = fingerprint("SELECT * FROM t WHERE id IN (1, 2, 3, 4, 5)")
        assert one == many

    def test_values_lists_collapsed(self) -> None:
        single = fingerprint("INSERT INTO t (a, b) VALUES (1, 'x')")
        multi = fingerprint("INSERT INTO t (a, b) VALUES (1, 'x'), (2, 'y'), (3, 'z')")
        assert single == multi

    def test_comments_stripped(self) -> None:
        a = fingerprint("SELECT /* hint */ * FROM t WHERE id = 1")
        b = fingerprint("SELECT * FROM t WHERE id = 2")
        assert a == b

    def test_embedded_identifier_numbers_normalized(self) -> None:
        a = fingerprint("SELECT * FROM users_2009 WHERE id = 1")
        b = fingerprint("SELECT * FROM users_2010 WHERE id = 1")
        assert a == b

    def test_null_literal_normalized(self) -> None:
        a = fingerprint("SELECT * FROM t WHERE a = NULL")
        b = fingerprint("SELECT * FROM t WHERE a = 1")
        assert a == b

    def test_different_shapes_differ(self) -> None:
        assert fingerprint("SELECT * FROM a WHERE id = 1") != fingerprint("SELECT * FROM b WHERE id = 1")

    def test_whitespace_collapsed(self) -> None:
        assert fingerprint("SELECT  *\n  FROM   t") == fingerprint("SELECT * FROM t")


class TestSubqueryNotFolded:
    """评审回归：IN (SELECT ...) 子查询不是值列表，不得折叠（不同形态必须不同指纹）。"""

    def test_in_subquery_keeps_distinct_fingerprints(self) -> None:
        a = fingerprint("SELECT * FROM t WHERE id IN (SELECT id FROM x WHERE flag = 1)")
        b = fingerprint("SELECT * FROM t WHERE id IN (SELECT id FROM y WHERE flag = 2)")
        assert a != b
        assert "select" in a

    def test_in_value_list_still_folds(self) -> None:
        a = fingerprint("SELECT * FROM t WHERE id IN (1, 2, 3)")
        b = fingerprint("SELECT * FROM t WHERE id IN (4, 5)")
        assert a == b

    def test_in_negative_number_folds(self) -> None:
        assert fingerprint("SELECT * FROM t WHERE id IN (-1)") == fingerprint("SELECT * FROM t WHERE id IN (-2)")
