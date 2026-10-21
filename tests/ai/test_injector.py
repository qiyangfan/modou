"""规则注入器测试：验证命中按模板原样生成上下文。"""

from __future__ import annotations

from modou.ai.injector import render_rule_context
from modou.lint.engine import Hit


def _hit(rule_id: str, file: str = "V01__x.sql", line: int = 3, message: str = "命中详情") -> Hit:
    return Hit(rule_id=rule_id, level="warning", file=file, line=line, message=message, suggestion="建议")


class TestRenderRuleContext:
    def test_renders_rule_id_location_and_message(self) -> None:
        context = render_rule_context([_hit("KEY.002"), _hit("STA.003", file="V02__y.sql", line=9, message="另一条")])
        assert "KEY.002" in context and "V01__x.sql:3" in context
        assert "STA.003" in context and "V02__y.sql:9" in context and "另一条" in context

    def test_empty_hits_render_empty(self) -> None:
        assert render_rule_context([]) == ""
