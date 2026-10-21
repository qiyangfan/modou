"""巡检未用、低用和冗余索引，使用 performance_schema 计数与服务器 uptime。

计数包含索引维护写入；统计可能被重启或 DDL 重置；唯一索引和外键依赖索引不判为未用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymysql.connections

from modou.db import quote_ident
from modou.optimize.sideeffects import (
    find_redundant_pairs,
    fk_required_index_names,
    index_views_from_table,
)
from modou.snapshot.model import DatabaseInventory

STATUS_CONFIRMED_UNUSED = "confirmed_unused"
STATUS_LOW_USE = "low_use"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_EXCLUDED_UNIQUE = "excluded_unique"
STATUS_EXCLUDED_FK = "excluded_fk"

STATUS_LABELS: dict[str, str] = {
    STATUS_CONFIRMED_UNUSED: "确认未用",
    STATUS_LOW_USE: "疑似低用",
    STATUS_INSUFFICIENT_DATA: "数据不足",
    STATUS_EXCLUDED_UNIQUE: "排除（唯一性语义）",
    STATUS_EXCLUDED_FK: "排除（外键依赖）",
}

# 默认观察 7 天，可按业务周期调大
DEFAULT_OBSERVE_DAYS = 7


class PerformanceSchemaDisabledError(Exception):
    """performance_schema 被关闭时明确报错，避免空结论误导。"""


@dataclass
class IndexUsage:
    database: str
    table: str
    index_name: str
    columns: list[str]
    status: str
    count_star: int = 0
    daily_average: float | None = None
    table_share_pct: float | None = None
    drop_statement: str | None = None
    note: str = ""


@dataclass
class RedundantIndex:
    database: str
    table: str
    redundant_index: str
    dominant_index: str
    case: str
    drop_statement: str
    fk_protected: bool = False


@dataclass
class UnusedIndexesReport:
    uptime_seconds: int | None = None
    observe_days: int = DEFAULT_OBSERVE_DAYS
    usages: list[IndexUsage] = field(default_factory=list)
    redundancies: list[RedundantIndex] = field(default_factory=list)

    def by_status(self, status: str) -> list[IndexUsage]:
        return [u for u in self.usages if u.status == status]


def read_index_io_counts(conn: pymysql.connections.Connection, db_name: str) -> dict[tuple[str, str], int]:
    """读 (表, 索引) → COUNT_STAR；INDEX_NAME=NULL（全表扫描）与 PRIMARY 行不取。"""
    with conn.cursor() as cursor:
        cursor.execute("SELECT @@performance_schema")
        row = cursor.fetchone()
        if row is None or int(row[0]) != 1:
            raise PerformanceSchemaDisabledError(
                "performance_schema is disabled on the target server; "
                "index usage statistics are unavailable (enable it and restart)"
            )
        cursor.execute(
            "SELECT OBJECT_NAME, INDEX_NAME, COUNT_STAR "
            "FROM performance_schema.table_io_waits_summary_by_index_usage "
            "WHERE OBJECT_SCHEMA = %s AND INDEX_NAME IS NOT NULL AND INDEX_NAME <> 'PRIMARY'",
            (db_name,),
        )
        return {(str(table), str(index)): int(count) for table, index, count in cursor.fetchall()}


def read_uptime(conn: pymysql.connections.Connection) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SHOW GLOBAL STATUS LIKE 'Uptime'")
        row = cursor.fetchone()
    if row is None:
        # 缺行属环境异常，映射 ValueError（退出码 2）
        raise ValueError("cannot read server uptime (SHOW GLOBAL STATUS returned no row)")
    return int(row[1])


def judge_unused_indexes(
    inventory: DatabaseInventory,
    counts: dict[tuple[str, str], int],
    *,
    uptime_seconds: int,
    observe_days: int = DEFAULT_OBSERVE_DAYS,
) -> list[IndexUsage]:
    """分层判定（结构来自快照/内省，计数来自 performance_schema）。"""
    usages: list[IndexUsage] = []
    observe_window = observe_days * 86400
    for table in inventory.tables.values():
        fk_protected = fk_required_index_names(table)
        table_total_io = sum(count for (t_name, _), count in counts.items() if t_name == table.name)
        for index in table.indexes:
            if index.name == "PRIMARY":
                continue
            columns = [part.column for part in index.parts if part.column]
            if index.unique:
                usages.append(
                    IndexUsage(
                        database=inventory.name,
                        table=table.name,
                        index_name=index.name,
                        columns=columns,
                        status=STATUS_EXCLUDED_UNIQUE,
                        note="唯一索引承载唯一性/约束语义，不做未用判定（sys 同口径）",
                    )
                )
                continue
            if index.name in fk_protected:
                usages.append(
                    IndexUsage(
                        database=inventory.name,
                        table=table.name,
                        index_name=index.name,
                        columns=columns,
                        status=STATUS_EXCLUDED_FK,
                        note="被外键依赖（删除会触发 MySQL 自动重建索引）",
                    )
                )
                continue
            count = counts.get((table.name, index.name), 0)
            if count == 0:
                if uptime_seconds >= observe_window:
                    usages.append(
                        IndexUsage(
                            database=inventory.name,
                            table=table.name,
                            index_name=index.name,
                            columns=columns,
                            status=STATUS_CONFIRMED_UNUSED,
                            count_star=0,
                            drop_statement=_drop_statement(inventory.name, table.name, index.name),
                            note=(
                                f"观察窗 {observe_days} 天（uptime {uptime_seconds}s）内零读取；统计可能被重启/DDL 重置"
                            ),
                        )
                    )
                else:
                    usages.append(
                        IndexUsage(
                            database=inventory.name,
                            table=table.name,
                            index_name=index.name,
                            columns=columns,
                            status=STATUS_INSUFFICIENT_DATA,
                            note=f"uptime {uptime_seconds}s 低于观察窗 {observe_days} 天，零读计数不足以定论",
                        )
                    )
            else:
                daily = count / max(uptime_seconds / 86400, 1e-9)
                share = count / table_total_io * 100 if table_total_io > 0 else None
                usages.append(
                    IndexUsage(
                        database=inventory.name,
                        table=table.name,
                        index_name=index.name,
                        columns=columns,
                        status=STATUS_LOW_USE,
                        count_star=count,
                        daily_average=round(daily, 2),
                        table_share_pct=round(share, 2) if share is not None else None,
                        note="读计数非零：结合业务周期判断是否低价值",
                    )
                )
    return usages


def find_redundant_from_inventory(inventory: DatabaseInventory) -> list[RedundantIndex]:
    """仅用快照元数据判定冗余索引，保留唯一性和外键依赖语义。"""
    redundancies: list[RedundantIndex] = []
    for table in inventory.tables.values():
        existing = sorted(index_views_from_table(table), key=lambda v: v.name)
        fk_protected = fk_required_index_names(table)
        for redundant_view, dominant_view, case in find_redundant_pairs(existing):
            if redundant_view.name == "PRIMARY":
                continue
            redundancies.append(
                RedundantIndex(
                    database=inventory.name,
                    table=table.name,
                    redundant_index=redundant_view.name,
                    dominant_index=dominant_view.name,
                    case=case,
                    drop_statement=_drop_statement(inventory.name, table.name, redundant_view.name),
                    fk_protected=redundant_view.name in fk_protected,
                )
            )
    return redundancies


def collect_from_live(conn: pymysql.connections.Connection, db_name: str) -> tuple[DatabaseInventory, int]:
    """连库模式：内省结构（只读）+ uptime。"""
    from modou.snapshot.introspect import read_database_inventory

    inventory = read_database_inventory(conn, db_name)
    uptime = read_uptime(conn)
    return inventory, uptime


def _drop_statement(db_name: str, table_name: str, index_name: str) -> str:
    return f"ALTER TABLE {quote_ident(db_name)}.{quote_ident(table_name)} DROP INDEX {quote_ident(index_name)};"
