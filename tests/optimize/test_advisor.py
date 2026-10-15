"""AI 顾问层测试：BYOK 配置、载荷边界（绝无数据行）、候选解析与失败降级。

网络层注入（_post_json 可替换）：本模块测试零真实网络。
"""

from __future__ import annotations

import json

import pytest

from modou.optimize.advisor import (
    AdvisorConfig,
    build_request_payload,
    build_schema_summary,
    config_from_env,
    fetch_candidates,
    maybe_fetch_candidates,
)
from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    Snapshot,
    SnapshotMeta,
    TableDef,
    TableSample,
)


def _snapshot() -> Snapshot:
    table = TableDef(
        name="orders",
        engine="InnoDB",
        collation="",
        comment="",
        create_options="",
        ddl="CREATE TABLE orders (id int PRIMARY KEY, user_id int, amount decimal(10,2))",
        columns=[
            ColumnDef("id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("user_id", 2, "int", True, None, "", None, "", ""),
            ColumnDef("amount", 3, "decimal(10,2)", True, None, "", None, "", ""),
        ],
        sample=TableSample(columns=["id", "user_id"], rows=[[1, "SECRET_ROW_VALUE"], [2, "x"]], sampled_rows=2),
    )
    return Snapshot(
        format_version=2,
        tool_version="0.2.0",
        captured_at="2026-10-15T00:00:00+00:00",
        meta=SnapshotMeta("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
        databases={"shop": DatabaseInventory(name="shop", charset="utf8mb4", collation="", tables={"orders": table})},
    )


class TestConfigFromEnv:
    def test_all_three_present(self) -> None:
        config = config_from_env(
            {"MOUDO_AI_BASE_URL": "https://api.example.com/v1", "MOUDO_AI_API_KEY": "k", "MOUDO_AI_MODEL": "m"}
        )
        assert config == AdvisorConfig(base_url="https://api.example.com/v1", api_key="k", model="m")

    @pytest.mark.parametrize(
        "env", [{}, {"MOUDO_AI_BASE_URL": "x"}, {"MOUDO_AI_BASE_URL": "x", "MOUDO_AI_API_KEY": "k"}]
    )
    def test_partial_config_is_unconfigured(self, env: dict) -> None:
        assert config_from_env(env) is None

    def test_blank_values_treated_as_missing(self) -> None:
        assert config_from_env({"MOUDO_AI_BASE_URL": "", "MOUDO_AI_API_KEY": "k", "MOUDO_AI_MODEL": "m"}) is None


class TestPayloadBoundary:
    def test_schema_summary_has_no_data_rows(self) -> None:
        summary = build_schema_summary(_snapshot(), {"shop"})
        assert summary[0]["table"] == "orders"
        assert any("user_id" in col for col in summary[0]["columns"])
        payload_text = json.dumps(
            build_request_payload(
                AdvisorConfig("https://x/v1", "k", "m"), "SELECT * FROM orders WHERE user_id = 1", summary
            )
        )
        # 载荷红线：仅 SQL 文本与 schema 摘要，绝无数据行
        assert "SECRET_ROW_VALUE" not in payload_text

    def test_summary_limited_to_requested_databases(self) -> None:
        summary = build_schema_summary(_snapshot(), {"other"})
        assert summary == []


class TestFetchCandidates:
    def test_happy_path_parses_index_and_rewrite(self) -> None:
        content = json.dumps(
            [
                {"type": "index", "table": "orders", "columns": ["user_id", "amount"]},
                {"type": "rewrite", "sql": "SELECT id FROM orders WHERE user_id = 1"},
            ]
        )
        calls: list[dict] = []

        def fake_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            calls.append(payload)
            return {"choices": [{"message": {"content": content}}]}

        candidates = fetch_candidates(
            AdvisorConfig("https://x/v1", "k", "m"),
            "SELECT * FROM orders WHERE user_id = 1",
            build_schema_summary(_snapshot(), {"shop"}),
            transport=fake_transport,
        )
        assert len(candidates) == 2
        assert candidates[0].source == "ai"
        assert candidates[0].kind == "index"
        assert candidates[0].columns == ["user_id", "amount"]
        assert candidates[1].kind == "rewrite"
        assert len(calls) == 1

    def test_malformed_content_degrades_to_empty(self) -> None:
        def fake_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            return {"choices": [{"message": {"content": "抱歉，我无法以 JSON 回答"}}]}

        candidates = fetch_candidates(
            AdvisorConfig("https://x/v1", "k", "m"), "SELECT 1 FROM t", [], transport=fake_transport
        )
        assert candidates == []

    def test_transport_error_degrades_to_empty(self) -> None:
        def boom(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            raise OSError("network down")

        assert fetch_candidates(AdvisorConfig("https://x/v1", "k", "m"), "SELECT 1 FROM t", [], transport=boom) == []

    def test_unconfigured_never_calls_transport(self) -> None:
        calls: list[int] = []

        def fake_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            calls.append(1)
            return {}

        result = maybe_fetch_candidates(None, "SELECT 1 FROM t", [], transport=fake_transport)
        assert result == []
        assert calls == []
