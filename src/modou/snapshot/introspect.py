"""内省：对在线 MySQL 执行只读语句，产出结构化库清单。

语句清单（全部只读，见 docs/formats.md）：
- SELECT VERSION() 与相关会话/服务器变量；
- information_schema 的 SCHEMATA / TABLES / COLUMNS / STATISTICS /
  REFERENTIAL_CONSTRAINTS + KEY_COLUMN_USAGE / CHECK_CONSTRAINTS / VIEWS /
  ROUTINES / TRIGGERS / EVENTS 查询；
- SHOW CREATE TABLE/VIEW/PROCEDURE/FUNCTION/TRIGGER/EVENT。
"""

from __future__ import annotations

import re
from datetime import UTC

import pymysql.connections
import pymysql.cursors

from modou.db import MysqlParams, quote_ident
from modou.replay.env import unsupported_version_errors
from modou.snapshot.model import (
    CheckDef,
    ColumnDef,
    DatabaseInventory,
    ForeignKeyDef,
    IndexDef,
    IndexPart,
    ObjectDef,
    Snapshot,
    SnapshotMeta,
    TableDef,
)

# 剥离 SHOW CREATE 输出中的 DEFINER 子句：灌入影子库后服务器会重写 DEFINER 为灌入者，
# 不剥离将产生假差异（HANDOFF 已知坑）。
_DEFINER_PATTERN = re.compile(r"DEFINER\s*=\s*`[^`]+`@`[^`]+`\s*", re.IGNORECASE)

# CREATE_OPTIONS 中的 auto_increment=N 是运行时计数器，非结构，剥离后存储
_AUTO_INCREMENT_OPTION_PATTERN = re.compile(r"\bauto_increment=\d+\s*", re.IGNORECASE)


def read_meta(conn: pymysql.connections.Connection) -> SnapshotMeta:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT VERSION(), @@version_comment, @@character_set_server, "
            "@@collation_server, @@lower_case_table_names, @@sql_mode"
        )
        version, version_comment, charset, collation, lctn, sql_mode = cursor.fetchone()
    return SnapshotMeta(
        server_version=str(version),
        version_comment=str(version_comment),
        character_set_server=str(charset),
        collation_server=str(collation),
        lower_case_table_names=int(lctn),
        sql_mode=str(sql_mode),
    )


def normalize_ddl(ddl: str) -> str:
    """归一化对象 DDL：剥离 DEFINER 子句。"""
    return _DEFINER_PATTERN.sub("", ddl.strip())


def _strip_runtime_options(create_options: str) -> str:
    return _AUTO_INCREMENT_OPTION_PATTERN.sub("", create_options or "").strip()


def read_database_inventory(conn: pymysql.connections.Connection, db_name: str) -> DatabaseInventory:
    """读取单个库的完整结构清单。

    权限不足时直接抛出 MySQL 错误（fail-loud）：静默跳过对象会让后续 diff
    产出「漏执行」假结论，比采集失败危害更大。库级 warnings 仅承载非致命提示。
    """
    inventory = DatabaseInventory(name=db_name, charset="", collation="")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT default_character_set_name, default_collation_name "
            "FROM information_schema.SCHEMATA WHERE schema_name = %s",
            (db_name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"database not found: {db_name}")
        inventory.charset, inventory.collation = str(row[0]), str(row[1])

        cursor.execute(
            "SELECT table_name, engine, table_collation, table_comment, create_options "
            "FROM information_schema.TABLES WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (db_name,),
        )
        table_rows = cursor.fetchall()
        for table_name, engine, table_collation, table_comment, create_options in table_rows:
            inventory.tables[str(table_name)] = TableDef(
                name=str(table_name),
                engine=str(engine or ""),
                collation=str(table_collation or ""),
                comment=str(table_comment or ""),
                create_options=_strip_runtime_options(str(create_options or "")),
                ddl=_read_table_ddl(cursor, db_name, str(table_name)),
            )

        for table_def in inventory.tables.values():
            table_def.columns = _read_columns(cursor, db_name, table_def.name)
            table_def.indexes = _read_indexes(cursor, db_name, table_def.name)
            table_def.foreign_keys = _read_foreign_keys(cursor, db_name, table_def.name)
            table_def.check_constraints = _read_check_constraints(cursor, db_name, table_def.name)

        cursor.execute(
            "SELECT table_name FROM information_schema.VIEWS WHERE table_schema = %s ORDER BY table_name",
            (db_name,),
        )
        for (view_name,) in cursor.fetchall():
            inventory.views[str(view_name)] = ObjectDef(
                name=str(view_name), ddl=normalize_ddl(_show_create(cursor, "VIEW", db_name, str(view_name)))
            )

        cursor.execute(
            "SELECT routine_name, routine_type FROM information_schema.ROUTINES "
            "WHERE routine_schema = %s AND routine_type IN ('PROCEDURE', 'FUNCTION') "
            "ORDER BY routine_type, routine_name",
            (db_name,),
        )
        for routine_name, routine_type in cursor.fetchall():
            target = inventory.procedures if str(routine_type) == "PROCEDURE" else inventory.functions
            kind = "PROCEDURE" if str(routine_type) == "PROCEDURE" else "FUNCTION"
            target[str(routine_name)] = ObjectDef(
                name=str(routine_name), ddl=normalize_ddl(_show_create(cursor, kind, db_name, str(routine_name)))
            )

        cursor.execute(
            "SELECT trigger_name FROM information_schema.TRIGGERS WHERE trigger_schema = %s ORDER BY trigger_name",
            (db_name,),
        )
        for (trigger_name,) in cursor.fetchall():
            inventory.triggers[str(trigger_name)] = ObjectDef(
                name=str(trigger_name), ddl=normalize_ddl(_show_create(cursor, "TRIGGER", db_name, str(trigger_name)))
            )

        cursor.execute(
            "SELECT event_name FROM information_schema.EVENTS WHERE event_schema = %s ORDER BY event_name",
            (db_name,),
        )
        for (event_name,) in cursor.fetchall():
            inventory.events[str(event_name)] = ObjectDef(
                name=str(event_name), ddl=normalize_ddl(_show_create(cursor, "EVENT", db_name, str(event_name)))
            )
    return inventory


def capture_snapshot(params: MysqlParams, database_names: list[str]) -> Snapshot:
    """对目标实例的指定库清单做一次只读采集。

    版本低于采集支持地板（8.0）时显式拒绝：内省查询依赖 8.0+ 专有元数据，
    老版本只会在查询期报 1054 一类晦涩错误。
    """
    conn = params.connect()
    try:
        meta = read_meta(conn)
        version_errors = unsupported_version_errors(meta)
        if version_errors:
            raise ValueError("; ".join(version_errors))
        snapshot = Snapshot(
            format_version=1,
            tool_version=_tool_version(),
            captured_at=_utc_now(),
            meta=meta,
        )
        for db_name in database_names:
            snapshot.databases[db_name] = read_database_inventory(conn, db_name)
        return snapshot
    finally:
        conn.close()


def _read_table_ddl(cursor: pymysql.cursors.Cursor, db_name: str, table_name: str) -> str:
    cursor.execute(f"SHOW CREATE TABLE {quote_ident(db_name)}.{quote_ident(table_name)}")
    return str(cursor.fetchone()[1])


def _read_columns(cursor: pymysql.cursors.Cursor, db_name: str, table_name: str) -> list[ColumnDef]:
    cursor.execute(
        "SELECT column_name, ordinal_position, column_type, is_nullable, column_default, "
        "extra, collation_name, column_comment, generation_expression "
        "FROM information_schema.COLUMNS WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position",
        (db_name, table_name),
    )
    return [
        ColumnDef(
            name=str(name),
            ordinal=int(ordinal),
            column_type=str(column_type),
            nullable=is_nullable == "YES",
            default=None if default is None else str(default),
            extra=str(extra or ""),
            collation=None if collation is None else str(collation),
            comment=str(comment or ""),
            generation_expression=str(generation or ""),
        )
        for name, ordinal, column_type, is_nullable, default, extra, collation, comment, generation in cursor.fetchall()
    ]


def _read_indexes(cursor: pymysql.cursors.Cursor, db_name: str, table_name: str) -> list[IndexDef]:
    cursor.execute(
        "SELECT index_name, non_unique, seq_in_index, column_name, collation, sub_part, expression "
        "FROM information_schema.STATISTICS WHERE table_schema = %s AND table_name = %s "
        "ORDER BY index_name, seq_in_index",
        (db_name, table_name),
    )
    indexes: dict[str, IndexDef] = {}
    for index_name, non_unique, seq, column, direction, sub_part, expression in cursor.fetchall():
        index = indexes.setdefault(str(index_name), IndexDef(name=str(index_name), unique=non_unique == 0))
        index.parts.append(
            IndexPart(
                seq=int(seq),
                column=str(column),
                sub_part=None if sub_part is None else int(sub_part),
                direction=str(direction or ""),
                expression=None if expression is None else str(expression),
            )
        )
    return [indexes[name] for name in sorted(indexes)]


def _read_foreign_keys(cursor: pymysql.cursors.Cursor, db_name: str, table_name: str) -> list[ForeignKeyDef]:
    cursor.execute(
        "SELECT rc.constraint_name, rc.update_rule, rc.delete_rule, "
        "kcu.column_name, kcu.referenced_table_name, kcu.referenced_column_name, kcu.ordinal_position "
        "FROM information_schema.referential_constraints rc "
        "JOIN information_schema.key_column_usage kcu "
        "ON rc.constraint_name = kcu.constraint_name AND rc.constraint_schema = kcu.constraint_schema "
        "AND kcu.table_name = rc.table_name "
        # KEY_COLUMN_USAGE 对同库任意表的唯一索引也产出同名行（索引名仅表内唯一），
        # 缺 table_name 关联会把他表列拼进本表 FK（referenced 列为 NULL 损坏快照）
        "AND kcu.referenced_table_name IS NOT NULL "
        "WHERE rc.constraint_schema = %s AND rc.table_name = %s "
        "ORDER BY rc.constraint_name, kcu.ordinal_position",
        (db_name, table_name),
    )
    foreign_keys: dict[str, ForeignKeyDef] = {}
    for constraint_name, update_rule, delete_rule, column, ref_table, ref_column, _ordinal in cursor.fetchall():
        fk = foreign_keys.setdefault(
            str(constraint_name),
            ForeignKeyDef(
                name=str(constraint_name),
                columns=[],
                ref_table=str(ref_table),
                ref_columns=[],
                on_update=str(update_rule),
                on_delete=str(delete_rule),
            ),
        )
        fk.columns.append(str(column))
        fk.ref_columns.append(str(ref_column))
    return [foreign_keys[name] for name in sorted(foreign_keys)]


def _read_check_constraints(cursor: pymysql.cursors.Cursor, db_name: str, table_name: str) -> list[CheckDef]:
    # enforced 取自 TABLE_CONSTRAINTS（8.4 的 CHECK_CONSTRAINTS 无 ENFORCED 列，该列两代都有）
    cursor.execute(
        "SELECT cc.constraint_name, cc.check_clause, tc.enforced "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.check_constraints cc "
        "ON tc.constraint_name = cc.constraint_name AND tc.constraint_schema = cc.constraint_schema "
        "WHERE tc.constraint_schema = %s AND tc.table_name = %s AND tc.constraint_type = 'CHECK' "
        "ORDER BY cc.constraint_name",
        (db_name, table_name),
    )
    return [
        CheckDef(name=str(name), expression=str(clause), enforced=str(enforced))
        for name, clause, enforced in cursor.fetchall()
    ]


# SHOW CREATE 各对象的结果集列名不同（TRIGGER/PROCEDURE/EVENT 的第 2 列是 sql_mode
# 而非 DDL），必须按列名取，禁止按位置取。
_DDL_COLUMN_BY_KIND: dict[str, str] = {
    "TABLE": "Create Table",
    "VIEW": "Create View",
    "TRIGGER": "SQL Original Statement",
    "PROCEDURE": "Create Procedure",
    "FUNCTION": "Create Function",
    "EVENT": "Create Event",
}


def _show_create(cursor: pymysql.cursors.Cursor, kind: str, db_name: str, object_name: str) -> str:
    column = _DDL_COLUMN_BY_KIND[kind]
    dict_cursor = cursor.connection.cursor(pymysql.cursors.DictCursor)
    try:
        dict_cursor.execute(f"SHOW CREATE {kind} {quote_ident(db_name)}.{quote_ident(object_name)}")
        row = dict_cursor.fetchone()
    finally:
        dict_cursor.close()
    if row is None or column not in row:
        raise ValueError(f"SHOW CREATE {kind} returned no {column!r} for {db_name}.{object_name}")
    return str(row[column])


def _tool_version() -> str:
    from modou import __version__

    return __version__


def _utc_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
