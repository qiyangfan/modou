"""慢日志解析器测试：三段结构、log_slow_extra 自适应、USE 终止、聚合。"""

from __future__ import annotations

from modou.patrol.slowlog import aggregate, analyze_slowlog, parse_slowlog

SAMPLE = """/usr/sbin/mysqld, Version: 8.4.6 (MySQL). started with:
Tcp port: 3306, Unix socket: /tmp/mysql.sock
Time                 Id Command    Argument
# Time: 2026-10-15T02:00:00.123456Z
# User@Host: app[app] @ [10.0.0.1]  Id: 101
# Query_time: 1.5 Lock_time: 0.0002 Rows_sent: 10 Rows_examined: 100000
SET timestamp=1792730400;
SELECT * FROM orders WHERE user_id = 42 AND status = 1;
# Time: 2026-10-15T02:00:05.000000Z
# User@Host: app[app] @ [10.0.0.1]  Id: 102
# Query_time: 2.5 Lock_time: 0.0001 Rows_sent: 10 Rows_examined: 200000
SET timestamp=1792730405;
SELECT * FROM orders WHERE user_id = 77 AND status = 0;
# Time: 2026-10-15T02:00:10.000000Z
# User@Host: app[app] @ [10.0.0.2]  Id: 103
# Query_time: 0.5 Lock_time: 0.0 Rows_sent: 1 Rows_examined: 1
SET timestamp=1792730410;
SELECT COUNT(*) FROM users WHERE id = 5;
"""


class TestParser:
    def test_basic_parsing(self) -> None:
        entries, _ = parse_slowlog(SAMPLE)
        assert len(entries) == 3
        assert entries[0].query_time == 1.5
        assert entries[0].rows_examined == 100000
        assert "user_id = 42" in entries[0].statement
        assert entries[0].time_hint == "2026-10-15T02:00:00.123456Z"

    def test_use_line_terminates_entry(self) -> None:
        text = (
            "# Query_time: 1 Rows_sent: 1 Rows_examined: 1\n"
            "SET timestamp=1;\n"
            "UPDATE t SET a = 1 WHERE id = 2;\n"
            "USE other;\n"
            "# Query_time: 1 Rows_sent: 1 Rows_examined: 1\n"
            "SET timestamp=2;\n"
            "SELECT 1 FROM x;\n"
        )
        entries, _ = parse_slowlog(text)
        assert len(entries) == 2
        assert entries[0].statement.startswith("UPDATE t")
        assert not entries[0].statement.startswith("USE")

    def test_log_slow_extra_fields_adapted(self) -> None:
        """log_slow_extra（8.0.14+）追加字段行：按字段数自适应，不丢条目。"""
        text = (
            "# Time: 2026-10-15T02:00:00Z\n"
            "# User@Host: app[app] @ [10.0.0.1]  Id: 1\n"
            "# Query_time: 3.2 Lock_time: 0.1 Rows_sent: 0 Rows_examined: 5000\n"
            "SET timestamp=1;\n"
            "SELECT * FROM big;\n"
            "# Time: 2026-10-15T02:00:09Z\n"
            "# User@Host: root[root] @ localhost  Id: 2\n"
            "# Query_time: 1.0 Lock_time: 0.0 Rows_sent: 1 Rows_examined: 99 Thread_id: 7 Errno: 0 Killed: 0\n"
            "SET timestamp=2;\n"
            "SELECT 1 FROM small;\n"
        )
        entries, _ = parse_slowlog(text)
        assert len(entries) == 2
        assert entries[1].query_time == 1.0

    def test_multi_line_statement(self) -> None:
        text = "# Query_time: 1 Rows_sent: 1 Rows_examined: 1\nSET timestamp=1;\nSELECT a,\n       b\nFROM t;\n"
        entries, _ = parse_slowlog(text)
        assert entries[0].statement == "SELECT a,\n       b\nFROM t;"

    def test_timestamp_fallback_without_time_header(self) -> None:
        text = "# Query_time: 1 Rows_sent: 1 Rows_examined: 1\nSET timestamp=1792730400;\nSELECT 1 FROM t;\n"
        entries, _ = parse_slowlog(text)
        assert entries[0].time_hint == "1792730400"

    def test_malformed_metric_value_skipped(self) -> None:
        """指标值损坏时跳过该条目并计数，不中断解析。"""
        text = (
            "# Query_time: 1.2.3 Lock_time: 0.0 Rows_sent: 1 Rows_examined: 1\n"
            "SET timestamp=1;\n"
            "SELECT 1 FROM broken;\n"
            "# Query_time: 2 Rows_sent: 1 Rows_examined: 2\n"
            "SET timestamp=2;\n"
            "SELECT 2 FROM fine;\n"
        )
        entries, skipped = parse_slowlog(text)
        assert skipped == 1
        assert len(entries) == 1
        assert entries[0].statement.startswith("SELECT 2")

    def test_shared_time_line_5_7_style(self) -> None:
        """老版本同一秒连续条目可能共享/省略 # Time 行：不丢条目。"""
        text = (
            "# Time: 2026-10-15T02:00:00Z\n"
            "# Query_time: 1 Rows_sent: 1 Rows_examined: 1\n"
            "SET timestamp=1;\n"
            "SELECT 1 FROM a;\n"
            "# Query_time: 2 Rows_sent: 1 Rows_examined: 2\n"
            "SET timestamp=1;\n"
            "SELECT 2 FROM b;\n"
        )
        entries, _ = parse_slowlog(text)
        assert len(entries) == 2


class TestAggregate:
    def test_same_fingerprint_merged(self) -> None:
        report = analyze_slowlog(SAMPLE, "slow.log")
        assert report.entries_parsed == 3
        top = report.top
        # 两条同模板（仅字面量不同）的 orders 查询聚合为一条，累计耗时排序第一
        orders = [a for a in top if "orders" in a.fingerprint]
        assert len(orders) == 1
        assert orders[0].count == 2
        assert orders[0].query_time_total == 4.0
        assert orders[0].query_time_max == 2.5
        assert orders[0].rows_examined_total == 300000
        assert "user_id = 42" in orders[0].sample  # 保留首条样本

    def test_sorted_by_total_query_time(self) -> None:
        report = analyze_slowlog(SAMPLE, "slow.log")
        totals = [a.query_time_total for a in report.top]
        assert totals == sorted(totals, reverse=True)

    def test_top_limit(self) -> None:
        entries, _ = parse_slowlog(SAMPLE)
        assert len(aggregate(entries, top=1)) == 1


class TestSkippedLinesContract:
    def test_skipped_lines_in_json_and_render(self) -> None:
        """跳过计数必须进入报告，供生成端、文档和 UI 使用。"""
        from modou.patrol.report import slowlog_render, slowlog_to_json

        text = (
            "# Query_time: 1.2.3 Rows_sent: 1 Rows_examined: 1\nSET timestamp=1;\nSELECT 1 FROM broken;\n"
            "# Query_time: 2 Rows_sent: 1 Rows_examined: 2\nSET timestamp=2;\nSELECT 2 FROM fine;\n"
        )
        report = analyze_slowlog(text, "slow.log")
        assert report.skipped_lines == 1
        as_json = slowlog_to_json(report)
        assert as_json["skipped_lines"] == 1
        assert "跳过 1 条" in slowlog_render(report)
