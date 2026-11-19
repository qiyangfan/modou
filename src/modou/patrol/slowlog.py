"""从本地 MySQL 慢日志解析条目，并按查询指纹聚合耗时和扫描行数。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from modou.patrol.fingerprint import fingerprint

_HEADER_TIME = re.compile(r"^# Time:\s*(.+)$")
_HEADER_USER = re.compile(r"^# User@Host:")
_METRIC_QUERY_TIME = re.compile(r"Query_time:\s*([0-9.eE+-]+)")
_METRIC_LOCK_TIME = re.compile(r"Lock_time:\s*([0-9.eE+-]+)")
_METRIC_ROWS_SENT = re.compile(r"Rows_sent:\s*(\d+)")
_METRIC_ROWS_EXAMINED = re.compile(r"Rows_examined:\s*(\d+)")
_SET_TIMESTAMP = re.compile(r"^SET\s+timestamp\s*=\s*(\d+)\s*;", re.IGNORECASE)
_USE_LINE = re.compile(r"^USE\s+", re.IGNORECASE)


@dataclass
class SlowEntry:
    query_time: float
    lock_time: float
    rows_sent: int
    rows_examined: int
    statement: str
    time_hint: str | None = None  # 时间来源：日志头或 SET timestamp，仅供参考

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.statement)


@dataclass
class SlowAggregate:
    fingerprint: str
    count: int = 0
    query_time_total: float = 0.0
    query_time_max: float = 0.0
    rows_examined_total: int = 0
    sample: str = ""


@dataclass
class SlowlogReport:
    source_file: str
    entries_parsed: int = 0
    skipped_lines: int = 0
    top: list[SlowAggregate] = field(default_factory=list)


def parse_slowlog(text: str) -> tuple[list[SlowEntry], int]:
    """返回条目清单和跳过条目数；指标值损坏时跳过该条，不中断解析。"""
    return _SlowlogParser().parse(text)


class _SlowlogParser:
    """逐行状态机：条目在 Query_time 头出现时开始，在 USE/EOF/下一条目头时收束。"""

    def __init__(self) -> None:
        self.entries: list[SlowEntry] = []
        self.skipped = 0
        self.metrics: tuple[float, float, int, int] | None = None
        self.time_hint: str | None = None
        self.pending_time_hint: str | None = None
        self.statement_lines: list[str] = []

    def parse(self, text: str) -> tuple[list[SlowEntry], int]:
        for raw_line in text.splitlines():
            self._consume(raw_line.rstrip("\r"))
        self.flush()
        return self.entries, self.skipped

    def _consume(self, line: str) -> None:
        if line.startswith("#"):
            self._consume_header(line)
            return
        if self._consume_control(line):
            return
        if line.strip() == "" and self.metrics is None:
            return
        self.statement_lines.append("" if line.strip() == "" else line)

    def _consume_header(self, line: str) -> None:
        # Query_time 出现即条目起点；其余字段按需提取，兼容 log_slow_extra 与老版本
        query_time = _METRIC_QUERY_TIME.search(line)
        if query_time:
            self._start_entry(line, query_time)
            return
        time_match = _HEADER_TIME.match(line)
        if time_match:
            self.time_hint = time_match.group(1)

    def _start_entry(self, line: str, query_time: re.Match[str]) -> None:
        self.flush()
        # 时间提示属于当前条目，起新条目时快照并复位
        self.pending_time_hint = self.time_hint
        self.time_hint = None
        lock = _METRIC_LOCK_TIME.search(line)
        sent = _METRIC_ROWS_SENT.search(line)
        examined = _METRIC_ROWS_EXAMINED.search(line)
        try:
            self.metrics = (
                float(query_time.group(1)),
                float(lock.group(1)) if lock else 0.0,
                int(sent.group(1)) if sent else 0,
                int(examined.group(1)) if examined else 0,
            )
        except ValueError:
            # 数值损坏时跳过该条目；正则可能放过 1.2.3 这类坏值
            self.metrics = None
            self.statement_lines = []
            self.skipped += 1

    def _consume_control(self, line: str) -> bool:
        set_match = _SET_TIMESTAMP.match(line)
        if set_match:
            # SET timestamp 仅在缺少日志头时间时作兜底
            if self.pending_time_hint is None:
                self.pending_time_hint = set_match.group(1)
            return True
        if _USE_LINE.match(line):
            # USE 终止当前条目，不进入语句本体
            self.flush()
            return True
        return False

    def flush(self) -> None:
        statement = "\n".join(self.statement_lines).strip()
        if self.metrics is not None and statement:
            query_time, lock_time, rows_sent, rows_examined = self.metrics
            self.entries.append(
                SlowEntry(
                    query_time=query_time,
                    lock_time=lock_time,
                    rows_sent=rows_sent,
                    rows_examined=rows_examined,
                    statement=statement,
                    time_hint=self.pending_time_hint,
                )
            )
        self.metrics = None
        self.statement_lines = []


def aggregate(entries: list[SlowEntry], *, top: int = 20) -> list[SlowAggregate]:
    """按指纹聚合：次数、累计/最大耗时、扫描行数、样本语句；按累计耗时降序。"""
    by_fingerprint: dict[str, SlowAggregate] = {}
    for entry in entries:
        key = entry.fingerprint
        agg = by_fingerprint.get(key)
        if agg is None:
            agg = SlowAggregate(fingerprint=key)
            by_fingerprint[key] = agg
        agg.count += 1
        agg.query_time_total += entry.query_time
        agg.query_time_max = max(agg.query_time_max, entry.query_time)
        agg.rows_examined_total += entry.rows_examined
        if not agg.sample:
            agg.sample = entry.statement
    ordered = sorted(by_fingerprint.values(), key=lambda a: a.query_time_total, reverse=True)
    return ordered[:top]


def analyze_slowlog(text: str, source_file: str, *, top: int = 20) -> SlowlogReport:
    entries, skipped = parse_slowlog(text)
    return SlowlogReport(
        source_file=source_file,
        entries_parsed=len(entries),
        skipped_lines=skipped,
        top=aggregate(entries, top=top),
    )


def read_slowlog_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
