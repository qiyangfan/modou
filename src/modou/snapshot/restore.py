"""将快照还原为影子库基线。

先建库和表，再跨库重试视图、触发器等对象；样本在触发器创建前灌入。
"""

from __future__ import annotations

import contextlib

import pymysql.connections
import pymysql.err

from modou.db import quote_ident
from modou.snapshot.model import DatabaseInventory, ObjectDef, Snapshot, TableDef
from modou.snapshot.sample import restore_value

# 依赖重试轮数随对象数增长，避免无限重试。
_MAX_RETRY_ROUNDS_FACTOR = 2

# 控制 executemany 单批行数，避免超过 max_allowed_packet。
_INSERT_BATCH_ROWS = 500


def restore_snapshot(
    conn: pymysql.connections.Connection,
    snapshot: Snapshot,
    *,
    database_filter: set[str] | None = None,
    include_data: bool = False,
) -> None:
    """灌入选定数据库（过滤器为 None 时使用全部库），可选写入表样本。"""
    inventories = [
        inventory
        for name, inventory in snapshot.databases.items()
        if database_filter is None or name in database_filter
    ]
    with conn.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        try:
            for inventory in inventories:
                _create_database(cursor, inventory)
            for inventory in inventories:
                conn.select_db(inventory.name)
                for table in inventory.tables.values():
                    cursor.execute(table.ddl)
            if include_data:
                # 样本必须先于触发器灌入，避免被触发器改写或拒绝。
                for inventory in inventories:
                    conn.select_db(inventory.name)
                    for table in inventory.tables.values():
                        _restore_table_sample(conn, cursor, inventory.name, table)
            # 跨库对象共用一个重试池，以等待其他库中的依赖。
            entries = [(inv.name, obj) for inv in inventories for obj in _dependency_objects(inv)]
            _restore_dependency_pool(conn, cursor, entries)
        finally:
            # 恢复失败时保留原始异常。
            with contextlib.suppress(pymysql.err.MySQLError):
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


def _restore_table_sample(
    conn: pymysql.connections.Connection,
    cursor: pymysql.cursors.Cursor,
    db_name: str,
    table: TableDef,
) -> None:
    """灌入单表采样数据：按列类型还原 JSON 值，分批 executemany。"""
    sample = table.sample
    if sample is None or not sample.rows:
        return
    types_by_name = {col.name: col.column_type for col in table.columns}
    placeholders = ", ".join(["%s"] * len(sample.columns))
    column_list = ", ".join(quote_ident(name) for name in sample.columns)
    target = f"{quote_ident(db_name)}.{quote_ident(table.name)}"
    sql = f"INSERT INTO {target} ({column_list}) VALUES ({placeholders})"
    for start in range(0, len(sample.rows), _INSERT_BATCH_ROWS):
        batch = []
        for row in sample.rows[start : start + _INSERT_BATCH_ROWS]:
            try:
                values = tuple(
                    restore_value(value, types_by_name.get(name, ""))
                    for name, value in zip(sample.columns, row, strict=True)
                )
            except ValueError as exc:
                # 列数与行值不符时拒绝，避免静默丢数据。
                raise ValueError(
                    f"sample row width mismatch in {db_name}.{table.name} "
                    f"(columns={len(sample.columns)}, row has {len(row)} values)"
                ) from exc
            batch.append(values)
        cursor.executemany(sql, batch)


def _create_database(cursor: pymysql.cursors.Cursor, inventory: DatabaseInventory) -> None:
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS {quote_ident(inventory.name)} "
        f"CHARACTER SET {quote_ident(inventory.charset)} COLLATE {quote_ident(inventory.collation)}"
    )


def _dependency_objects(inventory: DatabaseInventory) -> list[ObjectDef]:
    return [
        *inventory.views.values(),
        *inventory.triggers.values(),
        *inventory.procedures.values(),
        *inventory.functions.values(),
        *inventory.events.values(),
    ]


def _restore_dependency_pool(
    conn: pymysql.connections.Connection,
    cursor: pymysql.cursors.Cursor,
    entries: list[tuple[str, ObjectDef]],
) -> None:
    """非表对象统一入池：逐轮尝试，失败的留到下一轮（依赖方可能已在同轮更早创建）。"""
    max_rounds = max(2, len(entries) * _MAX_RETRY_ROUNDS_FACTOR)
    last_error: pymysql.err.MySQLError | None = None
    pool = entries
    for _ in range(max_rounds):
        if not pool:
            return
        remaining: list[tuple[str, ObjectDef]] = []
        for db_name, obj in pool:
            try:
                conn.select_db(db_name)  # 对象 DDL 不含库名前缀，需先切换库。
                cursor.execute(obj.ddl)
            except pymysql.err.MySQLError as exc:
                remaining.append((db_name, obj))
                last_error = exc
        pool = remaining
    # 仍有对象未创建时抛出最后的数据库异常。
    stuck_dbs = sorted({db_name for db_name, _ in pool})
    raise RuntimeError(
        f"restore failed: {len(pool)} object(s) in database(s) {stuck_dbs} could not be created; "
        f"last error: {last_error}"
    ) from last_error
