"""快照格式 v2（采样数据）与向后可读（v1 契约不动）的模型层测试。"""

from __future__ import annotations

import json

import pytest

from modou.snapshot.model import (
    FORMAT_VERSION,
    SUPPORTED_FORMAT_VERSIONS,
    ColumnDef,
    DatabaseInventory,
    IndexDef,
    IndexPart,
    Snapshot,
    SnapshotMeta,
    TableDef,
    TableSample,
    snapshot_from_json,
    snapshot_to_json,
)


def _meta() -> SnapshotMeta:
    return SnapshotMeta(
        server_version="8.4.6",
        version_comment="MySQL Community Server - GPL",
        character_set_server="utf8mb4",
        collation_server="utf8mb4_0900_ai_ci",
        lower_case_table_names=0,
        sql_mode="ONLY_FULL_GROUP_BY",
    )


def _table(name: str = "orders", with_sample: bool = False) -> TableDef:
    table = TableDef(
        name=name,
        engine="InnoDB",
        collation="utf8mb4_0900_ai_ci",
        comment="订单",
        create_options="",
        ddl=f"CREATE TABLE `{name}` (id int NOT NULL PRIMARY KEY)",
        columns=[ColumnDef("id", 1, "int", False, None, "", None, "", "")],
        indexes=[
            IndexDef("PRIMARY", True, [IndexPart(1, "id", None, "A", None)]),
        ],
    )
    if with_sample:
        table.sample = TableSample(
            columns=["id"],
            rows=[[1], [2]],
            sampled_rows=2,
            estimated_rows=2,
            method="primary_key_asc",
        )
    return table


def _snapshot(with_sample: bool, version: int = 2) -> Snapshot:
    return Snapshot(
        format_version=version,
        tool_version="0.1.0",
        captured_at="2026-10-15T00:00:00+00:00",
        meta=_meta(),
        databases={
            "shop": DatabaseInventory(
                name="shop",
                charset="utf8mb4",
                collation="utf8mb4_0900_ai_ci",
                tables={"orders": _table(with_sample=with_sample)},
            )
        },
    )


class TestFormatV2RoundTrip:
    def test_current_format_version_is_2(self) -> None:
        # 采样数据是 optimize 车道的前置（空表 EXPLAIN 无代价差异）
        assert FORMAT_VERSION == 2

    def test_v2_with_sample_round_trip_preserves_sample(self) -> None:
        snapshot = _snapshot(with_sample=True)
        restored = snapshot_from_json(snapshot_to_json(snapshot))
        sample = restored.databases["shop"].tables["orders"].sample
        assert sample is not None
        assert sample.columns == ["id"]
        assert sample.rows == [[1], [2]]
        assert sample.sampled_rows == 2
        assert sample.estimated_rows == 2
        assert sample.method == "primary_key_asc"

    def test_v2_without_sample_loads_as_none(self) -> None:
        restored = snapshot_from_json(snapshot_to_json(_snapshot(with_sample=False)))
        assert restored.databases["shop"].tables["orders"].sample is None

    def test_v1_snapshot_still_readable(self) -> None:
        """v1 快照（无 sample 键）必须仍可读：冻结契约的演进方式是向后可读。"""
        v1_text = json.dumps(json.loads(snapshot_to_json(_snapshot(with_sample=False))), ensure_ascii=False)
        raw = json.loads(v1_text)
        raw["format_version"] = 1
        restored = snapshot_from_json(json.dumps(raw, ensure_ascii=False))
        assert restored.format_version == 1
        assert restored.databases["shop"].tables["orders"].sample is None

    def test_unsupported_version_rejected(self) -> None:
        snapshot = _snapshot(with_sample=False, version=99)
        with pytest.raises(ValueError, match="format_version"):
            snapshot_from_json(snapshot_to_json(snapshot))

    def test_supported_versions_declared(self) -> None:
        assert SUPPORTED_FORMAT_VERSIONS == (1, 2)


class TestSampleValueConversion:
    """行值的 JSON 化与还原：采样采集与影子灌入共用同一套转换。"""

    def test_json_safe_values(self) -> None:
        from datetime import date, datetime
        from decimal import Decimal

        from modou.snapshot.sample import json_safe_value

        assert json_safe_value(None) is None
        assert json_safe_value(1) == 1
        assert json_safe_value(1.5) == 1.5
        assert json_safe_value(Decimal("1.25")) == "1.25"
        assert json_safe_value(datetime(2026, 10, 15, 8, 30, 0)) == "2026-10-15T08:30:00"
        assert json_safe_value(date(2026, 10, 15)) == "2026-10-15"
        assert json_safe_value(b"\x00abc") == {"$binary": "00616263"}

    def test_restore_binary_value_decoded(self) -> None:
        from modou.snapshot.sample import restore_value

        assert restore_value({"$binary": "00616263"}, "varbinary(16)") == b"\x00abc"

    def test_restore_temporal_passes_through_as_string(self) -> None:
        from modou.snapshot.sample import restore_value

        # MySQL 接受 'T' 分隔的 datetime 字面量：ISO 字符串直接作为参数传入
        assert restore_value("2026-10-15T08:30:00", "datetime") == "2026-10-15T08:30:00"


class TestSampleSqlBuilder:
    def test_primary_key_asc_sql_is_deterministic(self) -> None:
        from modou.snapshot.sample import build_sample_sql

        table = _table("orders")
        table.columns = [
            ColumnDef("id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("amount", 2, "decimal(10,2)", True, None, "", None, "", ""),
        ]
        sql = build_sample_sql("shop", table, limit=100)
        assert sql == "SELECT `id`, `amount` FROM `shop`.`orders` ORDER BY `id` ASC LIMIT 100"

    def test_composite_primary_key_order(self) -> None:
        from modou.snapshot.sample import build_sample_sql

        table = _table("order_items")
        table.columns = [
            ColumnDef("order_id", 1, "int", False, None, "", None, "", ""),
            ColumnDef("item_id", 2, "int", False, None, "", None, "", ""),
        ]
        table.indexes = [
            IndexDef(
                "PRIMARY",
                True,
                [IndexPart(1, "order_id", None, "A", None), IndexPart(2, "item_id", None, "A", None)],
            )
        ]
        sql = build_sample_sql("shop", table, limit=10)
        assert "ORDER BY `order_id` ASC, `item_id` ASC" in sql

    def test_table_without_primary_key_raises(self) -> None:
        from modou.snapshot.sample import NoPrimaryKeyError, build_sample_sql

        table = _table("logs")
        table.indexes = []
        with pytest.raises(NoPrimaryKeyError):
            build_sample_sql("shop", table, limit=10)

    def test_expression_index_parts_excluded_from_order(self) -> None:
        from modou.snapshot.sample import NoPrimaryKeyError, build_sample_sql

        table = _table("t")
        table.columns = [ColumnDef("id", 1, "int", False, None, "", None, "", "")]
        table.indexes = [
            IndexDef(
                "PRIMARY",
                True,
                [IndexPart(1, "id", None, "A", None), IndexPart(2, None, None, "", "upper(`name`)")],
            )
        ]
        # 函数索引部分不是可排序的普通列：只取普通列部分；全部为表达式时报错
        assert build_sample_sql("shop", table, limit=5).startswith("SELECT `id`")
        table.indexes = [IndexDef("PRIMARY", True, [IndexPart(1, None, None, "", "upper(`x`)")])]
        with pytest.raises(NoPrimaryKeyError):
            build_sample_sql("shop", table, limit=5)


class TestReviewRegressions:
    """评审回归：v2 采样节解析防御与精度往返。"""

    def test_sample_missing_keys_is_value_error(self) -> None:
        import json as _json

        from modou.snapshot.model import snapshot_from_json

        raw = {
            "format_version": 2,
            "tool_version": "t",
            "captured_at": "c",
            "meta": {
                "server_version": "8.4.6",
                "version_comment": "",
                "character_set_server": "utf8mb4",
                "collation_server": "utf8mb4_0900_ai_ci",
                "lower_case_table_names": 0,
                "sql_mode": "",
            },
            "databases": {
                "shop": {
                    "name": "shop",
                    "charset": "utf8mb4",
                    "collation": "utf8mb4_0900_ai_ci",
                    "tables": {
                        "t": {
                            "name": "t",
                            "engine": "InnoDB",
                            "collation": "",
                            "comment": "",
                            "create_options": "",
                            "ddl": "",
                            "columns": [],
                            "indexes": [],
                            "foreign_keys": [],
                            "check_constraints": [],
                            "sample": {"rows": "not-a-list"},
                        }
                    },
                    "views": {},
                    "procedures": {},
                    "functions": {},
                    "triggers": {},
                    "events": {},
                    "warnings": [],
                }
            },
            "warnings": [],
        }
        with pytest.raises(ValueError, match=r"sample\.columns"):
            snapshot_from_json(_json.dumps(raw))

    def test_datetime_microseconds_survive_roundtrip(self) -> None:
        import datetime

        from modou.snapshot.sample import json_safe_value

        value = datetime.datetime(2026, 10, 15, 8, 30, 0, 123456)
        assert json_safe_value(value) == "2026-10-15T08:30:00.123456"
        # 无微秒时保持秒级形态（与既有快照兼容）
        assert json_safe_value(datetime.datetime(2026, 10, 15, 8, 30, 0)) == "2026-10-15T08:30:00"

    def test_time_microseconds_survive(self) -> None:
        import datetime

        from modou.snapshot.sample import json_safe_value

        assert json_safe_value(datetime.time(8, 30, 0, 500000)) == "08:30:00.500000"

    def test_timedelta_fractional_seconds(self) -> None:
        import datetime

        from modou.snapshot.sample import json_safe_value

        assert json_safe_value(datetime.timedelta(hours=1, microseconds=999999)) == "01:00:00.999999"
        assert json_safe_value(datetime.timedelta(hours=-1)) == "-01:00:00"

    def test_build_sample_sql_excludes_generated_columns(self) -> None:
        from modou.snapshot.model import ColumnDef, IndexDef, IndexPart, TableDef
        from modou.snapshot.sample import build_sample_sql

        table = TableDef(
            name="t",
            engine="InnoDB",
            collation="",
            comment="",
            create_options="",
            ddl="",
            columns=[
                ColumnDef("id", 1, "int", False, None, "", None, "", ""),
                ColumnDef("full_name", 2, "varchar(100)", True, None, "VIRTUAL GENERATED", None, "", "CONCAT(a, b)"),
            ],
            indexes=[IndexDef("PRIMARY", True, [IndexPart(1, "id", None, "A", None)])],
        )
        sql = build_sample_sql("shop", table, limit=5)
        assert "`full_name`" not in sql
        assert "`id`" in sql
