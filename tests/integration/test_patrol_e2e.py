"""patrol 影子集成测试：连库未用索引分层判定 + 现场实采漂移。"""

from __future__ import annotations

import pymysql

from tests.conftest import unique_db


def _setup(conn: pymysql.connections.Connection, db: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{db}`")
        conn.select_db(db)
        cursor.execute(
            "CREATE TABLE t (id INT NOT NULL PRIMARY KEY, a INT DEFAULT NULL, b INT DEFAULT NULL, "
            "KEY idx_a (a), KEY idx_b (b)) ENGINE=InnoDB"
        )
        cursor.executemany("INSERT INTO t (id, a, b) VALUES (%s, %s, %s)", [(i, i % 10, i % 7) for i in range(1, 501)])
    conn.commit()


class TestPatrolShadowE2E:
    def test_live_unused_indexes_layered(self, mysql_conn) -> None:
        """FORCE INDEX 读 idx_a、不读 idx_b：零计数者判「确认未用」（观察窗 0 天）。"""
        from modou.patrol.unused_indexes import (
            STATUS_CONFIRMED_UNUSED,
            STATUS_LOW_USE,
            judge_unused_indexes,
            read_index_io_counts,
            read_uptime,
        )
        from modou.snapshot.introspect import read_database_inventory

        db = unique_db("patrol")
        _setup(mysql_conn, db)
        with mysql_conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{db}`.`t` FORCE INDEX (idx_a) WHERE a = 5 LIMIT 10")
            cursor.fetchall()
        mysql_conn.commit()

        inventory = read_database_inventory(mysql_conn, db)
        counts = read_index_io_counts(mysql_conn, db)
        uptime = read_uptime(mysql_conn)
        usages = judge_unused_indexes(inventory, counts, uptime_seconds=uptime, observe_days=0)
        by_name = {u.index_name: u for u in usages}
        assert by_name["idx_a"].status == STATUS_LOW_USE
        assert by_name["idx_a"].count_star > 0
        assert by_name["idx_b"].status == STATUS_CONFIRMED_UNUSED
        assert by_name["idx_b"].drop_statement is not None

    def test_live_capture_drift(self, mysql_server, mysql_conn) -> None:
        """现场实采第二份：两轮采集间加索引 → 报告「新增」。"""
        from modou.snapshot.capture import capture_to_file

        db = unique_db("patrol_d")
        _setup(mysql_conn, db)
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        before = tmp / "before.json"
        capture_to_file(mysql_server.connect_params(), [db], before)
        with mysql_conn.cursor() as cursor:
            cursor.execute(f"ALTER TABLE `{db}`.`t` ADD INDEX idx_new (b)")
        mysql_conn.commit()
        after = tmp / "after.json"
        capture_to_file(mysql_server.connect_params(), [db], after)

        from modou.patrol.drift import drift_between_snapshots
        from modou.snapshot.model import snapshot_from_json

        report = drift_between_snapshots(
            snapshot_from_json(before.read_text(encoding="utf-8")).databases,
            snapshot_from_json(after.read_text(encoding="utf-8")).databases,
        )
        assert report.exit_code == 1
        added = report.conclusions[db]
        assert any(c.category == "added" and "indexes" in c.dimensions for c in added)
