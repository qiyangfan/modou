"""按主键顺序确定性采样，并转换快照中保存和还原的行值。"""

from __future__ import annotations

import datetime
from decimal import Decimal

from modou.snapshot.model import TableDef

BINARY_TAG = "$binary"

# TEXT/BLOB 索引必须带前缀长度；64 是选择性与长度的折中
TEXT_PREFIX_LENGTH = 64
_TEXT_TYPE_PREFIXES = ("text", "blob", "tinytext", "tinyblob", "mediumtext", "mediumblob", "longtext", "longblob")


class NoPrimaryKeyError(Exception):
    """表无可用主键（或主键全为表达式部分），无法做确定性顺序采样。"""


def json_safe_value(value: object) -> object:
    """将 pymysql 返回值转为 JSON 可序列化类型，保留时间精度。"""
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {BINARY_TAG: value.hex()}
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        # MySQL TIME 可为负、可带小数秒，pymysql 以 timedelta 返回
        total_seconds = value.days * 86400 + value.seconds
        sign = "-" if total_seconds < 0 else ""
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        base = f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{base}.{value.microseconds:06d}" if value.microseconds else base
    if isinstance(value, (set, frozenset)):
        return ",".join(sorted(str(item) for item in value))
    return str(value)


def restore_value(json_value: object, column_type: str) -> object:
    """把快照中的 JSON 值转回可绑定参数，并还原二进制标记。"""
    if isinstance(json_value, dict) and BINARY_TAG in json_value:
        return bytes.fromhex(str(json_value[BINARY_TAG]))
    return json_value


def has_usable_primary_key(table: TableDef) -> bool:
    primary = next((idx for idx in table.indexes if idx.name == "PRIMARY"), None)
    if primary is None:
        return False
    return bool(_orderable_key_parts(primary.parts))


def _orderable_key_parts(parts: list) -> list[str]:
    """主键中可排序的普通列（排除函数/表达式部分）。"""
    return [part.column for part in parts if part.column]


def build_sample_sql(database: str, table: TableDef, *, limit: int) -> str:
    """构造按主键排序并限制行数的采样 SQL；排除不能显式插入的生成列。"""
    if not table.columns:
        raise NoPrimaryKeyError(f"table {database}.{table.name} has no column metadata")
    primary = next((idx for idx in table.indexes if idx.name == "PRIMARY"), None)
    key_parts = _orderable_key_parts(primary.parts) if primary else []
    if not key_parts:
        raise NoPrimaryKeyError(f"table {database}.{table.name} has no usable primary key")

    def quote(name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    sample_columns = [col for col in table.columns if not col.generation_expression]
    columns = ", ".join(quote(col.name) for col in sample_columns)
    order = ", ".join(quote(part) + " ASC" for part in key_parts)
    db = quote(database)
    tbl = quote(table.name)
    return f"SELECT {columns} FROM {db}.{tbl} ORDER BY {order} LIMIT {int(limit)}"


def build_index_prefix(column_type: str) -> str:
    """TEXT/BLOB 列的索引需要前缀长度，其余整列索引。"""
    lowered = column_type.lower()
    if lowered.startswith(_TEXT_TYPE_PREFIXES):
        return str(TEXT_PREFIX_LENGTH)
    return ""
