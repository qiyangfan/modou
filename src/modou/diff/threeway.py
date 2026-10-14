"""三方结构化 diff：基线 B（执行前）、期望 E（基线+回放）、实际 A（执行后）对比。

分类在「维度」粒度进行、按类别聚合成结论（对象 × 类别 一条）：
- E == A：该维度本次变更正确落地，无结论；
- E != A 且 B == A：线上停在该维度的基线态，变更未生效 → 漏执行；
- E != A 且 B == E：变更集未触碰的维度，线上却与基线不同 → 历史漂移（他人并行改动）；
- 其余（A 同时异于 B 与 E）：执行了但结果不对 → 错执行。

一个对象多个维度可产生不同类别（如索引漏执行、列定义错执行），各自成条。
比较用结构化字段而非 DDL 原文，杜绝格式化假差异（ADR-0004 同源）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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

KIND_MISSING = "missing_execution"
KIND_WRONG = "wrong_execution"
KIND_DRIFT = "historical_drift"


class DiffInvariantError(Exception):
    """三方分类的内部不变量被破坏（E==A 时调用 classify 等）：属编程错误，
    必须响亮穿透而非被管线的环境异常网收敛为退出码 2。"""


MISSING_MARKER = "<missing>"

_OBJECT_CATEGORIES: list[tuple[str, str]] = [
    # (inventory 属性, object_type)
    ("tables", "table"),
    ("views", "view"),
    ("procedures", "procedure"),
    ("functions", "function"),
    ("triggers", "trigger"),
    ("events", "event"),
]

_DIMENSION_LABELS: dict[str, str] = {
    "existence": "存在性",
    "options": "表选项",
    "columns": "列",
    "indexes": "索引",
    "foreign_keys": "外键",
    "check_constraints": "检查约束",
    "definition": "定义",
    "charset": "库字符集",
    "collation": "库排序规则",
}


@dataclass
class DimensionDiff:
    dimension: str
    path: str
    expected: str
    actual: str


@dataclass
class ObjectConclusion:
    database: str
    object_type: str
    object_name: str
    kind: str
    dimensions: list[str] = field(default_factory=list)
    details: list[DimensionDiff] = field(default_factory=list)

    @property
    def dimension_labels(self) -> list[str]:
        return [_DIMENSION_LABELS.get(d, d) for d in self.dimensions]


def three_way_diff(
    baseline: DatabaseInventory | None,
    expected: DatabaseInventory | None,
    actual: DatabaseInventory | None,
) -> list[ObjectConclusion]:
    """对单个库做三方对比，返回全部结论（按 对象 × 类别 聚合）。"""
    anchor = expected or baseline or actual
    db_name = anchor.name if anchor else "?"
    conclusions: list[ObjectConclusion] = []
    for attr, object_type in _OBJECT_CATEGORIES:
        b_objects = getattr(baseline, attr) if baseline else {}
        e_objects = getattr(expected, attr) if expected else {}
        a_objects = getattr(actual, attr) if actual else {}
        for name in sorted(set(b_objects) | set(e_objects) | set(a_objects)):
            conclusions.extend(
                _diff_object(
                    db_name,
                    object_type,
                    name,
                    b_objects.get(name),
                    e_objects.get(name),
                    a_objects.get(name),
                )
            )
    # 库级元信息（默认字符集/collation）：与其余维度同口径，期望≠实际才产出结论。
    # 守卫若误用 B≠A，合法落地（E==A）会在 _classify 处崩溃、漏执行（B==A）会漏报
    baseline_state = (baseline.charset, baseline.collation) if baseline else None
    if expected and actual and (expected.charset, expected.collation) != (actual.charset, actual.collation):
        # charset 与 collation 同时漂移时各自成一个维度条目，不折叠进单一标签
        sides = [
            side
            for side, e_value, a_value in (
                ("charset", expected.charset, actual.charset),
                ("collation", expected.collation, actual.collation),
            )
            if e_value != a_value
        ]
        conclusions.append(
            ObjectConclusion(
                database=db_name,
                object_type="database",
                object_name=db_name,
                kind=_classify(
                    baseline_state,
                    (expected.charset, expected.collation),
                    (actual.charset, actual.collation),
                ),
                dimensions=sides,
                details=[
                    DimensionDiff(
                        dimension=side,
                        path="database",
                        expected=side_e,
                        actual=side_a,
                    )
                    for side, side_e, side_a in (
                        ("charset", expected.charset, actual.charset),
                        ("collation", expected.collation, actual.collation),
                    )
                    if side in sides
                ],
            )
        )
    return conclusions


def _diff_object(
    db_name: str,
    object_type: str,
    name: str,
    b_obj: object | None,
    e_obj: object | None,
    a_obj: object | None,
) -> list[ObjectConclusion]:
    """单对象：逐维度分类，按类别聚合为 0~3 条结论。"""
    if object_type == "table":
        dimension_findings = _table_dimension_findings(b_obj, e_obj, a_obj)  # type: ignore[arg-type]
    else:
        dimension_findings = _definition_dimension_findings(b_obj, e_obj, a_obj)  # type: ignore[arg-type]

    by_kind: dict[str, ObjectConclusion] = {}
    for kind, dimension, details in dimension_findings:
        conclusion = by_kind.get(kind)
        if conclusion is None:
            conclusion = ObjectConclusion(database=db_name, object_type=object_type, object_name=name, kind=kind)
            by_kind[kind] = conclusion
        if dimension not in conclusion.dimensions:
            conclusion.dimensions.append(dimension)
        conclusion.details.extend(details)
    # 输出顺序稳定：漏执行 → 错执行 → 历史漂移
    return [by_kind[kind] for kind in (KIND_MISSING, KIND_WRONG, KIND_DRIFT) if kind in by_kind]


def _classify(b_state: object, e_state: object, a_state: object) -> str:
    if e_state == a_state:
        raise DiffInvariantError("classify requires expected != actual")
    if b_state == a_state:
        return KIND_MISSING
    if b_state == e_state:
        return KIND_DRIFT
    return KIND_WRONG


def _table_dimension_findings(
    b_table: TableDef | None,
    e_table: TableDef | None,
    a_table: TableDef | None,
) -> list[tuple[str, str, list[DimensionDiff]]]:
    """表的维度级判定：存在性 → 列/索引/外键/检查约束 → 表选项。"""
    findings: list[tuple[str, str, list[DimensionDiff]]] = []

    if e_table is None or a_table is None:
        if e_table is None and a_table is None:
            # 变更集要求删除、实际也已删除（或两侧皆无）：本次变更已正确落地，无结论
            return findings
        findings.append(
            (
                _classify(b_table is not None, e_table is not None, a_table is not None),
                "existence",
                [
                    DimensionDiff(
                        dimension="existence",
                        path=e_table.name if e_table else (a_table.name if a_table else "?"),
                        expected=MISSING_MARKER if e_table is None else "exists",
                        actual=MISSING_MARKER if a_table is None else "exists",
                    )
                ],
            )
        )
        return findings

    dimension_specs: list[tuple[str, dict, dict, dict, object]] = []
    # (维度名, b_state, e_state, a_state, 渲染函数)；state 为「条目名 → 定义」映射
    dimension_specs.append(
        (
            "columns",
            _by_name(b_table.columns) if b_table else {},
            _by_name(e_table.columns),
            _by_name(a_table.columns),
            _render_column,
        )
    )  # type: ignore[arg-type]
    dimension_specs.append(
        (
            "indexes",
            _by_name(b_table.indexes) if b_table else {},
            _by_name(e_table.indexes),
            _by_name(a_table.indexes),
            _render_index,
        )
    )  # type: ignore[arg-type]
    dimension_specs.append(
        (
            "foreign_keys",
            _by_name(b_table.foreign_keys) if b_table else {},
            _by_name(e_table.foreign_keys),
            _by_name(a_table.foreign_keys),
            _render_foreign_key,
        )
    )  # type: ignore[arg-type]
    dimension_specs.append(
        (
            "check_constraints",
            _by_name(b_table.check_constraints) if b_table else {},
            _by_name(e_table.check_constraints),
            _by_name(a_table.check_constraints),
            _render_check,
        )
    )  # type: ignore[arg-type]

    # 维度内逐「条目」分类：E→A 的每处差异，按该条目在 B 中的状态归因。
    # 整维度状态比较会把「建表后漏加一列」误判为错执行（基线无此表 → 列集全不同）。
    for dimension, b_state, e_state, a_state, render in dimension_specs:
        for kind, detail in _classify_items(dimension, b_state, e_state, a_state, render):
            findings.append((kind, dimension, [detail]))

    options_e = (e_table.engine, e_table.collation, e_table.comment, e_table.create_options)
    options_a = (a_table.engine, a_table.collation, a_table.comment, a_table.create_options)
    if options_e != options_a:
        # 基线无此表（新建场景）时以 None 参与分类：E≠A 且 A 异于「不存在」→ 错执行
        # （如运维以 latin1 客户端执行含中文注释的变更集，注释被双重编码固化）
        options_b = (b_table.engine, b_table.collation, b_table.comment, b_table.create_options) if b_table else None
        findings.append(
            (
                _classify(options_b, options_e, options_a),
                "options",
                [
                    DimensionDiff(
                        dimension="options",
                        path="table_options",
                        expected=_render_table_options(options_e),
                        actual=_render_table_options(options_a),
                    )
                ],
            )
        )
    return findings


def _definition_dimension_findings(
    b_obj: ObjectDef | None,
    e_obj: ObjectDef | None,
    a_obj: ObjectDef | None,
) -> list[tuple[str, str, list[DimensionDiff]]]:
    """视图/过程/函数/触发器/事件：存在性 + 定义两个维度。"""
    if e_obj is None or a_obj is None:
        if e_obj is None and a_obj is None:
            # 变更集要求删除、实际也已删除：本次变更已正确落地，无结论
            return []
        return [
            (
                _classify(b_obj is not None, e_obj is not None, a_obj is not None),
                "existence",
                [
                    DimensionDiff(
                        dimension="existence",
                        path=e_obj.name if e_obj else (a_obj.name if a_obj else "?"),
                        expected=MISSING_MARKER if e_obj is None else "exists",
                        actual=MISSING_MARKER if a_obj is None else "exists",
                    )
                ],
            )
        ]
    if e_obj.ddl == a_obj.ddl:
        return []
    b_ddl = b_obj.ddl if b_obj else None
    return [
        (
            _classify(b_ddl, e_obj.ddl, a_obj.ddl),
            "definition",
            [
                DimensionDiff(
                    dimension="definition",
                    path=e_obj.name,
                    expected=_compact_ddl(e_obj.ddl),
                    actual=_compact_ddl(a_obj.ddl),
                )
            ],
        )
    ]


def _by_name(items: list) -> dict:
    return {item.name: item for item in items}


def _classify_items(
    dimension: str,
    b_state: dict,
    e_state: dict,
    a_state: dict,
    render: Callable[[object], str],
) -> list[tuple[str, DimensionDiff]]:
    """维度内逐条目分类：只看 E 与 A 有差异的条目，按该条目在 B 中的状态归因。"""
    findings: list[tuple[str, DimensionDiff]] = []
    for name in sorted(set(e_state) | set(a_state)):
        expected, actual = e_state.get(name), a_state.get(name)
        if expected == actual:
            continue
        kind = _classify(b_state.get(name), expected, actual)
        findings.append(
            (
                kind,
                DimensionDiff(
                    dimension=dimension,
                    path=str(name),
                    expected=MISSING_MARKER if expected is None else render(expected),
                    actual=MISSING_MARKER if actual is None else render(actual),
                ),
            )
        )
    return findings


def _render_table_options(options: tuple) -> str:
    engine, collation, comment, create_options = options
    return f"engine={engine} collation={collation} comment={comment!r} options={create_options!r}"


def _render_column(column: ColumnDef) -> str:
    nullability = "NULL" if column.nullable else "NOT NULL"
    default = f" default={column.default!r}" if column.default is not None else ""
    extra = f" extra={column.extra}" if column.extra else ""
    generated = f" as({column.generation_expression})" if column.generation_expression else ""
    return f"{column.column_type} {nullability}{default}{extra}{generated} ordinal={column.ordinal}"


def _render_index(index: IndexDef) -> str:
    parts = ",".join(_render_index_part(part) for part in index.parts)
    uniqueness = "unique" if index.unique else "index"
    return f"{uniqueness}({parts})"


def _render_index_part(part: IndexPart) -> str:
    if part.expression:
        text = part.expression
    elif part.sub_part:
        text = f"{part.column}({part.sub_part})"
    else:
        text = part.column
    # DESC 方向是结构的一部分，缺了它两侧渲染相同、读者无法理解差异何在
    return f"{text} {part.direction}" if part.direction == "D" else text


def _render_foreign_key(fk: ForeignKeyDef) -> str:
    return f"{fk.columns}->{fk.ref_table}.{fk.ref_columns} on_update={fk.on_update} on_delete={fk.on_delete}"


def _render_check(check: CheckDef) -> str:
    return f"{check.expression} enforced={check.enforced}"


def _compact_ddl(ddl: str) -> str:
    """DDL 压缩为单行摘要（完整原文以文件形式随报告输出时再展开）。"""
    return " ".join(ddl.split())
