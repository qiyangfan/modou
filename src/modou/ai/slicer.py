"""schema 切片器：按语句触达裁剪元数据上下文（spec「上下文按触达裁剪」）。

口径：
- 触达面 = 语句引用的表（sqlglot AST，CTE 别名排除——它以 exp.Table 形态出现，
  HANDOFF 已实证）+ USE 语句建立的库上下文（对后续未限定语句生效）；
- 解析不了的语句不贡献触达面（usable=False 由调用方决定是否兜底），不猜测；
- 输出与快照求交：切片里只有真实存在的库表（AST 里的索引名等伪表自然消解）；
- 预算约束的是「补充上下文」，触达表必含（丢触达表等于让 AI 瞎评）——单条目
  永不截半，超预算整条丢弃。预算按字符计（max_chars）：内核零 tokenizer 依赖，
  字符预算是 token 预算的确定性工程近似（中文/SQL 混合文本约 1 char ≈ 0.5~1 token）。
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
    """语句集的触达面：库名（含 USE 上下文）与 (库, 表) 引用。"""

    databases: set[str] = field(default_factory=set)
    tables: set[tuple[str, str]] = field(default_factory=set)
    usable: bool = True


def touched_objects(sql: str, *, default_database: str | None = None) -> TouchedContext:
    """单条语句的触达面：不可解析时 usable=False 且不贡献任何触达。"""
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
    """按触达裁剪 schema 元数据：触达表在前（必含），同库其余表按预算补充。

    返回条目形如 {"database", "table", "engine", "columns", "indexes"}
    （与 optimize/advisor.build_schema_summary 同形，消费方提示词无需分叉）。
    """
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
            # USE 只对后续未限定语句生效（与回放切分器语义一致）
            current_default = sorted(touched.databases)[0] if len(touched.databases) == 1 else current_default

    # 与快照求交：只有真实存在的库表进上下文
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
                continue  # 无关库整库裁剪
            entry = _table_entry(db_name, table_name, snapshot)
            used += len(json.dumps(entry, ensure_ascii=False))
            if used > max_chars:
                break  # 预算耗尽：补充上下文整条丢弃，已排入的触达条目不动
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
