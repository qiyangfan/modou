"""快照 round-trip 测试：采集、灌入、再采集并比较结构字段。"""

from __future__ import annotations

from dataclasses import replace

import pymysql.connections

from modou.snapshot.introspect import capture_snapshot
from modou.snapshot.restore import restore_snapshot
from tests.conftest import unique_db

RICH_SCHEMA = """
CREATE TABLE t_inherit (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL COMMENT '用户名',
    status ENUM('active','disabled') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_name (name),
    KEY idx_name_prefix (name(8))
) COMMENT '继承库字符集的表';

CREATE TABLE t_explicit (
    id INT NOT NULL,
    code VARCHAR(32) NOT NULL,
    price DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    attrs JSON NULL DEFAULT (JSON_ARRAY()),
    gen_virtual INT AS (id * 2) VIRTUAL,
    gen_stored INT AS (id + 1) STORED,
    code_lower VARCHAR(32) AS (LOWER(code)) STORED,
    PRIMARY KEY (id),
    KEY idx_func ((UPPER(code)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT '显式字符集表';

CREATE TABLE t_parent (
    id INT NOT NULL PRIMARY KEY
);

CREATE TABLE t_child (
    id INT NOT NULL,
    parent_id INT NOT NULL,
    amount INT NOT NULL,
    CONSTRAINT fk_parent FOREIGN KEY (parent_id) REFERENCES t_parent (id) ON DELETE CASCADE,
    CONSTRAINT chk_amount CHECK (amount >= 0)
);

CREATE VIEW v_join AS SELECT c.id, p.id AS pid FROM t_child c JOIN t_parent p ON c.parent_id = p.id;
"""

RICH_ROUTINES = """
DELIMITER $$
CREATE PROCEDURE sp_count(IN p_status VARCHAR(20), OUT p_total INT)
BEGIN
    SELECT COUNT(*) INTO p_total FROM t_inherit WHERE status = p_status;
END$$
CREATE FUNCTION fn_double(x INT) RETURNS INT DETERMINISTIC
BEGIN
    RETURN x * 2;
END$$
CREATE TRIGGER tr_audit AFTER INSERT ON t_inherit FOR EACH ROW
BEGIN
    SET @last_inserted = NEW.id;
END$$
CREATE EVENT ev_nightly ON SCHEDULE EVERY 1 DAY DO DELETE FROM t_inherit WHERE status = 'disabled'$$
DELIMITER ;
"""


def test_shadow_container_reports_version(mysql_server) -> None:
    assert mysql_server.port > 0
    meta_version = mysql_server.connect_params().connect()
    try:
        with meta_version.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version = str(cursor.fetchone()[0])
    finally:
        meta_version.close()
    assert version.startswith("8.4")


def test_capture_is_structurally_stable(mysql_conn: pymysql.connections.Connection) -> None:
    """同一数据库重复采集得到结构等价的快照。"""
    db_name = unique_db()
    _create_rich_schema(mysql_conn, db_name)
    params = mysql_server_params(mysql_conn)
    first = capture_snapshot(params, [db_name])
    second = capture_snapshot(params, [db_name])
    assert first.databases[db_name] == second.databases[db_name]
    assert first.meta.server_version == second.meta.server_version
    _drop_db(mysql_conn, db_name)


def test_restore_roundtrip_full_fidelity(mysql_conn: pymysql.connections.Connection) -> None:
    """确认再采集的结构字段和对象 DDL 一致；表的 SHOW CREATE 文本不参与比较。"""
    db_name = unique_db()
    _create_rich_schema(mysql_conn, db_name)
    # 先制造 AUTO_INCREMENT 漂移再采集：计数器是运行时状态，不应影响结构等价
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"INSERT INTO {db_name}.t_inherit (name) VALUES ('a'), ('b')")
    params = mysql_server_params(mysql_conn)

    original = capture_snapshot(params, [db_name])
    _drop_db(mysql_conn, db_name)
    restore_snapshot(mysql_conn, original)
    restored = capture_snapshot(params, [db_name])

    original_db, restored_db = original.databases[db_name], restored.databases[db_name]
    assert _structured_view(restored_db) == _structured_view(original_db)
    assert restored.meta.server_version == original.meta.server_version
    # 对象 DDL 应为对应类型的 CREATE 语句。
    for name, trigger in original_db.triggers.items():
        assert trigger.ddl.startswith("CREATE TRIGGER"), f"trigger {name} ddl corrupted: {trigger.ddl[:60]}"
    for name, procedure in original_db.procedures.items():
        assert procedure.ddl.startswith("CREATE PROCEDURE"), f"procedure {name} ddl corrupted: {procedure.ddl[:60]}"
    for name, event in original_db.events.items():
        assert event.ddl.startswith("CREATE EVENT"), f"event {name} ddl corrupted: {event.ddl[:60]}"
    _drop_db(mysql_conn, db_name)


def test_restore_roundtrip_ddl_restable_after_one_pass(mysql_conn: pymysql.connections.Connection) -> None:
    """SHOW CREATE 文本漂移一轮后收敛，第二次 round-trip 表 DDL 也全等。"""
    db_name = unique_db()
    _create_rich_schema(mysql_conn, db_name)
    params = mysql_server_params(mysql_conn)

    first = capture_snapshot(params, [db_name])
    _drop_db(mysql_conn, db_name)
    restore_snapshot(mysql_conn, first)
    second = capture_snapshot(params, [db_name])
    _drop_db(mysql_conn, db_name)
    restore_snapshot(mysql_conn, second)
    third = capture_snapshot(params, [db_name])

    assert third.databases[db_name].tables == second.databases[db_name].tables
    _drop_db(mysql_conn, db_name)


def test_restore_database_charset_inheritance(mysql_conn: pymysql.connections.Connection) -> None:
    """库默认字符集非 utf8mb4 默认 collation 时，继承关系在 round-trip 后保持。"""
    db_name = unique_db()
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"CREATE TABLE {db_name}.t1 (id INT PRIMARY KEY, name VARCHAR(10))")
    params = mysql_server_params(mysql_conn)

    snapshot = capture_snapshot(params, [db_name])
    assert snapshot.databases[db_name].collation == "utf8mb4_unicode_ci"

    _drop_db(mysql_conn, db_name)
    restore_snapshot(mysql_conn, snapshot)
    recaptured = capture_snapshot(params, [db_name])

    assert _structured_view(recaptured.databases[db_name]) == _structured_view(snapshot.databases[db_name])
    with mysql_conn.cursor() as cursor:
        cursor.execute(
            "SELECT table_collation FROM information_schema.TABLES WHERE table_schema = %s AND table_name = 't1'",
            (db_name,),
        )
        # 表未显式声明 collation → 仍继承库的 utf8mb4_unicode_ci
        assert str(cursor.fetchone()[0]) == "utf8mb4_unicode_ci"
    _drop_db(mysql_conn, db_name)


def test_restore_resolves_cross_database_view_dependency(mysql_conn: pymysql.connections.Connection) -> None:
    """db1 视图引用 db2 视图时，灌入须在跨库依赖池中完成。"""
    db1, db2 = unique_db("modou_x1"), unique_db("modou_x2")
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db2}")
        cursor.execute(f"CREATE TABLE {db2}.base (id INT PRIMARY KEY)")
        cursor.execute(f"CREATE VIEW {db2}.v_base AS SELECT id FROM {db2}.base")
        cursor.execute(f"CREATE DATABASE {db1}")
        cursor.execute(f"CREATE VIEW {db1}.v_top AS SELECT id FROM {db2}.v_base")
    params = mysql_server_params(mysql_conn)

    snapshot = capture_snapshot(params, [db1, db2])
    _drop_db(mysql_conn, db1)
    _drop_db(mysql_conn, db2)
    restore_snapshot(mysql_conn, snapshot)

    recaptured = capture_snapshot(params, [db1, db2])
    assert _structured_view(recaptured.databases[db1]) == _structured_view(snapshot.databases[db1])
    assert _structured_view(recaptured.databases[db2]) == _structured_view(snapshot.databases[db2])
    _drop_db(mysql_conn, db1)
    _drop_db(mysql_conn, db2)


def test_capture_fk_ignores_same_name_unique_index_on_other_table(mysql_conn: pymysql.connections.Connection) -> None:
    """同名索引不应跨表混入 FK；KEY_COLUMN_USAGE 必须同时按库名和表名关联。"""
    db_name = unique_db()
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name}")
        cursor.execute(f"CREATE TABLE {db_name}.t_parent (id INT PRIMARY KEY)")
        cursor.execute(
            f"CREATE TABLE {db_name}.t_child (id INT PRIMARY KEY, parent_id INT NOT NULL, "
            f"CONSTRAINT fk_dup FOREIGN KEY (parent_id) REFERENCES {db_name}.t_parent (id))"
        )
        # 他表的唯一索引与 t_child 的 FK 同名（合法）
        cursor.execute(f"CREATE TABLE {db_name}.t_other (id INT PRIMARY KEY, CONSTRAINT fk_dup UNIQUE (id))")
    params = mysql_server_params(mysql_conn)

    snapshot = capture_snapshot(params, [db_name])
    foreign_keys = snapshot.databases[db_name].tables["t_child"].foreign_keys
    assert [fk.name for fk in foreign_keys] == ["fk_dup"]
    assert foreign_keys[0].columns == ["parent_id"]
    assert foreign_keys[0].ref_columns == ["id"]
    assert foreign_keys[0].ref_table == "t_parent"
    _drop_db(mysql_conn, db_name)


# ── 夹具辅助 ─────────────────────────────────────────────────────────────


def _structured_view(inventory):
    """剥离表 DDL 文本后的结构视图（列/索引/约束/表选项/对象 DDL 全保留）。"""
    return replace(
        inventory,
        tables={name: replace(table, ddl="") for name, table in inventory.tables.items()},
    )


def _create_rich_schema(conn: pymysql.connections.Connection, db_name: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        conn.select_db(db_name)
        # 多语句逐条执行；分号边界由测试文本控制，不涉及 DELIMITER
        for statement in RICH_SCHEMA.split(";"):
            if statement.strip():
                cursor.execute(statement)
        for statement in _split_delimiter_block(RICH_ROUTINES):
            cursor.execute(statement)


def _split_delimiter_block(sql: str) -> list[str]:
    """测试用切分器：按 $$ 切出过程体，简化语义与回放切分器一致。"""
    body = sql.split("DELIMITER $$", 1)[1].split("DELIMITER ;", 1)[0]
    return [part.strip().rstrip("$").strip() for part in body.split("$$") if part.strip().rstrip("$").strip()]


def _drop_db(conn: pymysql.connections.Connection, db_name: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")


def mysql_server_params(conn: pymysql.connections.Connection):
    from modou.db import MysqlParams

    return MysqlParams(host=conn.host, port=conn.port, user=conn.user, password=conn.password)
