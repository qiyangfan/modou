"""verify 失败归因测试：事实打包、输出校验、调用失败降级、零差异不调用。"""

from __future__ import annotations

import json

from modou.ai.client import AiConfig
from modou.ai.lane_verify import LANE, attribute_findings
from modou.snapshot.model import (
    ColumnDef,
    DatabaseInventory,
    Snapshot,
    SnapshotMeta,
    TableDef,
    TableSample,
)


def _config() -> AiConfig:
    return AiConfig(base_url="https://api.example.com/v1", api_key="k", model="glm-4.7")


def _transport_reply(content: str):
    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        return {"choices": [{"message": {"content": content}}]}

    return transport


def _transport_raise(error: Exception):
    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        raise error

    return transport


def _findings_report() -> dict:
    return {
        "report_version": 1,
        "exit_code": 1,
        "replay_error": None,
        "databases": {
            "shop": [
                {
                    "object_type": "table",
                    "object_name": "orders",
                    "kind": "missing_execution",
                    "dimensions": ["index"],
                    "details": [
                        {
                            "dimension": "index",
                            "path": "idx_user_amount",
                            "expected": "CREATE INDEX ...",
                            "actual": None,
                        }
                    ],
                }
            ]
        },
    }


def _changeset(tmp_path):
    changeset = tmp_path / "cs"
    changeset.mkdir()
    (changeset / "V01__add_index.sql").write_text(
        "ALTER TABLE `orders` ADD INDEX `idx_user_amount` (`user_id`, `amount`);\n", encoding="utf-8"
    )
    (changeset / "manifest.txt").write_text("V01__add_index.sql\n", encoding="utf-8")
    return changeset


def _baseline(with_sample_secret: bool = False) -> Snapshot:
    sample = TableSample(columns=["id"], rows=[["SECRET_ROW_VALUE"]] if with_sample_secret else [[1]], sampled_rows=2)
    table = TableDef(
        name="orders",
        engine="InnoDB",
        collation="",
        comment="",
        create_options="",
        ddl="CREATE TABLE orders (id int PRIMARY KEY, user_id int)",
        columns=[
            ColumnDef("id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("user_id", 2, "int", True, None, "", None, "", ""),
        ],
        indexes=[],
        sample=sample,
    )
    return Snapshot(
        format_version=2,
        tool_version="t",
        captured_at="c",
        meta=SnapshotMeta("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
        databases={"shop": DatabaseInventory(name="shop", charset="utf8mb4", collation="", tables={"orders": table})},
    )


class TestAttributeFindings:
    def test_no_findings_makes_no_call(self) -> None:
        from pathlib import Path

        report = {"report_version": 1, "exit_code": 0, "replay_error": None, "databases": {}}
        opinions = attribute_findings(
            report,
            Path("/nonexistent-changeset"),
            _baseline(),
            config=_config(),
            transport=_transport_raise(AssertionError("must not call")),
        )
        assert opinions == []

    def test_findings_attributed_with_subject_validation(self, tmp_path) -> None:
        reply = json.dumps(
            [
                {"subject": "shop.table:orders", "opinion": "索引 idx_user_amount 疑似漏执行，可重放该语句补齐。"},
                {"subject": "ghost:table:x", "opinion": "幻觉对象应被丢弃"},
                {"subject": "shop.table:orders", "opinion": ""},
            ],
            ensure_ascii=False,
        )
        opinions = attribute_findings(
            _findings_report(), _changeset(tmp_path), _baseline(), config=_config(), transport=_transport_reply(reply)
        )
        assert len(opinions) == 1
        assert (opinions[0].lane, opinions[0].subject) == (LANE, "shop.table:orders")

    def test_call_failure_degrades_as_report_level(self, tmp_path) -> None:
        opinions = attribute_findings(
            _findings_report(),
            _changeset(tmp_path),
            _baseline(),
            config=_config(),
            transport=_transport_raise(TimeoutError("t")),
        )
        assert len(opinions) == 1 and opinions[0].status == "degraded"
        assert opinions[0].subject == "report"

    def test_fact_packaging_failure_degrades_not_crashes(self, tmp_path, monkeypatch) -> None:
        """事实打包（含 schema 切片）失败时降级为 report 级观点，不使命令崩溃。"""

        def explode(*args, **kwargs):
            raise RuntimeError("schema slice blew up")

        monkeypatch.setattr("modou.ai.lane_verify.slice_schema", explode)
        opinions = attribute_findings(
            _findings_report(),
            _changeset(tmp_path),
            _baseline(),
            config=_config(),
            transport=_transport_reply("[]"),
        )
        assert len(opinions) == 1 and opinions[0].status == "degraded"
        assert opinions[0].subject == "report"

    def test_payload_contains_statements_and_metadata_only(self, tmp_path) -> None:
        """请求载荷只含变更集 SQL、结论事实与 schema 元数据，不含采样数据行。"""
        captured: dict = {}

        def spy_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
            captured.update(payload)
            return {"choices": [{"message": {"content": "[]"}}]}

        attribute_findings(
            _findings_report(),
            _changeset(tmp_path),
            _baseline(with_sample_secret=True),
            config=_config(),
            transport=spy_transport,
        )
        text = json.dumps(captured, ensure_ascii=False)
        assert "idx_user_amount" in text  # 结论事实在场
        assert "ADD INDEX" in text  # 变更集语句在场
        assert "SECRET_ROW_VALUE" not in text  # 数据行绝不在场
