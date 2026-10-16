"""patrol 跨信号综合叙事（内置通道）测试。"""

from __future__ import annotations

import json

from modou.ai.client import AiConfig
from modou.ai.lane_patrol import LANE, SUBJECT, narrativize


def _config() -> AiConfig:
    return AiConfig(base_url="https://api.example.com/v1", api_key="k", model="glm-4.7")


def _summary() -> dict:
    return {
        "report_kind": "patrol_summary",
        "report_version": 1,
        "exit_code": 1,
        "inputs": {"drift": "d.json", "unused": None, "slowlog": None},
        "signals": {"drift": {"added": 2, "removed": 0, "changed": 1, "objects": []}},
    }


def _transport_reply(content: str):
    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        return {"choices": [{"message": {"content": content}}]}

    return transport


class TestNarrativize:
    def test_valid_narrative_becomes_opinion(self) -> None:
        reply = json.dumps([{"subject": SUBJECT, "opinion": "新增索引与慢日志扫描信号相互印证。"}], ensure_ascii=False)
        (opinion,) = narrativize(_summary(), config=_config(), transport=_transport_reply(reply))
        assert (opinion.lane, opinion.subject) == (LANE, SUBJECT)
        assert opinion.model == "glm-4.7"

    def test_no_signals_makes_no_call(self) -> None:
        empty = {"signals": {}}

        def must_not_call(url, api_key, payload, timeout):
            raise AssertionError("must not call")

        assert narrativize(empty, config=_config(), transport=must_not_call) == []

    def test_foreign_subjects_dropped(self) -> None:
        reply = json.dumps(
            [{"subject": "other", "opinion": "x"}, {"subject": SUBJECT, "opinion": "有效叙事"}], ensure_ascii=False
        )
        opinions = narrativize(_summary(), config=_config(), transport=_transport_reply(reply))
        assert [o.opinion for o in opinions] == ["有效叙事"]

    def test_failure_degrades(self) -> None:
        def raise_transport(url, api_key, payload, timeout):
            raise TimeoutError("boom")

        (opinion,) = narrativize(_summary(), config=_config(), transport=raise_transport)
        assert opinion.status == "degraded" and "boom" in (opinion.degraded_reason or "")
