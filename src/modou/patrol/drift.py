"""比较两份结构快照，按维度报告新增、缺失和定义变更。"""

from __future__ import annotations

from dataclasses import dataclass, field

from modou.diff.threeway import (
    _OBJECT_CATEGORIES,
    MISSING_MARKER,
    DimensionDiff,
    _render_check,
    _render_column,
    _render_foreign_key,
    _render_index,
    _render_table_options,
)
from modou.snapshot.model import DatabaseInventory, ObjectDef, TableDef

CATEGORY_ADDED = "added"
CATEGORY_REMOVED = "removed"
CATEGORY_CHANGED = "changed"


def _normalize_ddl(ddl: str) -> str:
    """归一 DDL 空白，跨版本的换行和缩进不算漂移；比较和展示使用同一文本。"""
    return " ".join(ddl.split())


CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_ADDED: "新增",
    CATEGORY_REMOVED: "缺失",
    CATEGORY_CHANGED: "定义变更",
}


@dataclass
class DriftConclusion:
    database: str
    object_type: str
    object_name: str
    category: str
    dimensions: list[str] = field(default_factory=list)
    details: list[DimensionDiff] = field(default_factory=list)


@dataclass
class DriftReport:
    conclusions: dict[str, list[DriftConclusion]] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.conclusions else 0

    def count(self, category: str) -> int:
        return sum(1 for items in self.conclusions.values() for c in items if c.category == category)


def two_way_diff(baseline: DatabaseInventory | None, current: DatabaseInventory | None) -> list[DriftConclusion]:
    """对比单个库：基线有而当前无为缺失，反之为新增，两侧都有但维度不同为变更。"""
    anchor = baseline or current
    db_name = anchor.name if anchor else "?"
    conclusions: list[DriftConclusion] = []
    for attr, object_type in _OBJECT_CATEGORIES:
        b_objects = getattr(baseline, attr) if baseline else {}
        c_objects = getattr(current, attr) if current else {}
        for name in sorted(set(b_objects) | set(c_objects)):
            b_obj, c_obj = b_objects.get(name), c_objects.get(name)
            if object_type == "table":
                conclusions.extend(_diff_table(db_name, name, b_obj, c_obj))
            else:
                conclusions.extend(_diff_definition(db_name, object_type, name, b_obj, c_obj))
    # 库级字符集与排序规则
    if baseline and current:
        sides = [
            side
            for side, b_value, c_value in (
                ("charset", baseline.charset, current.charset),
                ("collation", baseline.collation, current.collation),
            )
            if b_value != c_value
        ]
        if sides:
            conclusions.append(
                DriftConclusion(
                    database=db_name,
                    object_type="database",
                    object_name=db_name,
                    category=CATEGORY_CHANGED,
                    dimensions=sides,
                    details=[
                        DimensionDiff(
                            dimension=side,
                            path="database",
                            expected=getattr(baseline, side),
                            actual=getattr(current, side),
                        )
                        for side in sides
                    ],
                )
            )
    return conclusions


def _diff_table(db_name: str, name: str, b_table: TableDef | None, c_table: TableDef | None) -> list[DriftConclusion]:
    if b_table is None and c_table is None:
        return []
    if b_table is None or c_table is None:
        return [
            DriftConclusion(
                database=db_name,
                object_type="table",
                object_name=name,
                category=CATEGORY_REMOVED if c_table is None else CATEGORY_ADDED,
                dimensions=["existence"],
                details=[
                    DimensionDiff(
                        dimension="existence",
                        path=name,
                        expected="exists" if b_table else MISSING_MARKER,
                        actual=MISSING_MARKER if c_table is None else "exists",
                    )
                ],
            )
        ]
    by_kind: dict[str, DriftConclusion] = {}

    def record(category: str, dimension: str, detail: DimensionDiff) -> None:
        conclusion = by_kind.get(category)
        if conclusion is None:
            conclusion = DriftConclusion(database=db_name, object_type="table", object_name=name, category=category)
            by_kind[category] = conclusion
        if dimension not in conclusion.dimensions:
            conclusion.dimensions.append(dimension)
        conclusion.details.append(detail)

    dimension_specs = [
        ("columns", {c.name: c for c in b_table.columns}, {c.name: c for c in c_table.columns}, _render_column),
        ("indexes", {i.name: i for i in b_table.indexes}, {i.name: i for i in c_table.indexes}, _render_index),
        (
            "foreign_keys",
            {fk.name: fk for fk in b_table.foreign_keys},
            {fk.name: fk for fk in c_table.foreign_keys},
            _render_foreign_key,
        ),
        (
            "check_constraints",
            {ck.name: ck for ck in b_table.check_constraints},
            {ck.name: ck for ck in c_table.check_constraints},
            _render_check,
        ),
    ]
    for dimension, b_state, c_state, render in dimension_specs:
        for item_name in sorted(set(b_state) | set(c_state)):
            b_item, c_item = b_state.get(item_name), c_state.get(item_name)
            if b_item == c_item:
                continue
            category = CATEGORY_REMOVED if c_item is None else (CATEGORY_ADDED if b_item is None else CATEGORY_CHANGED)
            record(
                category,
                dimension,
                DimensionDiff(
                    dimension=dimension,
                    path=str(item_name),
                    expected=MISSING_MARKER if b_item is None else render(b_item),
                    actual=MISSING_MARKER if c_item is None else render(c_item),
                ),
            )

    options_b = (b_table.engine, b_table.collation, b_table.comment, b_table.create_options)
    options_c = (c_table.engine, c_table.collation, c_table.comment, c_table.create_options)
    if options_b != options_c:
        record(
            CATEGORY_CHANGED,
            "options",
            DimensionDiff(
                dimension="options",
                path="table_options",
                expected=_render_table_options(options_b),
                actual=_render_table_options(options_c),
            ),
        )
    # 固定输出顺序：缺失、新增、定义变更
    return [by_kind[k] for k in (CATEGORY_REMOVED, CATEGORY_ADDED, CATEGORY_CHANGED) if k in by_kind]


def _diff_definition(
    db_name: str, object_type: str, name: str, b_obj: ObjectDef | None, c_obj: ObjectDef | None
) -> list[DriftConclusion]:
    if b_obj is None and c_obj is None:
        return []
    if b_obj is None or c_obj is None:
        return [
            DriftConclusion(
                database=db_name,
                object_type=object_type,
                object_name=name,
                category=CATEGORY_REMOVED if c_obj is None else CATEGORY_ADDED,
                dimensions=["existence"],
                details=[
                    DimensionDiff(
                        dimension="existence",
                        path=name,
                        expected="exists" if b_obj else MISSING_MARKER,
                        actual=MISSING_MARKER if c_obj is None else "exists",
                    )
                ],
            )
        ]
    if _normalize_ddl(b_obj.ddl) == _normalize_ddl(c_obj.ddl):
        return []
    return [
        DriftConclusion(
            database=db_name,
            object_type=object_type,
            object_name=name,
            category=CATEGORY_CHANGED,
            dimensions=["definition"],
            details=[
                DimensionDiff(
                    dimension="definition",
                    path=name,
                    expected=_normalize_ddl(b_obj.ddl),
                    actual=_normalize_ddl(c_obj.ddl),
                )
            ],
        )
    ]


def drift_between_snapshots(
    baseline_databases: dict[str, DatabaseInventory],
    current_databases: dict[str, DatabaseInventory],
) -> DriftReport:
    """逐库做两方对比并按库聚合。"""
    report = DriftReport()
    for db_name in sorted(set(baseline_databases) | set(current_databases)):
        conclusions = two_way_diff(baseline_databases.get(db_name), current_databases.get(db_name))
        if conclusions:
            report.conclusions[db_name] = conclusions
    return report
