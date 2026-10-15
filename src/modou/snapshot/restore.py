"""快照灌入：把快照还原为影子库基线。

灌入顺序（依赖驱动）：库 → 表 → 其余对象（全部库的视图/触发器/过程/函数/事件合并为
一个跨库收敛池，循环重试直到不再收敛，视图链/视图引用函数/跨库视图依赖均可解）。
全程 SET FOREIGN_KEY_CHECKS=0 以解除表间 FK 建表顺序约束（FK 定义仍随
SHOW CREATE TABLE 原样建立）。灌入执行的是快照内已归一化（剥离 DEFINER）的 DDL
原文——round-trip 保真由此保证。SHOW CREATE 的对象名不带库前缀，执行前先 select_db。
"""

from __future__ import annotations

import contextlib

import pymysql.connections
import pymysql.err

from modou.db import quote_ident
from modou.snapshot.model import DatabaseInventory, ObjectDef, Snapshot, TableDef
from modou.snapshot.sample import restore_value

# 收敛循环上限：每个对象至多需要一次「等依赖先建」，上限取对象数即充分
_MAX_RETRY_ROUNDS_FACTOR = 2

# 采样数据批量 INSERT 的单批行数：平衡单包体积与重放成本（executemany 客户端
# 插值会把一批展开为多行单语句，真实约束是 max_allowed_packet 而非占位符数）
_INSERT_BATCH_ROWS = 500


def restore_snapshot(
    conn: pymysql.connections.Connection,
    snapshot: Snapshot,
    *,
    database_filter: set[str] | None = None,
    include_data: bool = False,
) -> None:
    """将快照灌入目标连接（影子库）。database_filter 为 None 时灌全部库。

    include_data=True 时附带灌入采样数据（format v2 快照）：供 optimize 影子实证
    使用（空表 EXPLAIN 无代价差异）。数据在表结构之后、视图/触发器等对象之前灌入
    （FK 检查已关；采样 INSERT 不得触发触发器）。
    """
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
                # 数据在触发器之前灌入：BEFORE/AFTER INSERT 触发器若已存在，采样 INSERT
                # 会触发它（写审计表/SIGNAL 报错/改写列值），样本集失真；数据只依赖表结构
                for inventory in inventories:
                    conn.select_db(inventory.name)
                    for table in inventory.tables.values():
                        _restore_table_sample(conn, cursor, inventory.name, table)
            # 跨库依赖（db1 视图引用 db2 视图等）必须共用一个收敛池：
            # 按库分池时先灌库的池永远等不到后灌库的对象，必然误报不收敛
            entries = [(inv.name, obj) for inv in inventories for obj in _dependency_objects(inv)]
            _restore_dependency_pool(conn, cursor, entries)
        finally:
            # 失败路径也恢复会话状态；恢复本身失败不得掩盖原始异常
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
                # 列宽不符只可能来自损坏/手改的快照：响亮拒绝而非静默丢值
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
                conn.select_db(db_name)  # SHOW CREATE 的对象名不带库前缀
                cursor.execute(obj.ddl)
            except pymysql.err.MySQLError as exc:
                remaining.append((db_name, obj))
                last_error = exc
        pool = remaining
    # 不再收敛：剩余对象存在真实错误（语法/权限/引用缺失），带上最后一条错误抛出
    stuck_dbs = sorted({db_name for db_name, _ in pool})
    raise RuntimeError(
        f"restore failed: {len(pool)} object(s) in database(s) {stuck_dbs} could not be created; "
        f"last error: {last_error}"
    ) from last_error
