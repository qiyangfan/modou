"""按语句触达范围裁剪 schema 上下文。

只纳入快照中存在的表；触达表必含，字符预算只限制补充的同库表；不可解析的语句不贡献触达面。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import sqlglot
import sqlglot.errors
import sqlglot.expressions as exp

from modou.snapshot.model import Snapshot

DEFAULT_SCHEMA_BUDGET_CHARS = 24000


@dataclass
class TouchedContext:
    """语句触达的库（含 USE）与 (库, 表) 引用。"""

    databases: set[str] = field(default_factory=set)
    tables: set[tuple[str, str]] = field(default_factory=set)
    usable: bool = True


def touched_objects(sql: str, *, default_database: str | None = None) -> TouchedContext:
    """单条语句的触达面；不可解析时 usable=False。"""
    try:
        tree = sqlglot.parse_one(sql, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError, ValueError):
        return TouchedContext(usable=False)
    if tree is None:
        return TouchedContext()
    touched = TouchedContext()
    use_node = tree.find(exp.Use)
    if use_node is not None:
        identifier = use_node.find(exp.Identifier)
        if identifier is not None and identifier.name:
            touched.databases.add(identifier.name)
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name or name in cte_names:
            continue
        db = table.db or default_database
        if db:
            touched.tables.add((db, name))
    return touched


def slice_schema(
    statements: list[str],
    snapshot: Snapshot,
    *,
    default_database: str | None = None,
    max_chars: int = DEFAULT_SCHEMA_BUDGET_CHARS,
) -> list[dict]:
    """按触达范围返回 schema 条目；触达表必含，其他同库表受字符预算限制。"""
    all_touched = TouchedContext()
    current_default = default_database
    for statement in statements:
        if not statement.strip():
            continue
        touched = touched_objects(statement, default_database=current_default)
        all_touched.databases |= touched.databases
        all_touched.tables |= touched.tables
        all_touched.usable = all_touched.usable and touched.usable
        if touched.databases:
            # USE 只作用于后续未限定库名的语句。
            current_default = sorted(touched.databases)[0] if len(touched.databases) == 1 else current_default

    # 只保留快照中真实存在的库表
    resolved: set[tuple[str, str]] = set()
    for db_name, table_name in all_touched.tables:
        inventory = snapshot.databases.get(db_name)
        if inventory is not None and table_name in inventory.tables:
            resolved.add((db_name, table_name))
    if not resolved:
        return []

    entry_by_key = {key: _table_entry(key[0], key[1], snapshot) for key in resolved}
    ordered: list[dict] = [entry_by_key[key] for key in sorted(resolved)]
    used = sum(len(json.dumps(entry, ensure_ascii=False)) for entry in ordered)

    touched_dbs = {db for db, _ in resolved}
    for db_name in sorted(snapshot.databases):
        for table_name in sorted(snapshot.databases[db_name].tables):
            if (db_name, table_name) in resolved:
                continue
            if db_name not in touched_dbs:
                continue  # 跳过整个未触达的库
            entry = _table_entry(db_name, table_name, snapshot)
            used += len(json.dumps(entry, ensure_ascii=False))
            if used > max_chars:
                break  # 预算耗尽后不再补充；已排入的触达条目保留
            ordered.append(entry)
        else:
            continue
        break
    return ordered


def _table_entry(db_name: str, table_name: str, snapshot: Snapshot) -> dict:
    table = snapshot.databases[db_name].tables[table_name]
    return {
        "database": db_name,
        "table": table_name,
        "engine": table.engine,
        "columns": [f"{col.name} {col.column_type}{'' if col.nullable else ' NOT NULL'}" for col in table.columns],
        "indexes": [
            f"{index.name}{' UNIQUE' if index.unique else ''} ("
            + ", ".join(part.column for part in index.parts if part.column)
            + ")"
            for index in table.indexes
        ],
    }
