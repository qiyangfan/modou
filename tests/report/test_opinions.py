"""AI 观点区测试：观点与确定性结论分离，不影响退出码。"""

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
        """无观点时 attach 不改动报告。"""
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
        """原报告字段保持不变，只新增 ai_opinions。"""
        report = _report(exit_code=1)
        merged = attach_ai_opinions(report, [_opinion()])
        assert set(merged) == set(report) | {AI_OPINIONS_KEY}
        for key, value in report.items():
            assert merged[key] == value
