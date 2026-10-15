"""采样数据：确定性抽样 SQL 构造与行值的 JSON 化/还原。

采样口径（v0.2 design §1）：
- 按主键索引顺序取前 N 行（索引顺序读，对线上低成本）；同库同参数重复采集
  得到相同样本集——ORDER BY 主键列 ASC 在唯一主键下是确定性序；
- 行值经 json_safe_value 转为 JSON 安全形态存储，灌入时按列类型还原
  （restore_value）：二进制带 $binary 标记还原为 bytes，时间类型以 ISO 字符串
  直接作为参数传入（MySQL 接受 'T' 分隔的 datetime 字面量）。
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from modou.snapshot.model import TableDef

BINARY_TAG = "$binary"

# TEXT/BLOB 列建索引必须给前缀长度；64 字符是索引选择性与长度的折中口径
TEXT_PREFIX_LENGTH = 64
_TEXT_TYPE_PREFIXES = ("text", "blob", "tinytext", "tinyblob", "mediumtext", "mediumblob", "longtext", "longblob")


class NoPrimaryKeyError(Exception):
    """表无可用主键（或主键全为表达式部分），无法做确定性顺序采样。"""


def json_safe_value(value: object) -> object:
    """把 pymysql 返回值转为 JSON 安全形态（快照存储侧）。

    时间类型保留完整精度（微秒在 isoformat 中按需出现）——截断会让样本集
    与源值不一致，「确定性样本集」承诺失真。
    """
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
        # MySQL TIME（可为负、可带小数秒）：pymysql 以 timedelta 给出
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
    """把快照中的 JSON 值还原为 pymysql 可绑定的参数（影子灌入侧）。

    时间列的 ISO 字符串直接作为参数传入（MySQL 接受 'T' 分隔字面量），
    无需按类型解析回 Python 对象；仅二进制标记需要显式还原。
    """
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
    """构造确定性采样 SQL：显式列名 + 主键顺序 + 行数上限（禁止 SELECT *）。

    生成列（generation_expression 非空）不进采样列清单：MySQL 对显式赋值
    生成列的 INSERT 报 3105，且其值可由基列推导，排除无损。
    """
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
