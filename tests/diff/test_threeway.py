"""三方 diff 用例：漏执行 / 错执行 / 历史漂移 / 一致 / 多库分组。

基线 B（执行前）、期望 E（基线+回放变更集）、实际 A（执行后线上快照）。
"""

from dataclasses import replace

from modou.diff.threeway import (
    KIND_DRIFT,
    KIND_MISSING,
    KIND_WRONG,
    three_way_diff,
)
from modou.snapshot.model import (
    CheckDef,
    ColumnDef,
    DatabaseInventory,
    ForeignKeyDef,
    IndexDef,
    IndexPart,
    ObjectDef,
    TableDef,
)


def column(
    name: str, column_type: str = "int", ordinal: int = 1, nullable: bool = True, default: str | None = None
) -> ColumnDef:
    return ColumnDef(
        name=name,
        ordinal=ordinal,
        column_type=column_type,
        nullable=nullable,
        default=default,
        extra="",
        collation=None,
        comment="",
        generation_expression="",
    )


def index(name: str, columns: list[str], unique: bool = False) -> IndexDef:
    return IndexDef(
        name=name,
        unique=unique,
        parts=[
            IndexPart(seq=i + 1, column=c, sub_part=None, direction="A", expression=None) for i, c in enumerate(columns)
        ],
    )


def table(
    name: str,
    *,
    columns: list[ColumnDef],
    indexes: list[IndexDef] | None = None,
    foreign_keys: list[ForeignKeyDef] | None = None,
    checks: list[CheckDef] | None = None,
    engine: str = "InnoDB",
) -> TableDef:
    return TableDef(
        name=name,
        engine=engine,
        collation="utf8mb4_0900_ai_ci",
        comment="",
        create_options="",
        ddl=f"CREATE TABLE `{name}` (...)",
        columns=columns,
        indexes=indexes or [],
        foreign_keys=foreign_keys or [],
        check_constraints=checks or [],
    )


def db(
    name: str = "appdb", *, tables: dict | None = None, views: dict | None = None, procedures: dict | None = None
) -> DatabaseInventory:
    return DatabaseInventory(
        name=name,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
        tables=tables or {},
        views=views or {},
        procedures=procedures or {},
    )


def object_kind_names(conclusions) -> set[tuple[str, str, str]]:
    return {(c.database, c.object_type, c.object_name) for c in conclusions}


# ── 漏执行：变更集应建 t_orders，实际库里没有 ──────────────────────────────


def test_missing_execution_table_not_created() -> None:
    b = db(tables={"t_users": table("t_users", columns=[column("id")])})
    e = db(
        tables={
            "t_users": table("t_users", columns=[column("id")]),
            "t_orders": table("t_orders", columns=[column("id")]),
        }
    )
    a = db(tables={"t_users": table("t_users", columns=[column("id")])})
    conclusions = three_way_diff(b, e, a)
    assert object_kind_names(conclusions) == {("appdb", "table", "t_orders")}
    assert conclusions[0].kind == KIND_MISSING
    assert conclusions[0].dimensions == ["existence"]


# ── 错执行：索引列序建错 ─────────────────────────────────────────────────


def test_wrong_execution_index_column_order() -> None:
    common = dict(columns=[column("id"), column("a", ordinal=2), column("b", ordinal=3)])
    b = db(tables={"t1": table("t1", **common)})
    e = db(tables={"t1": table("t1", **common, indexes=[index("idx_ab", ["a", "b"])])})
    a = db(tables={"t1": table("t1", **common, indexes=[index("idx_ab", ["b", "a"])])})
    conclusions = three_way_diff(b, e, a)
    assert object_kind_names(conclusions) == {("appdb", "table", "t1")}
    assert conclusions[0].kind == KIND_WRONG
    assert conclusions[0].dimensions == ["indexes"]


def test_wrong_execution_column_type_differs() -> None:
    b = db(tables={"t1": table("t1", columns=[column("id"), column("tier", "varchar(10)", ordinal=2)])})
    e = db(tables={"t1": table("t1", columns=[column("id"), column("tier", "varchar(50)", ordinal=2)])})
    a = db(tables={"t1": table("t1", columns=[column("id"), column("tier", "varchar(10)", ordinal=2)])})
    conclusions = three_way_diff(b, e, a)
    assert conclusions[0].kind == KIND_MISSING  # 实际仍停在基线 → 变更未生效，归漏执行


def test_column_collation_difference_rendered() -> None:
    """collation 参与判差就必须参与渲染：两侧渲染同文时读者无法理解差异何在。

    真链场景：链脚本建表不钉 collation（继承库默认），交付 dump 产物固化了
    生成环境默认——verify 判 59 表「错执行（列、表选项）」但列渲染同文。
    """
    e = db(
        tables={"t1": table("t1", columns=[replace(column("plant_id", "varchar(64)"), collation="utf8mb4_unicode_ci")])}
    )
    a = db(
        tables={"t1": table("t1", columns=[replace(column("plant_id", "varchar(64)"), collation="utf8mb4_0900_ai_ci")])}
    )
    conclusions = three_way_diff(None, e, a)
    assert conclusions[0].kind == KIND_WRONG
    assert conclusions[0].dimensions == ["columns"]
    detail = conclusions[0].details[0]
    assert "collation=utf8mb4_unicode_ci" in detail.expected
    assert "collation=utf8mb4_0900_ai_ci" in detail.actual


def test_column_comment_difference_rendered() -> None:
    """comment 同为参与比较的字段，渲染必须可区分（真链场景：执行事故把中文注释双重编码固化）。"""
    e = db(tables={"t1": table("t1", columns=[replace(column("plant_id", "varchar(64)"), comment="电站标识")])})
    a = db(tables={"t1": table("t1", columns=[replace(column("plant_id", "varchar(64)"), comment="çµç«æ è¯")])})
    conclusions = three_way_diff(None, e, a)
    assert conclusions[0].kind == KIND_WRONG
    detail = conclusions[0].details[0]
    # !r 渲染把乱码中的不可打印字节转义为 \xNN 字面量，字节形态对读者无歧义
    assert "comment='电站标识'" in detail.expected
    assert r"\x94" in detail.actual
    assert detail.expected != detail.actual


def test_new_table_options_mismatch_is_wrong_execution() -> None:
    """回归：新建表（基线无此表）且表选项与期望不符时，应归为错执行而非崩溃。

    真实场景：运维以 latin1 客户端执行含中文注释的变更集，注释被双重编码固化，
    verify 必须把它作为错执行报出来，这正是验收的本职。
    """
    expected_table = replace(table("orders", columns=[column("id")]), comment="订单表")
    actual_table = replace(expected_table, comment="è®¢å¡¨")  # latin1 双重编码后的固化形态
    conclusions = three_way_diff(None, db(tables={"orders": expected_table}), db(tables={"orders": actual_table}))
    table_conclusions = [c for c in conclusions if c.object_type == "table" and c.object_name == "orders"]
    assert [c.kind for c in table_conclusions] == [KIND_WRONG]
    assert table_conclusions[0].dimensions == ["options"]


# ── 历史漂移：变更集未触碰的对象在线上被他人改动 ────────────────────────────


def test_created_but_index_missing_is_missing_not_wrong() -> None:
    """对象已创建、其中一条语句（建索引）漏执行 → 该维度归漏执行而非错执行。"""
    b = db(tables={"t1": table("t1", columns=[column("id"), column("a", ordinal=2)])})
    e = db(tables={"t1": table("t1", columns=[column("id"), column("a", ordinal=2)], indexes=[index("idx_a", ["a"])])})
    a = db(tables={"t1": table("t1", columns=[column("id"), column("a", ordinal=2)])})
    conclusions = three_way_diff(b, e, a)
    assert [c.kind for c in conclusions] == [KIND_MISSING]
    assert conclusions[0].dimensions == ["indexes"]


def test_historical_drift_on_untouched_table() -> None:
    b = db(
        tables={
            "t_users": table("t_users", columns=[column("id")]),
            "t_legacy": table("t_legacy", columns=[column("old", "varchar(10)")]),
        }
    )
    e = db(
        tables={
            "t_users": table("t_users", columns=[column("id"), column("name", "varchar(50)", ordinal=2)]),
            "t_legacy": table("t_legacy", columns=[column("old", "varchar(10)")]),
        }
    )
    a = db(
        tables={
            "t_users": table("t_users", columns=[column("id"), column("name", "varchar(50)", ordinal=2)]),
            "t_legacy": table("t_legacy", columns=[column("old", "varchar(99)")]),
        }
    )
    conclusions = three_way_diff(b, e, a)
    # 本次变更（t_users 加列）已正确落地；t_legacy 与变更无关却变了 → 历史漂移
    assert object_kind_names(conclusions) == {("appdb", "table", "t_legacy")}
    assert conclusions[0].kind == KIND_DRIFT


def test_correctly_executed_drop_yields_no_conclusion() -> None:
    """变更集删除对象且实际已删除 → 全部一致（回归：曾在此场景抛 ValueError）。"""
    dropped = table("t_old", columns=[column("id")])
    b = db(tables={"t_old": dropped})
    e = db(tables={})
    a = db(tables={})
    assert three_way_diff(b, e, a) == []


def test_correctly_executed_drop_routine_yields_no_conclusion() -> None:
    b = db(procedures={"p1": ObjectDef(name="p1", ddl="CREATE PROCEDURE p1() BEGIN SELECT 1; END")})
    assert three_way_diff(b, db(procedures={}), db(procedures={})) == []


def test_missed_drop_is_missing_execution() -> None:
    """变更集删除对象但实际仍在 → 漏执行。"""
    dropped = table("t_old", columns=[column("id")])
    b = db(tables={"t_old": dropped})
    e = db(tables={})
    a = db(tables={"t_old": dropped})
    conclusions = three_way_diff(b, e, a)
    assert [c.kind for c in conclusions] == [KIND_MISSING]


def test_same_object_multiple_kinds_per_dimension() -> None:
    """同对象多维度不同类别：索引漏执行与列定义错执行各自成条。"""
    b = db(tables={"t1": table("t1", columns=[column("id"), column("a", ordinal=2)])})
    e = db(
        tables={
            "t1": table(
                "t1", columns=[column("id"), column("a", "varchar(50)", ordinal=2)], indexes=[index("idx_a", ["a"])]
            ),
        }
    )
    a = db(
        tables={
            "t1": table("t1", columns=[column("id"), column("a", "varchar(99)", ordinal=2)]),
        }
    )
    conclusions = three_way_diff(b, e, a)
    kinds = {c.kind: c for c in conclusions}
    assert set(kinds) == {KIND_MISSING, KIND_WRONG}
    assert kinds[KIND_MISSING].dimensions == ["indexes"]
    assert kinds[KIND_WRONG].dimensions == ["columns"]


def test_extra_object_on_server_is_drift() -> None:
    b = db(tables={"t_users": table("t_users", columns=[column("id")])})
    e = db(tables={"t_users": table("t_users", columns=[column("id")])})
    a = db(
        tables={
            "t_users": table("t_users", columns=[column("id")]),
            "t_ghost": table("t_ghost", columns=[column("x")]),
        }
    )
    conclusions = three_way_diff(b, e, a)
    assert object_kind_names(conclusions) == {("appdb", "table", "t_ghost")}
    assert conclusions[0].kind == KIND_DRIFT


# ── 一致 ────────────────────────────────────────────────────────────────


def test_all_consistent_no_conclusions() -> None:
    b = db(
        tables={
            "t1": table("t1", columns=[column("id"), column("a")], indexes=[index("idx_a", ["a"])]),
        }
    )
    e = db(
        tables={
            "t1": table("t1", columns=[column("id"), column("a")], indexes=[index("idx_a", ["a"])]),
        }
    )
    conclusions = three_way_diff(b, e, b)
    assert conclusions == []


def test_fk_and_check_dimensions() -> None:
    fk = ForeignKeyDef(
        name="fk_o",
        columns=["uid"],
        ref_table="t_users",
        ref_columns=["id"],
        on_update="NO ACTION",
        on_delete="CASCADE",
    )
    b = db(tables={"t_o": table("t_o", columns=[column("uid")])})
    e = db(tables={"t_o": table("t_o", columns=[column("uid")], foreign_keys=[fk])})
    a = db(
        tables={
            "t_o": table(
                "t_o",
                columns=[column("uid")],
                foreign_keys=[
                    ForeignKeyDef(
                        name="fk_o",
                        columns=["uid"],
                        ref_table="t_users",
                        ref_columns=["id"],
                        on_update="NO ACTION",
                        on_delete="SET NULL",
                    )
                ],
            )
        }
    )
    conclusions = three_way_diff(b, e, a)
    assert conclusions[0].kind == KIND_WRONG
    assert conclusions[0].dimensions == ["foreign_keys"]


def test_routine_definition_diff() -> None:
    b = db(procedures={})
    e = db(procedures={"p1": ObjectDef(name="p1", ddl="CREATE PROCEDURE p1() BEGIN SELECT 1; END")})
    a = db(procedures={"p1": ObjectDef(name="p1", ddl="CREATE PROCEDURE p1() BEGIN SELECT 2; END")})
    conclusions = three_way_diff(b, e, a)
    assert conclusions[0].kind == KIND_WRONG
    assert conclusions[0].dimensions == ["definition"]


# ── 多库分组 ────────────────────────────────────────────────────────────


def test_multi_database_grouping() -> None:
    b0 = db("db0", tables={"t_users": table("t_users", columns=[column("id")])})
    e0 = db(
        "db0",
        tables={
            "t_users": table("t_users", columns=[column("id")]),
            "t_orders": table("t_orders", columns=[column("id")]),
        },
    )
    a0 = db("db0", tables={"t_users": table("t_users", columns=[column("id")])})

    common = dict(columns=[column("id"), column("a", ordinal=2), column("b", ordinal=3)])
    b1 = db("db1", tables={"t1": table("t1", **common)})
    e1 = db("db1", tables={"t1": table("t1", **common, indexes=[index("idx_ab", ["a", "b"])])})
    a1 = db("db1", tables={"t1": table("t1", **common, indexes=[index("idx_ab", ["b", "a"])])})

    conclusions = three_way_diff(b0, e0, a0) + three_way_diff(b1, e1, a1)
    assert {c.database for c in conclusions} == {"db0", "db1"}


# ── 库级缺快照：实际快照缺整库时，未被变更集触碰的对象归历史漂移 ──────────────


def test_database_missing_in_actual_untouched_object_is_drift() -> None:
    b = db("newdb", tables={"t1": table("t1", columns=[column("id")])})
    e = db("newdb", tables={"t1": table("t1", columns=[column("id")])})
    conclusions = three_way_diff(b, e, None)
    assert conclusions[0].kind == KIND_DRIFT


def test_database_missing_in_actual_expected_new_object_is_missing() -> None:
    e = db("newdb", tables={"t1": table("t1", columns=[column("id")])})
    conclusions = three_way_diff(None, e, None)
    assert conclusions[0].kind == KIND_MISSING


# ── 库级 charset/collation 维度（期望≠实际才产出结论，与其余维度同口径） ─────


def _db_charset(name: str, charset: str, collation: str) -> DatabaseInventory:
    return DatabaseInventory(name=name, charset=charset, collation=collation)


def test_db_charset_alter_landed_yields_no_conclusion() -> None:
    """回归：ALTER DATABASE 字符集合法落地（B=旧，E=A=新）→ 无结论，不得在 classify 崩溃。"""
    old = _db_charset("appdb", "utf8mb4", "utf8mb4_0900_ai_ci")
    new = _db_charset("appdb", "utf8mb3", "utf8mb3_general_ci")
    assert three_way_diff(old, new, new) == []


def test_db_charset_missed_execution_is_missing() -> None:
    old = _db_charset("appdb", "utf8mb4", "utf8mb4_0900_ai_ci")
    e = _db_charset("appdb", "utf8mb3", "utf8mb3_general_ci")
    conclusions = three_way_diff(old, e, old)
    assert [c.kind for c in conclusions] == [KIND_MISSING]
    # charset 与 collation 同时漂移：两个维度各自成条目，不折叠
    assert conclusions[0].dimensions == ["charset", "collation"]


def test_db_collation_drift_on_untouched_dimension() -> None:
    baseline = _db_charset("appdb", "utf8mb4", "utf8mb4_0900_ai_ci")
    actual = _db_charset("appdb", "utf8mb4", "utf8mb4_general_ci")
    conclusions = three_way_diff(baseline, baseline, actual)  # E==B：变更集未触碰，线上被他人改动
    assert [c.kind for c in conclusions] == [KIND_DRIFT]
    assert conclusions[0].dimension_labels == ["库排序规则"]


def test_new_db_charset_mismatch_is_wrong_execution() -> None:
    """基线缺库（新建库场景）：期望与实际的库字符集不符 → 错执行。"""
    e = _db_charset("newdb", "utf8mb4", "utf8mb4_0900_ai_ci")
    a = _db_charset("newdb", "latin1", "latin1_swedish_ci")
    conclusions = three_way_diff(None, e, a)
    assert [c.kind for c in conclusions] == [KIND_WRONG]
    assert conclusions[0].dimensions == ["charset", "collation"]
    assert [d.dimension for d in conclusions[0].details] == ["charset", "collation"]
