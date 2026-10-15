"""执行计划采集与统计刷新：影子库实证的判定数据源（v0.2 design §2）。

判定口径（2026-10 调研，出处见 change design.md）：
- 判定指标 = EXPLAIN FORMAT=JSON 顶层 query_block.cost_info.query_cost（估计代价）
  与各访问表的 rows 估计；EXPLAIN ANALYZE（TREE，真实执行）的实测耗时仅作参考
  信息，不参与判定；
- 两个已核实事实：EXPLAIN ANALYZE 至 8.4 仍不支持 FORMAT=JSON（ERROR 1235）；
  query_cost 字段官方手册未文档化（源码行为 + 社区考据）——解析必须容错降级；
- InnoDB 统计为随机采样（random dives），ADD INDEX 无条件刷新该表索引统计：
  基线与复测两侧各自显式 ANALYZE TABLE 拉平口径，是本模块调用方的固定流程。
"""

from __future__ import annotations

import contextlib
import json
import re

import pymysql.connections

from modou.db import quote_ident

# 顶层代价（query_block.cost_info.query_cost）；字段缺失（未文档化/版本差异）容错为 None
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
    """一次 EXPLAIN FORMAT=JSON 的提取结果（代价缺失时 query_cost=None）。"""

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
    """执行 EXPLAIN ANALYZE 返回 TREE 文本（实测耗时参考信息）；不支持/失败由调用方降级。"""
    with conn.cursor() as cursor:
        cursor.execute("EXPLAIN ANALYZE " + sql)
        return "\n".join(str(row[0]) for row in cursor.fetchall())


def parse_explain_json(text: str) -> ExplainPlan:
    """解析 EXPLAIN JSON：顶层代价 + 递归收集访问表（table_name/rows/access_type）。

    rows 在 JSON 中可能是字符串（MySQL 8 行为）：统一转 int；转不了按 0 记。
    """
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
    """对给定 (库, 表) 清单逐个 ANALYZE TABLE（同步前台重算，拉平统计口径）。

    采样页参数（innodb_stats_persistent_sample_pages）是 GLOBAL 变量：尝试调大以
    换取 cardinality 估计稳定（默认 20 → 128）；无权限时降级跳过（仅影响稳定性，
    不影响判定流程本身）。
    """
    with conn.cursor() as cursor:
        # 无 GLOBAL 权限时降级跳过（仅影响统计稳定性，不影响判定流程；风险已在报告声明）
        with contextlib.suppress(pymysql.err.MySQLError):
            cursor.execute("SET GLOBAL innodb_stats_persistent_sample_pages = 128")
        for database, table in tables:
            cursor.execute(build_analyze_sql(database, table))
            cursor.fetchall()  # ANALYZE 返回结果集（Msg_text），耗尽后才算完成
