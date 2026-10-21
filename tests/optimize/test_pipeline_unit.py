"""实证管线纯逻辑测试：输入校验、代价判定、候选校验与报告两级状态。"""

from __future__ import annotations

import pytest

from modou.optimize.candidates import IndexCandidate
from modou.optimize.pipeline import (
    OptimizeInputError,
    judge_improvement,
    validate_inputs,
)
from tests.optimize.conftest import make_orders_table, make_snapshot


class TestValidateInputs:
    def test_empty_statements_rejected(self) -> None:
        with pytest.raises(OptimizeInputError, match="no statements"):
            validate_inputs([], make_snapshot(with_sample=True))

    def test_unsampled_snapshot_rejected(self) -> None:
        with pytest.raises(OptimizeInputError, match="sample"):
            validate_inputs(["SELECT * FROM orders WHERE user_id = 1"], make_snapshot(with_sample=False))

    def test_v1_snapshot_rejected(self) -> None:
        # v1 快照无采样数据，按输入错误拒绝并提示重采
        with pytest.raises(OptimizeInputError, match="sample"):
            validate_inputs(["SELECT * FROM orders WHERE user_id = 1"], make_snapshot(format_version=1))

    def test_ddl_statement_rejected(self) -> None:
        with pytest.raises(OptimizeInputError, match="statement #1"):
            validate_inputs(["CREATE TABLE t (id int)"], make_snapshot(with_sample=True))

    def test_unparseable_statement_rejected(self) -> None:
        with pytest.raises(OptimizeInputError, match="statement #1"):
            validate_inputs(["SELEC * FORM orders"], make_snapshot(with_sample=True))

    def test_statement_referencing_unknown_database_rejected(self) -> None:
        with pytest.raises(OptimizeInputError, match="is not in the snapshot"):
            validate_inputs(["SELECT * FROM other.orders WHERE user_id = 1"], make_snapshot(with_sample=True))

    def test_unqualified_statement_requires_default_database(self) -> None:
        with pytest.raises(OptimizeInputError, match="--default-database"):
            validate_inputs(["SELECT * FROM orders WHERE user_id = 1"], make_snapshot(with_sample=True))


class TestJudgeImprovement:
    def test_cost_down_is_measured(self) -> None:
        status, reason, improvement = judge_improvement(100.0, 40.0)
        assert status == "measured"
        assert reason is None
        assert improvement == pytest.approx(60.0)

    def test_cost_equal_or_up_is_unverified(self) -> None:
        status, reason, _ = judge_improvement(100.0, 100.0)
        assert status == "unverified"
        assert "代价未降低" in (reason or "")

        status2, reason2, _ = judge_improvement(100.0, 150.0)
        assert status2 == "unverified"
        assert "代价未降低" in (reason2 or "")

    def test_missing_cost_degrades_to_unverified(self) -> None:
        status, reason, improvement = judge_improvement(None, 10.0)
        assert status == "unverified"
        assert improvement is None
        assert reason is not None


class TestCandidateResolution:
    def test_ai_hallucinated_column_dropped(self) -> None:
        from modou.optimize.pipeline import resolve_candidates

        analysis_table_map = {"shop": {"orders": make_orders_table()}}
        candidates = [
            IndexCandidate("shop", "orders", ["user_id", "amount"], "AI", source="ai"),
            IndexCandidate("shop", "orders", ["user_id", "nonexistent_col"], "AI", source="ai"),
        ]
        suggestions, dropped = resolve_candidates(candidates, analysis_table_map)
        assert len(suggestions) == 1
        assert len(dropped) == 1
        assert "nonexistent_col" in dropped[0]

    def test_candidate_on_unknown_table_dropped(self) -> None:
        from modou.optimize.pipeline import resolve_candidates

        analysis_table_map = {"shop": {"orders": make_orders_table()}}
        candidates = [IndexCandidate("shop", "ghost_table", ["a"], "AI", source="ai")]
        suggestions, dropped = resolve_candidates(candidates, analysis_table_map)
        assert suggestions == []
        assert len(dropped) == 1

    def test_rule_candidate_kept_for_evidence(self) -> None:
        from modou.optimize.pipeline import resolve_candidates

        analysis_table_map = {"shop": {"orders": make_orders_table()}}
        candidates = [IndexCandidate("shop", "orders", ["user_id"], "等值谓词列 user_id", source="rule")]
        suggestions, dropped = resolve_candidates(candidates, analysis_table_map)
        assert len(suggestions) == 1
        assert suggestions[0]["source"] == "rule"
        assert dropped == []

    def test_rewrite_candidate_passes_through(self) -> None:
        from modou.optimize.pipeline import resolve_candidates

        analysis_table_map = {"shop": {"orders": make_orders_table()}}
        candidates = [IndexCandidate(None, "", [], "AI 改写", source="ai", kind="rewrite", sql="SELECT id FROM orders")]
        suggestions, _ = resolve_candidates(candidates, analysis_table_map)
        assert len(suggestions) == 1
        assert suggestions[0]["kind"] == "rewrite"
        assert suggestions[0]["content"] == "SELECT id FROM orders"


class TestTwoStateInvariant:
    def test_report_suggestions_always_two_state(self) -> None:
        """报告两级状态：measured / unverified 二选一，无第三种状态。"""
        from modou.optimize.report import render_text, report_to_json

        statement_report = {
            "index": 1,
            "database": "shop",
            "sql": "SELECT * FROM orders WHERE user_id = 1",
            "baseline": {"cost": 100.0, "tables": [], "actual_time_ms": None},
            "findings": [],
            "suggestions": [
                {
                    "source": "rule",
                    "kind": "index",
                    "content": "ALTER TABLE `shop`.`orders` ADD INDEX `idx_user_id` (`user_id`)",
                    "status": "measured",
                    "cost_before": 100.0,
                    "cost_after": 30.0,
                    "improvement_pct": 70.0,
                    "rows_before": [],
                    "rows_after": [],
                    "actual_time_before_ms": None,
                    "actual_time_after_ms": None,
                    "reason": None,
                    "side_effects": [],
                },
                {
                    "source": "ai",
                    "kind": "index",
                    "content": "ALTER TABLE `shop`.`orders` ADD INDEX `idx_status` (`status`)",
                    "status": "unverified",
                    "cost_before": 100.0,
                    "cost_after": 100.0,
                    "improvement_pct": None,
                    "rows_before": [],
                    "rows_after": [],
                    "actual_time_before_ms": None,
                    "actual_time_after_ms": None,
                    "reason": "代价未降低",
                    "side_effects": [],
                },
            ],
        }
        report = {
            "report_version": 1,
            "report_kind": "optimize",
            "generated_at": "2026-10-15T00:00:00+00:00",
            "exit_code": 0,
            "env_errors": [],
            "input_errors": [],
            "advisor": {"configured": False, "model": None, "dropped": []},
            "evidence_env": {"note": "n", "tables": []},
            "databases": {"shop": {"statements": [statement_report]}},
        }
        as_json = report_to_json(report)
        assert as_json["report_kind"] == "optimize"
        grouped = as_json["databases"]["shop"]["statements"]
        for suggestion in grouped[0]["suggestions"]:
            assert suggestion["status"] in ("measured", "unverified")
        text = render_text(report)
        assert "实测提升" in text
        assert "未验证" in text

    def test_status_labels_in_text(self) -> None:
        from modou.optimize.report import STATUS_LABELS

        assert STATUS_LABELS["measured"] == "实测提升"
        assert STATUS_LABELS["unverified"] == "未验证"


class TestReferencedTableValidation:
    def test_statement_referencing_missing_table_rejected(self) -> None:
        # 快照缺表时提前失败（退出码 2），不要等到影子阶段才失败
        with pytest.raises(OptimizeInputError, match="ghost"):
            validate_inputs(
                ["SELECT * FROM orders o JOIN ghost g ON o.user_id = g.id"],
                make_snapshot(with_sample=True),
                default_database="shop",
            )

    def test_alias_statement_passes_validation(self) -> None:
        analyses = validate_inputs(
            ["SELECT * FROM orders o WHERE o.user_id = 1"], make_snapshot(with_sample=True), default_database="shop"
        )
        assert len(analyses) == 1
        assert analyses[0].candidates[0].database == "shop"


class TestAdvisorDroppedAttribution:
    def test_dropped_message_names_the_source(self) -> None:
        from modou.optimize.pipeline import resolve_candidates

        tables_map = {"shop": {"orders": make_orders_table()}}
        _, dropped = resolve_candidates([IndexCandidate("shop", "ghost", ["a"], "r", source="ai")], tables_map)
        assert dropped and dropped[0].startswith("ai ")
        _, dropped2 = resolve_candidates([IndexCandidate("shop", "ghost", ["a"], "r", source="rule")], tables_map)
        assert dropped2 and dropped2[0].startswith("rule ")


class TestAdvisorExplainFactsWiring:
    def test_measure_statement_passes_baseline_plan_facts(self, monkeypatch) -> None:
        """管线把基线 EXPLAIN 事实传给候选生成。"""

        import modou.optimize.pipeline as pipeline_module
        from modou.optimize.candidates import analyze_statement
        from modou.optimize.explain import ExplainPlan

        captured: dict = {}

        def fake_fetch(config, sql, schema_summary, *, explain_facts=None, **kwargs):
            captured["explain_facts"] = explain_facts
            return []

        monkeypatch.setattr(pipeline_module, "maybe_fetch_candidates", fake_fetch)
        monkeypatch.setattr(
            pipeline_module,
            "explain_json",
            lambda conn, sql: ExplainPlan(
                query_cost=42.0, table_accesses=[{"table": "orders", "access_type": "ALL", "rows": 2000}]
            ),
        )
        monkeypatch.setattr(pipeline_module, "_reference_actual_ms", lambda conn, analysis: None)

        analysis = analyze_statement("SELECT * FROM orders WHERE user_id = 7", "shop")
        report = pipeline_module._measure_statement(
            conn=None,
            position=1,
            analysis=analysis,
            tables_map={"shop": {}},
            schema_summary=[],
            advisor_config=object(),
            index_count_limit=10,
            advisor_dropped=[],
        )
        assert report["baseline"]["cost"] == 42.0
        assert captured["explain_facts"]["query_cost"] == 42.0
        assert captured["explain_facts"]["table_accesses"][0]["table"] == "orders"
