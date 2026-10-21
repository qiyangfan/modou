"""残留语句提取测试：解析成功且规则零命中的语句 = AI 评审的输入面（规则盲区）。"""

from __future__ import annotations

from modou.lint import RULES
from modou.lint.engine import residual_statements


class TestResidualStatements:
    def test_clean_statement_is_residual_with_location(self) -> None:
        text = "SELECT id FROM orders WHERE id = 1;\n"
        residual = residual_statements(text, RULES)
        # 切分器去掉结尾分隔符，残留面给的是可送审的语句
        assert [(line, sql.strip()) for line, sql in residual] == [(1, "SELECT id FROM orders WHERE id = 1")]

    def test_rule_hit_statement_is_not_residual(self) -> None:
        text = "SELECT * FROM orders;\nSELECT id FROM orders WHERE id = 1;\n"
        residual = residual_statements(text, RULES)
        assert len(residual) == 1  # 只有第二条（COL.001 命中的首条不在残留面）
        assert "id = 1" in residual[0][1]

    def test_unparseable_statement_is_never_residual(self) -> None:
        text = "SELECT 'unclosed\n"
        assert residual_statements(text, RULES) == []

    def test_disabled_rule_makes_statement_residual(self) -> None:
        # 该语句只触发 COL.001；带 WHERE，不会触发无 WHERE 规则
        text = "SELECT * FROM orders WHERE id = 1;\n"
        assert residual_statements(text, RULES) == []
        assert residual_statements(text, RULES, disabled={"COL.001"}) != []

    def test_empty_text(self) -> None:
        assert residual_statements("", RULES) == []
