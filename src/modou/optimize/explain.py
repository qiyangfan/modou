"""采集 EXPLAIN 计划并刷新统计，供影子库优化实证使用。

候选判定使用 JSON 计划中的估计代价；ANALYZE 实测耗时只作参考。缺少代价时记为不可得。
"""

from __future__ import annotations

import contextlib
import json
import re

import pymysql.connections

from modou.db import quote_ident

# EXPLAIN JSON 中可能包含嵌套查询块的键，用于递归收集所有表访问
_NESTED_BLOCK_KEYS = (
    "nested_loop",
    "grouping_operation",
    "ordering_operation",
    "materialized_from_subquery",
    "duplicated_from_subquery",
    "attached_subqueries",
    "cacheable_subquery",
    "query_block",
    "query_specifications",
    "table",
)


class ExplainPlan:
    """EXPLAIN FORMAT=JSON 的解析结果；代价缺失时 query_cost 为 None。"""

    def __init__(self, query_cost: float | None, table_accesses: list[dict]) -> None:
        self.query_cost = query_cost
        self.table_accesses = table_accesses


def explain_json(conn: pymysql.connections.Connection, sql: str) -> ExplainPlan:
    """执行 EXPLAIN FORMAT=JSON 并解析顶层代价与访问表行数估计。"""
    with conn.cursor() as cursor:
        cursor.execute("EXPLAIN FORMAT=JSON " + sql)
        row = cursor.fetchone()
    if row is None or row[0] is None:
        raise ValueError("EXPLAIN FORMAT=JSON returned no output")
    return parse_explain_json(str(row[0]))


def explain_analyze_tree(conn: pymysql.connections.Connection, sql: str) -> str:
    """执行 EXPLAIN ANALYZE 并返回 TREE 文本；失败由调用方降级。"""
    with conn.cursor() as cursor:
        cursor.execute("EXPLAIN ANALYZE " + sql)
        return "\n".join(str(row[0]) for row in cursor.fetchall())


def parse_explain_json(text: str) -> ExplainPlan:
    """提取顶层代价与表访问信息；rows 转整数，无法解析时记为 0。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid EXPLAIN JSON output: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid EXPLAIN JSON structure")
    cost_info = data.get("query_block", {}).get("cost_info", {}) if isinstance(data.get("query_block"), dict) else {}
    raw_cost = cost_info.get("query_cost")
    query_cost: float | None
    try:
        query_cost = None if raw_cost is None else float(raw_cost)
    except (TypeError, ValueError):
        query_cost = None
    accesses: list[dict] = []
    _collect_tables(data.get("query_block", {}), accesses)
    return ExplainPlan(query_cost=query_cost, table_accesses=accesses)


def _collect_tables(node: object, out: list[dict]) -> None:
    if not isinstance(node, dict):
        return
    if "table_name" in node:
        rows_raw = node.get("rows")
        try:
            rows = 0 if rows_raw is None else int(rows_raw)
        except (TypeError, ValueError):
            rows = 0
        out.append(
            {
                "table": str(node.get("table_name", "?")),
                "rows": rows,
                "access_type": str(node.get("access_type", "")),
            }
        )
    for key in _NESTED_BLOCK_KEYS:
        child = node.get(key)
        if isinstance(child, list):
            for item in child:
                _collect_tables(item, out)
        elif child is not None:
            _collect_tables(child, out)


_ACTUAL_TIME_PATTERN = re.compile(r"actual time=(\d+(?:\.\d+)?)\.\.(\d+(?:\.\d+)?)")


def parse_explain_tree_actual_ms(tree_text: str) -> float | None:
    """从 TREE 输出取顶层节点的 actual time 终值（毫秒）；无实测标记返回 None。"""
    match = _ACTUAL_TIME_PATTERN.search(tree_text)
    if match is None:
        return None
    return float(match.group(2))


def build_analyze_sql(database: str, table: str) -> str:
    return f"ANALYZE TABLE {quote_ident(database)}.{quote_ident(table)}"


def refresh_statistics(
    conn: pymysql.connections.Connection,
    tables: list[tuple[str, str]],
) -> None:
    """逐个执行 ANALYZE TABLE，并尝试调大统计采样页数以稳定基数估计。"""
    with conn.cursor() as cursor:
        # 无 GLOBAL 权限时跳过采样页调整
        with contextlib.suppress(pymysql.err.MySQLError):
            cursor.execute("SET GLOBAL innodb_stats_persistent_sample_pages = 128")
        for database, table in tables:
            cursor.execute(build_analyze_sql(database, table))
            cursor.fetchall()  # ANALYZE 返回结果集，需读空才算完成
