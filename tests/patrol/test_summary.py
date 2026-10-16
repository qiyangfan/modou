"""跨信号综合摘要（patrol summarize）测试：确定性 digest、输入校验、退出码取最严重档。"""

from __future__ import annotations

import pytest

from modou.patrol.summary import SummaryInputError, summarize_render, summarize_reports


def _drift(exit_code: int = 1) -> dict:
    return {
        "report_kind": "patrol_drift",
        "report_version": 1,
        "exit_code": exit_code,
        "summary": {"added": 2, "removed": 0, "changed": 1, "databases_with_findings": 1},
        "databases": {
            "shop": [
                {
                    "object_type": "table",
                    "object_name": "orders",
                    "category": "added",
                    "dimensions": ["table"],
                    "details": [],
                }
            ]
        },
    }


def _unused() -> dict:
    return {
        "report_kind": "patrol_unused_indexes",
        "report_version": 1,
        "exit_code": 0,
        "uptime_seconds": 86400,
        "observe_days": 7,
        "usages": [
            {
                "status": "confirmed_unused",
                "database": "shop",
                "table": "orders",
                "index_name": "idx_old",
                "columns": ["a"],
                "count_star": 0,
                "table_share_pct": 0.0,
                "daily_average": 0.0,
                "note": "",
                "drop_statement": "ALTER TABLE `shop`.`orders` DROP INDEX `idx_old`",
            },
            {
                "status": "low_use",
                "database": "shop",
                "table": "users",
                "index_name": "idx_b",
                "columns": ["b"],
                "count_star": 3,
                "table_share_pct": 1.0,
                "daily_average": 1.0,
                "note": "",
                "drop_statement": "",
            },
        ],
        "redundancies": [
            {
                "case": "leftmost_prefix",
                "database": "shop",
                "table": "orders",
                "redundant_index": "idx_a",
                "dominant_index": "idx_ab",
                "fk_protected": False,
                "drop_statement": "ALTER TABLE `shop`.`orders` DROP INDEX `idx_a`",
            }
        ],
    }


def _slowlog() -> dict:
    return {
        "report_kind": "patrol_slowlog",
        "report_version": 1,
        "exit_code": 0,
        "source_file": "slow.log",
        "entries_parsed": 10,
        "skipped_lines": 0,
        "top": [
            {
                "fingerprint": "SELECT * FROM orders WHERE user_id = ?",
                "sample": "SELECT * FROM orders WHERE user_id = 7",
                "count": 5,
                "query_time_total": 4.0,
                "query_time_max": 1.2,
                "rows_examined_total": 50000,
            }
        ],
    }


class TestSummarizeReports:
    def test_all_three_signals(self) -> None:
        report = summarize_reports(_drift(), _unused(), _slowlog())
        assert report["report_kind"] == "patrol_summary"
        assert report["exit_code"] == 1  # 取最严重档（drift 有发现）
        assert report["signals"]["drift"]["added"] == 2
        assert report["signals"]["unused"]["confirmed_unused"] == 1
        assert report["signals"]["unused"]["redundant"] == 1
        assert report["signals"]["slowlog"]["fingerprints"] == 1

    def test_at_least_one_signal_required(self) -> None:
        with pytest.raises(SummaryInputError):
            summarize_reports(None, None, None)

    def test_kind_mismatch_is_input_error(self) -> None:
        with pytest.raises(SummaryInputError):
            summarize_reports(_unused(), None, None)  # drift 槽位给了 unused 报告

    def test_digest_items_capped_and_metadata_only(self) -> None:
        report = summarize_reports(_drift(), _unused(), _slowlog())
        (item,) = report["signals"]["drift"]["objects"]
        assert item == {"database": "shop", "object_type": "table", "object_name": "orders", "category": "added"}
        (slow,) = report["signals"]["slowlog"]["top"]
        assert slow["count"] == 5 and "sample" not in slow  # 样本 SQL 不进摘要（多余载荷）

    def test_no_drift_exit_zero(self) -> None:
        report = summarize_reports(None, _unused(), None)
        assert report["exit_code"] == 0


class TestSummarizeRender:
    def test_renders_signals_and_exit(self) -> None:
        text = summarize_render(summarize_reports(_drift(), _unused(), _slowlog()))
        assert "墨斗综合巡检报告" in text
        assert "漂移" in text and "未用" in text and "慢日志" in text
        assert "退出码：1" in text
