"""optimize 车道影子集成测试（MOUDO_TEST_SHADOW=1 门禁）：采样采集 → 数据灌入 →
实测判定 → 实证关（AI 无效建议被拦截）。

每测试使用独立库名：注入的会话级影子容器会被多个测试复用，restore 不删除已存在
对象，库名隔离避免 CREATE TABLE 冲突。
"""

from __future__ import annotations

import pymysql

from modou.optimize.candidates import IndexCandidate
from modou.optimize.pipeline import OptimizeOutcome, run_optimize
from modou.snapshot.capture import capture_to_file
from tests.conftest import unique_db

from ..optimize.conftest import make_snapshot

SETUP_ROWS = 2000


def _setup_orders(conn: pymysql.connections.Connection, db_name: str, *, with_created_index: bool = False) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{db_name}`")
        cursor.execute(f"USE `{db_name}`")
        extra = ", INDEX idx_user_created (user_id, status)" if with_created_index else ""
        cursor.execute(
            f"CREATE TABLE orders ("
            f"  id INT NOT NULL PRIMARY KEY,"
            f"  user_id INT DEFAULT NULL,"
            f"  amount DECIMAL(10,2) DEFAULT NULL,"
            f"  status INT DEFAULT NULL{extra}"
            f") ENGINE=InnoDB"
        )
        cursor.executemany(
            "INSERT INTO orders (id, user_id, amount, status) VALUES (%s, %s, %s, %s)",
            [(i, i % 50, i * 1.5, i % 3) for i in range(1, SETUP_ROWS + 1)],
        )
    conn.commit()


def _capture_renamed(shadow, source_db: str, target_db: str, sample_rows: int):
    """在影子容器上采样采集并把库改名为 target_db（restore 需要全新库名）。"""
    snapshot = capture_to_file(shadow.connect_params(), [source_db], _tmp_json(target_db), sample_rows=sample_rows)
    inventory = snapshot.databases.pop(source_db)
    inventory.name = target_db
    snapshot.databases[target_db] = inventory
    return snapshot


def _tmp_json(name: str):
    import tempfile
    from pathlib import Path

    return Path(tempfile.gettempdir()) / f"modou-opt-{name}.json"


def _suggestions_of(outcome: OptimizeOutcome, db_name: str) -> list[dict]:
    grouped = outcome.report_json["databases"][db_name]
    return [s for stmt in grouped["statements"] for s in stmt["suggestions"]]


class TestOptimizeShadowE2E:
    def test_sample_capture_deterministic_and_restores_rows(self, mysql_server, mysql_conn) -> None:
        """同库同参数两次采集样本集一致；数据灌入后影子行数与快照记录一致。"""
        db = unique_db("opt_cap")
        _setup_orders(mysql_conn, db)
        first = _capture_renamed(mysql_server, db, unique_db("opt_cap_t"), sample_rows=500)
        second_snapshot = capture_to_file(mysql_server.connect_params(), [db], _tmp_json("dup"), sample_rows=500)
        table_first = first.databases[next(iter(first.databases))].tables["orders"]
        table_second = second_snapshot.databases[db].tables["orders"]
        assert table_first.sample is not None and table_second.sample is not None
        assert table_first.sample.rows == table_second.sample.rows
        assert table_first.sample.sampled_rows == 500
        assert table_first.sample.estimated_rows == SETUP_ROWS

        target_db = next(iter(first.databases))
        from modou.snapshot.restore import restore_snapshot

        restore_snapshot(mysql_conn, first, database_filter={target_db}, include_data=True)
        with mysql_conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM `{target_db}`.`orders`")
            assert cursor.fetchone()[0] == 500

    def test_effective_index_measured(self, mysql_server, mysql_conn) -> None:
        """有效索引候选：影子实测代价下降 → measured + 提升幅度，退出码 0。"""
        source_db = unique_db("opt_eff")
        _setup_orders(mysql_conn, source_db)
        target_db = unique_db("opt_eff_t")
        snapshot = _capture_renamed(mysql_server, source_db, target_db, sample_rows=1000)
        statements_file_sql = "SELECT * FROM orders WHERE user_id = 42 AND amount > 10"
        outcome = run_optimize([statements_file_sql], snapshot, default_database=target_db, shadow=mysql_server)
        assert outcome.exit_code == 0
        suggestions = _suggestions_of(outcome, target_db)
        assert suggestions, "expected at least one rule candidate"
        measured = [s for s in suggestions if s["status"] == "measured"]
        assert measured, f"expected a measured suggestion, got: {[(s['status'], s['reason']) for s in suggestions]}"
        top = max(measured, key=lambda s: s["improvement_pct"])
        assert top["improvement_pct"] > 0
        assert top["cost_after"] < top["cost_before"]
        # 报告两级状态：不存在第三种状态
        assert all(s["status"] in ("measured", "unverified") for s in suggestions)
        # 实证环境数据规模披露在场
        assert outcome.report_json["evidence_env"]["tables"]

    def test_ai_bogus_suggestion_intercepted_by_evidence(self, mysql_server, mysql_conn, monkeypatch) -> None:
        """实证关（ADR-0003）：AI 产出的低选择性索引建议实测无提升 → 标「未验证」，
        报告与退出码不受 AI 输出影响（退出码保持 0）。"""
        import modou.optimize.pipeline as pipeline_module

        source_db = unique_db("opt_ai")
        _setup_orders(mysql_conn, source_db)
        target_db = unique_db("opt_ai_t")
        snapshot = _capture_renamed(mysql_server, source_db, target_db, sample_rows=1000)

        def fake_advisor(*args, **kwargs):
            # 模拟 AI 幻觉式建议：对 status（仅 3 个取值）建独立索引
            return [IndexCandidate(None, "orders", ["status"], "AI 建议索引", source="ai")]

        monkeypatch.setattr(pipeline_module, "maybe_fetch_candidates", fake_advisor)
        outcome = run_optimize(
            # 语句只涉及 amount（规则候选在 amount 上）；AI 建议在 status 上（与规则候选
            # 不同列，不会被去重）——低选择性索引实测无提升，必须被实证关拦下
            ["SELECT * FROM orders WHERE amount > 100"],
            snapshot,
            default_database=target_db,
            shadow=mysql_server,
            advisor_config=pipeline_module.AdvisorConfig("https://x/v1", "k", "fake-model"),
        )
        assert outcome.exit_code == 0
        suggestions = _suggestions_of(outcome, target_db)
        ai_suggestions = [s for s in suggestions if s["source"] == "ai"]
        assert ai_suggestions, "AI candidate should reach the evidence stage"
        # 低选择性索引在 2000 行表上不会有实质提升：必须被实证关拦下
        assert all(s["status"] == "unverified" for s in ai_suggestions)
        assert all("代价未降低" in (s["reason"] or "") for s in ai_suggestions)
        # 候选索引已被回滚删除：影子表索引数恢复基线
        with mysql_conn.cursor() as cursor:
            cursor.execute(f"SHOW INDEX FROM `{target_db}`.`orders`")
            names = {row[2] for row in cursor.fetchall()}
        assert names == {"PRIMARY"}

    def test_redundant_candidate_skips_evidence(self, mysql_server, mysql_conn) -> None:
        """冗余候选（被现有索引前缀覆盖）：确定性判定跳过实证，标「未验证（冗余）」。"""
        source_db = unique_db("opt_red")
        _setup_orders(mysql_conn, source_db, with_created_index=True)
        target_db = unique_db("opt_red_t")
        snapshot = _capture_renamed(mysql_server, source_db, target_db, sample_rows=500)
        outcome = run_optimize(
            ["SELECT * FROM orders WHERE user_id = 7"], snapshot, default_database=target_db, shadow=mysql_server
        )
        assert outcome.exit_code == 0
        suggestions = _suggestions_of(outcome, target_db)
        redundant = [s for s in suggestions if s.get("reason", "") and "冗余" in s["reason"]]
        assert redundant, f"expected redundant candidate, got {suggestions}"
        assert all(s["status"] == "unverified" for s in redundant)
        # 冗余候选未做实证：cost_after 保持 None（未建索引）
        assert all(s["cost_after"] is None for s in redundant)

    def test_ddl_and_unsampled_input_exit_2(self, mysql_server, mysql_conn) -> None:
        source_db = unique_db("opt_bad")
        _setup_orders(mysql_conn, source_db)
        outcome = run_optimize(["CREATE TABLE x (id int)"], make_snapshot(with_sample=True), shadow=mysql_server)
        assert outcome.exit_code == 2
        structure_only = capture_to_file(mysql_server.connect_params(), [source_db], _tmp_json("plain"))
        inventory = structure_only.databases.pop(source_db)
        target_db = unique_db("opt_bad_t")
        inventory.name = target_db
        structure_only.databases[target_db] = inventory
        outcome2 = run_optimize(
            ["SELECT * FROM orders WHERE user_id = 1"], structure_only, default_database=target_db, shadow=mysql_server
        )
        assert outcome2.exit_code == 2
        assert "sample" in " ".join(outcome2.report_json["input_errors"])


def test_generated_column_sampling_roundtrip(mysql_server) -> None:
    """生成列表采样灌入回归：显式赋值生成列的 INSERT 报 3105，采样列清单必须排除它。"""
    from modou.snapshot.restore import restore_snapshot

    source = unique_db("opt_gen_src")
    target = unique_db("opt_gen_tgt")
    conn = mysql_server.connect_params().connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{source}`")
            cursor.execute(f"USE `{source}`")
            cursor.execute(
                "CREATE TABLE t ("
                "  id INT NOT NULL PRIMARY KEY,"
                "  first_name VARCHAR(20) DEFAULT NULL,"
                "  full_name VARCHAR(41) GENERATED ALWAYS AS (CONCAT(first_name, ' !')) VIRTUAL"
                ") ENGINE=InnoDB"
            )
            cursor.executemany(
                "INSERT INTO t (id, first_name) VALUES (%s, %s)",
                [(i, f"name{i}") for i in range(1, 51)],
            )
        conn.commit()
        snapshot = _capture_renamed(mysql_server, source, target, sample_rows=10)
        sample = snapshot.databases[target].tables["t"].sample
        assert sample is not None and sample.rows
        assert "full_name" not in sample.columns
        shadow_conn = mysql_server.connect_params().connect()
        try:
            restore_snapshot(shadow_conn, snapshot, database_filter={target}, include_data=True)
            with shadow_conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM `{target}`.`t`")
                assert cursor.fetchone()[0] == 10
        finally:
            shadow_conn.close()
    finally:
        conn.close()
