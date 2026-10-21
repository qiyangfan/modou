"""lint 残留评审测试：输出校验、无效条目丢弃、调用失败降级、未配置不联网。"""

from __future__ import annotations

import json

from modou.ai.bundler import StatementUnit
from modou.ai.client import AiConfig
from modou.ai.lane_lint import review_residual
from modou.lint import RULES
from modou.lint.engine import Hit


def _config() -> AiConfig:
    return AiConfig(base_url="https://api.example.com/v1", api_key="k", model="glm-4.7")


def _units(*subjects: str) -> list[StatementUnit]:
    return [
        StatementUnit(file=s.split(":")[0], line=int(s.split(":")[1]), sql=f"SELECT {i} FROM t")
        for i, s in enumerate(subjects)
    ]


def _transport_reply(content: str):
    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        return {"choices": [{"message": {"content": content}}]}

    return transport


def _transport_raise(error: Exception):
    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        raise error

    return transport


class TestReviewResidual:
    def test_valid_entries_become_opinions(self) -> None:
        reply = json.dumps(
            [
                {"subject": "a.sql:1", "opinion": "该语句与后续 DROP 存在顺序依赖风险。"},
                {"subject": "a.sql:2", "opinion": "意图疑似与文件名不符。"},
            ],
            ensure_ascii=False,
        )
        opinions = review_residual(_units("a.sql:1", "a.sql:2"), [], _config(), transport=_transport_reply(reply))
        assert [(o.lane, o.subject) for o in opinions] == [("lint", "a.sql:1"), ("lint", "a.sql:2")]
        assert all(o.model == "glm-4.7" and o.status == "ok" for o in opinions)

    def test_invalid_entries_dropped_whole_call_not_failed(self) -> None:
        """指向批次外的 subject 与空观点逐条丢弃，合法条目保留。"""
        reply = json.dumps(
            [
                {"subject": "ghost.sql:99", "opinion": "幻觉定位"},
                {"subject": "a.sql:1", "opinion": "   "},
                {"subject": "a.sql:1", "opinion": "合法观点"},
                "not-an-object",
            ],
            ensure_ascii=False,
        )
        opinions = review_residual(_units("a.sql:1"), [], _config(), transport=_transport_reply(reply))
        assert [(o.subject, o.opinion) for o in opinions] == [("a.sql:1", "合法观点")]

    def test_unparseable_reply_degrades_not_silent(self) -> None:
        """回复不可解析时降级，并说明原因。"""
        opinions = review_residual(_units("a.sql:1"), [], _config(), transport=_transport_reply("抱歉我无法输出 JSON"))
        assert len(opinions) == 1
        assert opinions[0].status == "degraded"
        assert "unparseable" in (opinions[0].degraded_reason or "")

    def test_call_failure_degrades_not_raises(self) -> None:
        opinions = review_residual(
            _units("a.sql:1", "a.sql:2"), [], _config(), transport=_transport_raise(TimeoutError("boom"))
        )
        assert len(opinions) == 1
        assert opinions[0].status == "degraded"
        assert "boom" in (opinions[0].degraded_reason or "")
        assert opinions[0].model == "glm-4.7"

    def test_no_units_makes_no_call(self) -> None:
        calls: list[dict] = []

        def spy_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            calls.append(payload)
            return {"choices": [{"message": {"content": "[]"}}]}

        opinions = review_residual([], [], _config(), transport=spy_transport)
        assert opinions == []
        assert calls == []

    def test_payload_carries_only_sql_text_and_rule_context(self) -> None:
        """请求载荷只含 SQL 文本与规则命中，不含数据行。"""
        captured: dict = {}

        def spy_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            captured.update(payload)
            return {"choices": [{"message": {"content": "[]"}}]}

        hits = [Hit(rule_id="COL.001", level="warning", file="a.sql", line=1, message="SELECT *", suggestion="显式列")]
        review_residual(_units("a.sql:2"), hits, _config(), transport=spy_transport)
        user_content = json.loads(captured["messages"][1]["content"])
        assert user_content["statements"][0]["sql"] == "SELECT 0 FROM t"
        assert "COL.001" in user_content["static_rule_hits"]

    def test_batches_split_by_budget_each_gets_call(self) -> None:
        calls: list[dict] = []

        def spy_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            calls.append(payload)
            return {"choices": [{"message": {"content": "[]"}}]}

        units = _units("a.sql:1", "a.sql:2", "a.sql:3")
        review_residual(units, [], _config(), transport=spy_transport, max_statements=2)
        assert len(calls) == 2


class TestReviewFromEngineResiduals:
    def test_reviews_units_built_from_engine_residuals(self, tmp_path) -> None:
        """残留语句取自 LintResult.residuals，即规则未命中的语句。"""
        from modou.lint.engine import lint_paths

        hit_file = tmp_path / "hit.sql"
        hit_file.write_text("SELECT * FROM orders;\nSELECT id FROM orders WHERE id = 1;\n", encoding="utf-8")
        captured: dict = {}

        def spy_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            captured.update(payload)
            return {"choices": [{"message": {"content": "[]"}}]}

        result = lint_paths([hit_file], RULES)
        units = [StatementUnit(file=r.file, line=r.line, sql=r.sql) for r in result.residuals]
        opinions = review_residual(units, result.hits, _config(), transport=spy_transport)
        assert opinions == []
        statements = json.loads(captured["messages"][1]["content"])["statements"]
        assert [s["subject"] for s in statements] == [f"{hit_file}:2"]

    def test_directory_input_resolved_by_engine_not_by_lane(self, tmp_path) -> None:
        """目录由 lint_paths 展开，lane 只接收文件级残留单元。"""
        from modou.lint.engine import lint_paths

        sub = tmp_path / "cs"
        sub.mkdir()
        (sub / "V01__a.sql").write_text("SELECT id FROM t WHERE id = 1;\n", encoding="utf-8")
        result = lint_paths([sub], RULES)
        assert [r.file for r in result.residuals] == [str(sub / "V01__a.sql")]
