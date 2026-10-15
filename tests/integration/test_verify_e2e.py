"""端到端验收：真实形态变更集 + 人工构造的执行结果，verify 必须给出正确结论与退出码。

场景映射 spec：
- 全部落地 → 退出码 0；
- 漏执行一条语句 → 「漏执行」指认该语句影响的对象，退出码 1；
- 索引列序建错 → 「错执行」展示两侧定义，退出码 1；
- 与变更无关的并行改动 → 「历史漂移」，不与本次变更结论混淆；
- 多库清单 → 报告按库分组，退出码取最严重档；
- 语法错误 / 环境不匹配 / 缺 default-database → 退出码 2。
"""

from __future__ import annotations

from pathlib import Path

import pymysql.connections

from modou.changeset.pack import pack_changeset
from modou.diff.pipeline import run_verify
from modou.diff.threeway import KIND_DRIFT, KIND_MISSING, KIND_WRONG
from modou.replay.splitter import split_statements
from modou.report.render import EXIT_DIFF, EXIT_ERROR, EXIT_OK
from modou.snapshot.introspect import capture_snapshot
from tests.conftest import unique_db

CREATE_ORDERS = (
    "CREATE TABLE orders (\n"
    "  id BIGINT NOT NULL PRIMARY KEY,\n"
    "  user_id BIGINT NOT NULL,\n"
    "  amount DECIMAL(12,2) NOT NULL DEFAULT 0.00\n)"
)
ADD_REMARK = "ALTER TABLE orders ADD COLUMN remark VARCHAR(200) NOT NULL DEFAULT ''"
ADD_INDEX = "ALTER TABLE orders ADD INDEX idx_user_amount (user_id, amount)"
PROCEDURE_BLOCK = (
    "DELIMITER $$\n"
    "CREATE PROCEDURE sp_order_count(IN p_user BIGINT, OUT p_total INT)\n"
    "BEGIN\n"
    "    SELECT COUNT(*) INTO p_total FROM orders WHERE user_id = p_user;\n"
    "END$$\n"
    "DELIMITER ;"
)


def write_single_db_changeset(tmp_path: Path) -> Path:
    """单库变更集：语句不带库名，靠 --default-database 指定目标库。"""
    files = {
        "V01__create_orders.sql": CREATE_ORDERS + ";",
        "V02__alter_orders.sql": ADD_REMARK + ";",
        "V03__add_index.sql": ADD_INDEX + ";",
        "V04__procedure.sql": PROCEDURE_BLOCK,
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    return tmp_path


def write_multi_db_changeset(tmp_path: Path, db0: str, db1: str) -> Path:
    """跨库变更集：USE 声明目标库（双库各来一套，存储过程仅主库）。"""
    files = {
        "V01__create_orders.sql": f"USE `{db0}`;\n{CREATE_ORDERS};\nUSE `{db1}`;\n{CREATE_ORDERS};",
        "V02__alter_orders.sql": f"USE `{db0}`;\n{ADD_REMARK};\nUSE `{db1}`;\n{ADD_REMARK};",
        "V03__add_index.sql": f"USE `{db0}`;\n{ADD_INDEX};\nUSE `{db1}`;\n{ADD_INDEX};",
        "V04__procedure.sql": f"USE `{db0}`;\n{PROCEDURE_BLOCK}",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    return tmp_path


def packed_statements(changeset_dir: Path) -> list[str]:
    return split_statements(pack_changeset(changeset_dir).packed_sql)


def _statement_db_target(statement: str) -> str | None:
    """从语句文本解析 USE 目标库：跳过前导注释行（pack 头注释附着在文件首语句上）。"""
    for line in statement.splitlines():
        text = line.strip()
        if not text or text.startswith("--") or text.startswith("#"):
            continue
        if text.upper().startswith("USE "):
            return text[4:].strip().rstrip(";").strip().strip("`")
        return None
    return None


def apply_as_ops(
    conn: pymysql.connections.Connection,
    db_name: str | None,
    statements: list[str],
    skip=None,
) -> None:
    """模拟运维执行打包脚本：单连接顺序执行（USE 语句自然切库）。

    db_name 为单库执行的默认库（运维先 USE 后跑脚本）；跨库变更集传 None 靠 USE 切换。
    skip(current_db, statement) 为真时跳过该语句（构造漏执行）。
    """
    if db_name is not None:
        conn.select_db(db_name)
    current_db = db_name
    with conn.cursor() as cursor:
        for statement in statements:
            target = _statement_db_target(statement)
            if target is not None:
                current_db = target
            if skip is not None and current_db is not None and skip(current_db, statement):
                continue
            cursor.execute(statement)


def prepare_baseline_db(conn: pymysql.connections.Connection, db_name: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        cursor.execute(f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cursor.execute(f"CREATE TABLE `{db_name}`.t_users (id BIGINT NOT NULL PRIMARY KEY, name VARCHAR(64) NOT NULL)")
        cursor.execute(
            f"CREATE TABLE `{db_name}`.t_config ("
            "id INT NOT NULL PRIMARY KEY, k VARCHAR(32) NOT NULL, v VARCHAR(255) NULL)"
        )


def capture_dbs(mysql_server, db_names: list[str]):
    return capture_snapshot(mysql_server.connect_params(), db_names)


def drop_dbs(conn: pymysql.connections.Connection, db_names: list[str]) -> None:
    with conn.cursor() as cursor:
        for db_name in db_names:
            cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")


# ── 场景一：全部正确落地 → 0 ─────────────────────────────────────────────


def test_verify_all_landed_exit_zero(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    apply_as_ops(mysql_conn, db_name, packed_statements(write_single_db_changeset(tmp_path)))
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database=db_name
    )

    assert outcome.exit_code == EXIT_OK
    assert outcome.report.databases == {}
    assert "全部一致" in outcome.render()


# ── 场景二：漏执行 ALTER 与索引 → 漏执行指认对象，退出码 1 ───────────────────


def test_verify_missed_alter_is_caught(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    statements = packed_statements(write_single_db_changeset(tmp_path))
    # 运维漏了 V02（加列）与 V03（索引）
    apply_as_ops(mysql_conn, db_name, [s for s in statements if "ALTER TABLE orders" not in s])
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database=db_name
    )

    assert outcome.exit_code == EXIT_DIFF
    conclusions = outcome.report.databases[db_name]
    orders = [c for c in conclusions if c.object_name == "orders"]
    assert orders, "orders 表必须出现在结论中"
    assert all(c.kind == KIND_MISSING for c in orders)
    dimensions = {d for c in orders for d in c.dimensions}
    assert "columns" in dimensions  # remark 列缺失
    assert "indexes" in dimensions  # idx_user_amount 缺失
    assert all(c.object_type != "procedure" for c in conclusions)  # 存储过程已落地
    text = outcome.render()
    assert "漏执行" in text and "orders" in text


# ── 场景三：索引列序建错 → 错执行 ─────────────────────────────────────────


def test_verify_wrong_index_column_order_is_caught(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    statements = [
        s.replace("idx_user_amount (user_id, amount)", "idx_user_amount (amount, user_id)")
        for s in packed_statements(write_single_db_changeset(tmp_path))
    ]
    apply_as_ops(mysql_conn, db_name, statements)
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database=db_name
    )

    assert outcome.exit_code == EXIT_DIFF
    wrong = [c for c in outcome.report.databases[db_name] if c.kind == KIND_WRONG]
    assert len(wrong) == 1
    assert wrong[0].object_name == "orders"
    assert wrong[0].dimensions == ["indexes"]
    detail = wrong[0].details[0]
    assert detail.expected.index("user_id") < detail.expected.index("amount")
    assert detail.actual.index("amount") < detail.actual.index("user_id")


# ── 场景四：无关并行改动 → 历史漂移，不与本次变更混淆 ────────────────────────


def test_verify_unrelated_drift_is_isolated(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    apply_as_ops(mysql_conn, db_name, packed_statements(write_single_db_changeset(tmp_path)))
    # 他人并行改动：变更集未触碰 t_config
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"ALTER TABLE `{db_name}`.t_config ADD COLUMN extra VARCHAR(50) NULL")
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database=db_name
    )

    assert outcome.exit_code == EXIT_DIFF
    conclusions = outcome.report.databases[db_name]
    assert [c.kind for c in conclusions] == [KIND_DRIFT]
    assert conclusions[0].object_name == "t_config"


# ── 场景五：多库清单 → 按库分组聚合，退出码取最严重档 ────────────────────────


def test_verify_multi_database_grouped_and_aggregated(mysql_server, mysql_conn, tmp_path) -> None:
    db0, db1 = unique_db("modou_m0"), unique_db("modou_m1")
    prepare_baseline_db(mysql_conn, db0)
    prepare_baseline_db(mysql_conn, db1)
    baseline = capture_dbs(mysql_server, [db0, db1])
    changeset_dir = write_multi_db_changeset(tmp_path, db0, db1)
    # 库 1 漏掉索引语句（其余全部落地）
    apply_as_ops(
        mysql_conn,
        None,
        packed_statements(changeset_dir),
        skip=lambda db, s: db == db1 and "idx_user_amount" in s,
    )
    after = capture_dbs(mysql_server, [db0, db1])
    drop_dbs(mysql_conn, [db0, db1])

    outcome = run_verify(baseline, after, changeset_dir, shadow=mysql_server)

    assert outcome.exit_code == EXIT_DIFF
    assert db0 not in outcome.report.databases  # 库 0 全部落地，无结论
    kinds_db1 = {c.kind for c in outcome.report.databases[db1]}
    assert kinds_db1 == {KIND_MISSING}
    assert {c.object_name for c in outcome.report.databases[db1]} == {"orders"}


# ── 场景六：变更集正确 DROP 对象 → 退出码 0（回归：diff 曾在此崩溃）───────────


def test_verify_correctly_executed_drop_exit_zero(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE TABLE `{db_name}`.t_old (id INT NOT NULL PRIMARY KEY)")
    baseline = capture_dbs(mysql_server, [db_name])
    changeset_dir = tmp_path / "cs-drop"
    changeset_dir.mkdir()
    (changeset_dir / "V01__drop_old.sql").write_text("DROP TABLE t_old;", encoding="utf-8")
    (changeset_dir / "manifest.txt").write_text("V01__drop_old.sql\n", encoding="utf-8")
    apply_as_ops(mysql_conn, db_name, packed_statements(changeset_dir))
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(baseline, after, changeset_dir, shadow=mysql_server, default_database=db_name)

    assert outcome.exit_code == EXIT_OK, outcome.render()


# ── 场景七：变更集新建库 → 可验收（基线缺库不是错误）─────────────────────────


def test_verify_new_database_created_by_changeset(mysql_server, mysql_conn, tmp_path) -> None:
    db0 = unique_db()
    newdb = unique_db("modou_new")
    prepare_baseline_db(mysql_conn, db0)
    baseline = capture_dbs(mysql_server, [db0])  # 基线尚无 newdb
    changeset_dir = tmp_path / "cs-newdb"
    changeset_dir.mkdir()
    (changeset_dir / "V01__create_db.sql").write_text(
        f"CREATE DATABASE `{newdb}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;\n"
        f"CREATE TABLE `{newdb}`.t1 (id INT NOT NULL PRIMARY KEY);\n",
        encoding="utf-8",
    )
    (changeset_dir / "manifest.txt").write_text("V01__create_db.sql\n", encoding="utf-8")
    apply_as_ops(mysql_conn, None, packed_statements(changeset_dir))  # 全限定名，无需默认库
    after = capture_dbs(mysql_server, [db0, newdb])
    drop_dbs(mysql_conn, [db0, newdb])

    outcome = run_verify(baseline, after, changeset_dir, shadow=mysql_server)

    assert outcome.exit_code == EXIT_OK, outcome.render()


# ── 场景八：基线缺库且回放也未创建 → 输入错误退出码 2 ────────────────────────


def test_verify_baseline_missing_db_not_created_by_replay_exit_two(mysql_server, mysql_conn, tmp_path) -> None:
    db0 = unique_db()
    newdb = unique_db("modou_new")
    prepare_baseline_db(mysql_conn, db0)
    baseline = capture_dbs(mysql_server, [db0])
    # 变更集不建库；人工在实际侧建了库（他人所为）→ 期望态无从推导
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{newdb}`")
    changeset_dir = tmp_path / "cs-noop"
    changeset_dir.mkdir()
    (changeset_dir / "V01__noop.sql").write_text("SELECT 1;", encoding="utf-8")
    (changeset_dir / "manifest.txt").write_text("V01__noop.sql\n", encoding="utf-8")
    after = capture_dbs(mysql_server, [db0, newdb])
    drop_dbs(mysql_conn, [db0, newdb])

    outcome = run_verify(baseline, after, changeset_dir, shadow=mysql_server)

    assert outcome.exit_code == EXIT_ERROR
    assert any("cannot be derived" in e for e in outcome.report.env_errors)


# ── 场景九：影子阶段意外（--default-database 拼错 → 1049）→ 退出码 2 而非裸崩 ──


def test_verify_wrong_default_database_exit_two(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database="no_such_db"
    )

    assert outcome.exit_code == EXIT_ERROR
    assert any("shadow operation failed" in e for e in outcome.report.env_errors)


# ── 场景十：变更集语法错误 → 退出码 2 + 语句序号 ────────────────────────────


def test_verify_replay_failure_exit_two(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])
    broken = write_single_db_changeset(tmp_path)
    (broken / "V02__alter_orders.sql").write_text("CREATE TABLE (;", encoding="utf-8")  # 合法切分、非法执行

    outcome = run_verify(baseline, after, broken, shadow=mysql_server, default_database=db_name)

    assert outcome.exit_code == EXIT_ERROR
    assert outcome.report.replay_error is not None
    assert outcome.report.replay_error["statement_index"] == 2
    assert outcome.report.replay_error["error_code"] == 1064


# ── 场景十一：影子版本序列不匹配 → 环境错误退出码 2 ──────────────────────────


def test_verify_version_mismatch_exit_two(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])
    baseline.meta.server_version = "8.0.36"  # 受支持但序列（8.0）与影子（8.4）不同；5.7 会被版本地板先行拒绝

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database=db_name
    )

    assert outcome.exit_code == EXIT_ERROR
    assert any("version series mismatch" in e for e in outcome.report.env_errors)


# ── 场景十二：无 USE 且未给 default-database → 输入错误退出码 2 ──────────────


def test_verify_missing_default_database_exit_two(mysql_server, mysql_conn, tmp_path) -> None:
    db_name = unique_db()
    prepare_baseline_db(mysql_conn, db_name)
    baseline = capture_dbs(mysql_server, [db_name])
    after = capture_dbs(mysql_server, [db_name])
    drop_dbs(mysql_conn, [db_name])

    outcome = run_verify(
        baseline, after, write_single_db_changeset(tmp_path), shadow=mysql_server, default_database=None
    )

    assert outcome.exit_code == EXIT_ERROR
    assert outcome.report.replay_error is not None
    assert outcome.report.replay_error["error_code"] == 1046
