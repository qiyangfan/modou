"""AI 观点区契约测试（v0.5，spec ai-analyst「结论两级分级」）。

契约三律（测试即规格）：
- 单列：AI 观点只出现在 ai_opinions 键与专属文本区，不混入确定性结论字段；
- 来源标注：每条观点带 source=ai、模型名与「未实证」标注；
- 退出码免疫：观点的出入不改变报告 exit_code；未配置（无观点）时报告与
  v0.4 完全一致——无该键、文本无该区。
"""

from __future__ import annotations

from modou.report.opinions import (
    AI_OPINIONS_KEY,
    AiOpinion,
    attach_ai_opinions,
    degraded,
    opinions_to_json,
    render_opinions_section,
)


def _report(exit_code: int = 0) -> dict:
    return {
        "report_version": 1,
        "exit_code": exit_code,
        "summary": {"missing_execution": 1},
        "databases": {"shop": [{"object_name": "orders", "kind": "missing_execution"}]},
    }


def _opinion() -> AiOpinion:
    return AiOpinion(
        lane="verify", subject="shop.orders", opinion="索引缺失疑似漏执行，建议补执行 V03。", model="glm-4.7"
    )


class TestUnconfiguredZeroDiff:
    def test_empty_opinions_leave_report_identical(self) -> None:
        """未配置 BYOK = 车道不产出观点 = attach 是恒等函数（无键、内容逐字段相等）。"""
        report = _report()
        merged = attach_ai_opinions(report, [])
        assert merged == report
        assert AI_OPINIONS_KEY not in merged

    def test_empty_opinions_render_no_section(self) -> None:
        assert render_opinions_section([]) == ""


class TestExitCodeImmunity:
    def test_exit_code_untouched_by_opinions(self) -> None:
        for exit_code in (0, 1, 2):
            report = _report(exit_code=exit_code)
            merged = attach_ai_opinions(report, [_opinion(), degraded("lint", "a.sql:3", "m", "timeout")])
            assert merged["exit_code"] == exit_code

    def test_attach_does_not_mutate_input(self) -> None:
        report = _report(exit_code=1)
        attach_ai_opinions(report, [_opinion()])
        assert AI_OPINIONS_KEY not in report


class TestOpinionContract:
    def test_json_item_fields(self) -> None:
        (item,) = opinions_to_json([_opinion()])
        assert item["lane"] == "verify"
        assert item["subject"] == "shop.orders"
        assert item["source"] == "ai"
        assert item["model"] == "glm-4.7"
        assert item["status"] == "ok"
        assert item["degraded_reason"] is None

    def test_degraded_item_carries_reason(self) -> None:
        (item,) = opinions_to_json([degraded("lint", "a.sql:3", "glm-4.7", "upstream timeout after 30s")])
        assert item["status"] == "degraded"
        assert item["degraded_reason"] == "upstream timeout after 30s"
        assert item["source"] == "ai"

    def test_section_is_dedicated_block_with_annotations(self) -> None:
        section = render_opinions_section([_opinion()])
        assert "AI 观点" in section
        assert "未实证" in section
        assert "不影响退出码" in section
        assert "verify" in section and "shop.orders" in section and "glm-4.7" in section

    def test_degraded_entry_rendered_with_reason(self) -> None:
        section = render_opinions_section([degraded("lint", "a.sql:3", "glm-4.7", "timeout")])
        assert "降级" in section and "timeout" in section


class TestAdditiveOnly:
    def test_verify_report_gains_only_the_new_key(self) -> None:
        """只增不改：原契约字段逐项保留，新增仅 ai_opinions 一键。"""
        report = _report(exit_code=1)
        merged = attach_ai_opinions(report, [_opinion()])
        assert set(merged) == set(report) | {AI_OPINIONS_KEY}
        for key, value in report.items():
            assert merged[key] == value
