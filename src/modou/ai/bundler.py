"""按库分组并按语句数、字符预算分包；超预算语句独占一批，不截断或丢弃。"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_STATEMENTS = 8
DEFAULT_MAX_CHARS = 12000


@dataclass
class StatementUnit:
    """分包的最小单元，携带语句与定位信息。"""

    file: str
    line: int
    sql: str
    database: str | None = None

    @property
    def subject(self) -> str:
        return f"{self.file}:{self.line}"


def bundle_units(
    units: list[StatementUnit],
    *,
    max_statements: int = DEFAULT_MAX_STATEMENTS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[list[StatementUnit]]:
    """按库分组后装箱，批次不混库，语句数与字符数受预算约束。"""
    groups: dict[str | None, list[StatementUnit]] = {}
    for unit in units:
        groups.setdefault(unit.database, []).append(unit)

    batches: list[list[StatementUnit]] = []
    for _database, group in groups.items():
        current: list[StatementUnit] = []
        current_chars = 0
        for unit in group:
            unit_chars = len(unit.sql)
            fits = current and len(current) < max_statements and current_chars + unit_chars <= max_chars
            if not fits:
                if current:
                    batches.append(current)
                current = [unit]
                current_chars = unit_chars
            else:
                current.append(unit)
                current_chars += unit_chars
        if current:
            batches.append(current)
    return batches
