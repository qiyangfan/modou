"""变更分包器：按库/语句组分包（OCR 分包思想，design §4）。

分组规则（确定性，测试固化）：
- 先按库分组（库为 None 的语句自成一组，视为同一「默认库」批次），
  组顺序 = 库首次出现序；
- 组内按 max_statements 与 max_chars 贪心装箱；单条超预算的语句独占一批，
  绝不丢弃、绝不截断（丢语句 = AI 漏审）。
并发单轮的聚合由调用方完成（bundler 只做确定性分组，不碰网络）。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_STATEMENTS = 8
DEFAULT_MAX_CHARS = 12000


@dataclass
class StatementUnit:
    """分包最小单元：语句文本 + 定位信息（观点区 subject 由此生成）。"""

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
    """按库分组 + 组内装箱：批次间不混库，批次内语句数与总字符受预算约束。"""
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
