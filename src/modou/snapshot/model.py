"""定义快照导出模型和 JSON 转换。

结构字段用于 diff，归一化 DDL 用于灌入；可选采样数据供优化实证使用，支持读取格式 v1 和 v2。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FORMAT_VERSION = 2
# v1 只有结构；v2 增加可选采样数据
SUPPORTED_FORMAT_VERSIONS = (1, 2)


@dataclass
class TableSample:
    """表的确定性样本与数据规模信息。"""

    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    sampled_rows: int = 0
    estimated_rows: int | None = None
    method: str = "primary_key_asc"  # 采样方式，如 primary_key_asc、skipped_no_primary_key
    note: str = ""


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
    direction: str  # "A"/"D"/""；函数索引无方向
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
    sample: TableSample | None = None


@dataclass
class ObjectDef:
    """视图、过程、函数、触发器和事件，以归一化 DDL 为比较与灌入载体。"""

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
    """序列化为易读 JSON；拒绝 NaN 和 Infinity 等非标准 JSON 数值。"""
    return json.dumps(asdict(snapshot), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _require_int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"snapshot field {where} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"snapshot field {where} must be an integer") from exc


def _require_dict(value: object, where: str) -> dict:
    """要求字段为 JSON object，格式错误时抛出 ValueError。"""
    if not isinstance(value, dict):
        raise ValueError(f"snapshot field {where} must be a JSON object")
    return value


def _require_list(value: object, where: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"snapshot field {where} must be a JSON array")
    return value


def snapshot_from_json(text: str) -> Snapshot:
    """反序列化快照 JSON；拒绝不支持的版本或非法字段结构。"""
    raw = json.loads(text)
    raw = _require_dict(raw, "<root>")
    if raw.get("format_version") not in SUPPORTED_FORMAT_VERSIONS:
        raise ValueError(
            f"unsupported snapshot format_version: {raw.get('format_version')!r} "
            f"(supported: {', '.join(str(v) for v in SUPPORTED_FORMAT_VERSIONS)})"
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
            sample_raw = t_raw.get("sample")
            sample: TableSample | None = None
            if sample_raw is not None:
                sample_dict = _require_dict(sample_raw, f"databases[{db_name!r}].tables[{t_name!r}].sample")
                sample = TableSample(
                    columns=list(_require_list(sample_dict.get("columns"), f"{t_name!r}.sample.columns")),
                    rows=list(_require_list(sample_dict.get("rows"), f"{t_name!r}.sample.rows")),
                    sampled_rows=int(_require_int(sample_dict.get("sampled_rows"), f"{t_name!r}.sample.sampled_rows")),
                    estimated_rows=(
                        None
                        if sample_dict.get("estimated_rows") is None
                        else _require_int(sample_dict.get("estimated_rows"), f"{t_name!r}.sample.estimated_rows")
                    ),
                    method=str(sample_dict.get("method", "")),
                    note=str(sample_dict.get("note", "")),
                )
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
                sample=sample,
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
