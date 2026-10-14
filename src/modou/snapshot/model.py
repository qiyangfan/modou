"""快照数据模型：导出格式的唯一事实源（format_version=1，契约冻结，见 docs/formats.md）。

设计要点：
- 结构化字段（列/索引/约束）供三方 diff 逐维对比，DDL 原文仅供灌入与人工排查；
- 内省侧已对 DDL 归一化（剥离 DEFINER），因此本模型不再做二次归一；
- 表选项不比较 AUTO_INCREMENT 计数器（运行时状态，非结构）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FORMAT_VERSION = 1


@dataclass
class ColumnDef:
    name: str
    ordinal: int
    column_type: str
    nullable: bool
    default: str | None
    extra: str
    collation: str | None
    comment: str
    generation_expression: str


@dataclass
class IndexPart:
    seq: int
    column: str
    sub_part: int | None
    direction: str  # "A" / "D" / ""（MySQL 8.0 函数索引无方向）
    expression: str | None


@dataclass
class IndexDef:
    name: str
    unique: bool
    parts: list[IndexPart] = field(default_factory=list)


@dataclass
class ForeignKeyDef:
    name: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_update: str
    on_delete: str


@dataclass
class CheckDef:
    name: str
    expression: str
    enforced: str  # YES / NO


@dataclass
class TableDef:
    name: str
    engine: str
    collation: str
    comment: str
    create_options: str
    ddl: str
    columns: list[ColumnDef] = field(default_factory=list)
    indexes: list[IndexDef] = field(default_factory=list)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    check_constraints: list[CheckDef] = field(default_factory=list)


@dataclass
class ObjectDef:
    """视图 / 存储过程 / 函数 / 触发器 / 事件：以归一化 DDL 为比较与灌入载体。"""

    name: str
    ddl: str


@dataclass
class DatabaseInventory:
    name: str
    charset: str
    collation: str
    tables: dict[str, TableDef] = field(default_factory=dict)
    views: dict[str, ObjectDef] = field(default_factory=dict)
    procedures: dict[str, ObjectDef] = field(default_factory=dict)
    functions: dict[str, ObjectDef] = field(default_factory=dict)
    triggers: dict[str, ObjectDef] = field(default_factory=dict)
    events: dict[str, ObjectDef] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SnapshotMeta:
    server_version: str
    version_comment: str
    character_set_server: str
    collation_server: str
    lower_case_table_names: int
    sql_mode: str


@dataclass
class Snapshot:
    format_version: int
    tool_version: str
    captured_at: str
    meta: SnapshotMeta
    databases: dict[str, DatabaseInventory] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def snapshot_to_json(snapshot: Snapshot) -> str:
    """序列化为导出格式（缩进 2 空格，人可读、可 diff）。"""
    return json.dumps(asdict(snapshot), ensure_ascii=False, indent=2) + "\n"


def _require_dict(value: object, where: str) -> dict:
    """反序列化防御：容器字段必须是 JSON object，否则报 ValueError（CLI 收敛退出码 2），
    而不是让 AttributeError/TypeError 之类裸穿透。"""
    if not isinstance(value, dict):
        raise ValueError(f"snapshot field {where} must be a JSON object")
    return value


def _require_list(value: object, where: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"snapshot field {where} must be a JSON array")
    return value


def snapshot_from_json(text: str) -> Snapshot:
    """从导出格式反序列化；格式版本不匹配或容器结构非法即拒绝（防静默误读）。"""
    raw = json.loads(text)
    raw = _require_dict(raw, "<root>")
    if raw.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"unsupported snapshot format_version: {raw.get('format_version')!r} (expected {FORMAT_VERSION})"
        )
    meta = SnapshotMeta(**_require_dict(raw["meta"], "meta"))
    databases: dict[str, DatabaseInventory] = {}
    for db_name, db_raw in _require_dict(raw["databases"], "databases").items():
        db_raw = _require_dict(db_raw, f"databases[{db_name!r}]")
        tables: dict[str, TableDef] = {}
        for t_name, t_value in _require_dict(db_raw["tables"], f"databases[{db_name!r}].tables").items():
            t_raw = _require_dict(t_value, f"databases[{db_name!r}].tables[{t_name!r}]")
            columns = [
                ColumnDef(**c)
                for c in _require_list(t_raw["columns"], f"databases[{db_name!r}].tables[{t_name!r}].columns")
            ]
            indexes_where = f"databases[{db_name!r}].tables[{t_name!r}].indexes"
            indexes = []
            for idx_pos, idx_value in enumerate(_require_list(t_raw["indexes"], indexes_where)):
                index_raw = _require_dict(idx_value, f"{indexes_where}[{idx_pos}]")
                parts_where = f"{indexes_where}[{index_raw.get('name')!r}].parts"
                indexes.append(
                    IndexDef(
                        name=index_raw["name"],
                        unique=index_raw["unique"],
                        parts=[IndexPart(**p) for p in _require_list(index_raw["parts"], parts_where)],
                    )
                )
            foreign_keys = [
                ForeignKeyDef(**fk)
                for fk in _require_list(
                    t_raw["foreign_keys"], f"databases[{db_name!r}].tables[{t_name!r}].foreign_keys"
                )
            ]
            checks = [
                CheckDef(**ck)
                for ck in _require_list(
                    t_raw["check_constraints"], f"databases[{db_name!r}].tables[{t_name!r}].check_constraints"
                )
            ]
            tables[t_name] = TableDef(
                name=t_raw["name"],
                engine=t_raw["engine"],
                collation=t_raw["collation"],
                comment=t_raw["comment"],
                create_options=t_raw["create_options"],
                ddl=t_raw["ddl"],
                columns=columns,
                indexes=indexes,
                foreign_keys=foreign_keys,
                check_constraints=checks,
            )
        object_fields = {
            "views": db_raw["views"],
            "procedures": db_raw["procedures"],
            "functions": db_raw["functions"],
            "triggers": db_raw["triggers"],
            "events": db_raw["events"],
        }
        object_maps = {
            field_name: {
                obj_name: ObjectDef(**obj_raw)
                for obj_name, obj_raw in _require_dict(mapping, f"databases[{db_name!r}].{field_name}").items()
            }
            for field_name, mapping in object_fields.items()
        }
        databases[db_name] = DatabaseInventory(
            name=db_raw["name"],
            charset=db_raw["charset"],
            collation=db_raw["collation"],
            tables=tables,
            **object_maps,
            warnings=list(_require_list(db_raw["warnings"], f"databases[{db_name!r}].warnings")),
        )
    return Snapshot(
        format_version=raw["format_version"],
        tool_version=raw["tool_version"],
        captured_at=raw["captured_at"],
        meta=meta,
        databases=databases,
        warnings=list(_require_list(raw["warnings"], "warnings")),
    )
