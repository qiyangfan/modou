"""EXPLAIN 采集器与统计刷新的单元测试（解析层，不依赖容器）。"""

from __future__ import annotations

import json

from modou.optimize.explain import ExplainPlan, parse_explain_json, parse_explain_tree_actual_ms


class TestParseExplainJson:
    def test_simple_query_cost_and_rows(self) -> None:
        plan_json = {
            "query_block": {
                "select_id": 1,
                "cost_info": {"query_cost": "1205.35"},
                "table": {
                    "table_name": "orders",
                    "access_type": "ALL",
                    "rows": "1000",
                    "filtered": "100.00",
                },
            }
        }
        plan = parse_explain_json(json.dumps(plan_json))
        assert isinstance(plan, ExplainPlan)
        assert plan.query_cost == 1205.35
        assert plan.table_accesses == [{"table": "orders", "rows": 1000, "access_type": "ALL"}]

    def test_nested_blocks_collected(self) -> None:
        plan_json = {
            "query_block": {
                "select_id": 1,
                "cost_info": {"query_cost": "42.00"},
                "nested_loop": [
                    {
                        "table": {
                            "table_name": "a",
                            "access_type": "ref",
                            "rows": "10",
                            "cost_info": {"read_cost": "12.0"},
                        }
                    },
                    {
                        "table": {
                            "table_name": "b",
                            "access_type": "eq_ref",
                            "rows": "1",
                        }
                    },
                ],
            }
        }
        plan = parse_explain_json(json.dumps(plan_json))
        assert plan.query_cost == 42.0
        assert [t["table"] for t in plan.table_accesses] == ["a", "b"]

    def test_missing_cost_info_degrades_to_none(self) -> None:
        """query_cost 未入官方手册（事实字段）：缺失时容错降级为 None，不抛异常。"""
        plan = parse_explain_json(json.dumps({"query_block": {"select_id": 1, "table": {"table_name": "t"}}}))
        assert plan.query_cost is None
        assert plan.table_accesses

    def test_invalid_json_raises_value_error(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            parse_explain_json("not json")


class TestParseExplainTree:
    def test_top_node_actual_time(self) -> None:
        tree = (
            "-> Limit: 10 row(s)  (actual time=0.050..123.456 rows=10 loops=1)\n"
            "    -> Table scan on t  (cost=100 rows=1000) (actual time=0.040..100.2 rows=5000 loops=1)\n"
        )
        assert parse_explain_tree_actual_ms(tree) == 123.456

    def test_no_actual_marker_returns_none(self) -> None:
        assert parse_explain_tree_actual_ms("-> Table scan on t (cost=1) (never executed)") is None


class TestRefreshStatisticsSql:
    def test_analyze_table_sql(self) -> None:
        from modou.optimize.explain import build_analyze_sql

        assert build_analyze_sql("shop", "orders") == "ANALYZE TABLE `shop`.`orders`"
