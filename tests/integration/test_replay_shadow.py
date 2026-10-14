"""回放器集成用例：变更集执行 = 期望态；失败语句指认（序号 + 错误）。"""

from __future__ import annotations

from pathlib import Path

import pymysql.connections

from modou.changeset.pack import pack_changeset
from modou.replay.replay import replay_statements
from modou.replay.splitter import split_statements
from tests.integration.conftest import unique_db


def make_changeset(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    return tmp_path


def packed_statements(changeset_dir: Path) -> list[str]:
    return split_statements(pack_changeset(changeset_dir).packed_sql)


def test_replay_applies_changeset_in_order(mysql_conn: pymysql.connections.Connection, tmp_path: Path) -> None:
    db_name = unique_db()
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name}")
    mysql_conn.select_db(db_name)

    changeset = make_changeset(
        tmp_path,
        {
            "V01__create.sql": "CREATE TABLE orders (id INT PRIMARY KEY, note VARCHAR(100));",
            "V02__alter.sql": "ALTER TABLE orders ADD COLUMN flag TINYINT NOT NULL DEFAULT 0;",
        },
    )
    result = replay_statements(mysql_conn, packed_statements(changeset))

    assert result.error is None
    assert result.executed_count == 2
    with mysql_conn.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.COLUMNS "
            "WHERE table_schema = %s AND table_name = 'orders' ORDER BY ordinal_position",
            (db_name,),
        )
        columns = [str(row[0]) for row in cursor.fetchall()]
    assert columns == ["id", "note", "flag"]


def test_replay_failure_reports_statement_index(mysql_conn: pymysql.connections.Connection, tmp_path: Path) -> None:
    db_name = unique_db()
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name}")
    mysql_conn.select_db(db_name)

    changeset = make_changeset(
        tmp_path,
        {
            "V01__ok.sql": "CREATE TABLE t1 (id INT PRIMARY KEY);",
            "V02__broken.sql": "CREATE TABLE (",
        },
    )
    result = replay_statements(mysql_conn, packed_statements(changeset))

    assert result.error is not None
    assert result.error.statement_index == 2
    assert result.error.error_code == 1064  # 语法错误
    # 中止语义：失败语句之后不再执行（本例失败即最后一条，已执行 1 条）
    assert result.executed_count == 1


def test_replay_delimiter_block_creates_procedure(mysql_conn: pymysql.connections.Connection, tmp_path: Path) -> None:
    db_name = unique_db()
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name}")
    mysql_conn.select_db(db_name)

    changeset = make_changeset(
        tmp_path,
        {
            "V01__proc.sql": (
                "DELIMITER $$\n"
                "CREATE PROCEDURE add_user(IN p_name VARCHAR(50))\n"
                "BEGIN\n"
                "    INSERT INTO users (name) VALUES (p_name);\n"
                "END$$\n"
                "DELIMITER ;\n"
                "CREATE TABLE users (id INT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(50));\n"
            )
        },
    )
    statements = packed_statements(changeset)
    # 过程体不被内部分号拆散
    assert len(statements) == 2

    result = replay_statements(mysql_conn, statements)
    assert result.error is None, f"replay failed: {result.error}"

    with mysql_conn.cursor() as cursor:
        cursor.execute(
            "SELECT routine_name FROM information_schema.ROUTINES "
            "WHERE routine_schema = %s AND routine_type = 'PROCEDURE'",
            (db_name,),
        )
        assert [str(row[0]) for row in cursor.fetchall()] == ["add_user"]

    # 过程可调用（语义与单文件执行一致）
    with mysql_conn.cursor() as cursor:
        cursor.execute("CALL add_user(%s)", ("张三",))
        cursor.execute("SELECT name FROM users")
        assert str(cursor.fetchone()[0]) == "张三"


def test_replay_session_database_via_use(mysql_conn: pymysql.connections.Connection, tmp_path: Path) -> None:
    """变更集内 USE 切库：跨库语句按声明落库（多库默认，ADR-0008）。"""
    db0, db1 = unique_db("modou_a"), unique_db("modou_b")
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db0}")
        cursor.execute(f"CREATE DATABASE {db1}")

    changeset = make_changeset(
        tmp_path,
        {
            "V01__cross.sql": (
                f"USE `{db0}`;\n"
                "CREATE TABLE t_a (id INT PRIMARY KEY);\n"
                f"USE `{db1}`;\n"
                "CREATE TABLE t_b (id INT PRIMARY KEY);\n"
            )
        },
    )
    result = replay_statements(mysql_conn, packed_statements(changeset))
    assert result.error is None, f"replay failed: {result.error}"

    with mysql_conn.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema, table_name FROM information_schema.TABLES "
            "WHERE table_name IN ('t_a', 't_b') ORDER BY table_name"
        )
        found = {(str(row[0]), str(row[1])) for row in cursor.fetchall()}
    assert (db0, "t_a") in found
    assert (db1, "t_b") in found
