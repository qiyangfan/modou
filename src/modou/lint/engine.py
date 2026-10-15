"""审核引擎：纯静态规则判定（AST），不连库、不启容器、不联网（宪法与 spec 同源）。

- 语句切分复用回放切分器（DELIMITER 感知，ADR-0004 同源：边界结论不依赖解析）；
- 行号定位用「空白不敏感的顺序扫描」：切分器保留语句内注释，直接 find 会因
  空白差异失配，归一化后顺序锚定既稳健又确定性；
- 解析失败快速失败（文件 + 行号），不产出半截报告（spec「语法错误快速失败」）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
import sqlglot.errors
import sqlglot.expressions as exp

from modou.replay.splitter import split_statements

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"


class LintParseError(Exception):
    """语句无法解析（输入错误，退出码 2）：指认文件与大致行号。"""

    def __init__(self, file: str, line: int, reason: str) -> None:
        super().__init__(f"{file}:{line}: unparseable statement: {reason}")
        self.file = file
        self.line = line
        self.reason = reason


@dataclass(frozen=True)
class Thresholds:
    """数值阈值（宪法口径：可配置，未配置用默认值）。"""

    in_list: int = 100
    offset: int = 10000
    index_count: int = 10


@dataclass
class Hit:
    rule_id: str
    level: str
    file: str
    line: int
    message: str
    suggestion: str


@dataclass(frozen=True)
class Rule:
    """单条规则：标识 + 级别 + 说明 + 判定函数（AST 节点访问，返回消息清单）。"""

    rule_id: str
    level: str
    description: str
    suggestion: str
    check: Callable[[exp.Expression, Thresholds], list[str]]


@dataclass
class LintResult:
    hits: list[Hit] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    statements: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.hits else 0


def lint_paths(
    paths: list[Path],
    rules: list[Rule],
    *,
    thresholds: Thresholds | None = None,
    disabled: set[str] | None = None,
) -> LintResult:
    """对文件/目录/变更集目录清单执行审核（目录递归收集 .sql 文件，输入路径去重）。"""
    resolved = thresholds or Thresholds()
    disabled_rules = disabled or set()
    result = LintResult()
    for path in _collect_sql_files(paths):
        text = path.read_text(encoding="utf-8")
        result.files.append(str(path))
        result.hits.extend(lint_sql_text(text, str(path), rules, thresholds=resolved, disabled=disabled_rules))
        result.statements += len(split_statements(text))
    return result


def lint_sql_text(
    text: str,
    filename: str,
    rules: list[Rule],
    *,
    thresholds: Thresholds | None = None,
    disabled: set[str] | None = None,
) -> list[Hit]:
    """审核单文件文本：切分 → 行号定位 → 解析 → 规则判定。"""
    resolved = thresholds or Thresholds()
    disabled_rules = disabled or set()
    statements = split_statements(text)
    if not statements:
        return []
    lines = _statement_start_lines(text, statements)
    hits: list[Hit] = []
    for statement, line in zip(statements, lines, strict=True):
        try:
            tree = sqlglot.parse_one(statement, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
        except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
            raise LintParseError(filename, line, str(exc).split("\n")[0]) from exc
        if tree is None:
            continue
        for rule in rules:
            if rule.rule_id in disabled_rules:
                continue
            for message in rule.check(tree, resolved):
                hits.append(
                    Hit(
                        rule_id=rule.rule_id,
                        level=rule.level,
                        file=filename,
                        line=line,
                        message=message,
                        suggestion=rule.suggestion,
                    )
                )
    return hits


def _collect_sql_files(paths: list[Path]) -> list[Path]:
    """文件直接收；目录递归收集 .sql（变更集目录 = 目录扫描，不做 manifest 校验）。

    按 resolve 后的绝对路径去重：同一文件经目录与显式路径重复给出时只审一次。
    """
    files: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        candidates = sorted(p for p in path.rglob("*.sql") if p.is_file()) if path.is_dir() else [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(candidate)
    return files


def _statement_start_lines(text: str, statements: list[str]) -> list[int]:
    """每条语句在文件中的起始行：空白不敏感顺序扫描（见模块注释）。"""
    positions: list[int] = []
    norm_chars: list[str] = []
    norm_positions: list[int] = []
    for index, ch in enumerate(text):
        if not ch.isspace():
            norm_chars.append(ch.lower())
            norm_positions.append(index)
    joined = "".join(norm_chars)

    def line_of(original_pos: int) -> int:
        return text.count("\n", 0, original_pos) + 1

    cursor = 0
    for statement in statements:
        needle = "".join(statement.split()).lower()[:64]
        if not needle:
            positions.append(1)
            continue
        found = joined.find(needle, cursor)
        if found < 0:
            # 理论不可达（语句文本必然来自本文件切分）；防御性兜底为上一位置
            positions.append(line_of(norm_positions[cursor]) if cursor < len(norm_positions) else 1)
            continue
        positions.append(line_of(norm_positions[found]))
        cursor = found + len(needle)
    return positions


def render_text(result: LintResult) -> str:
    """人读文本（中文正文）：逐命中列规则、级别、位置与建议。"""
    lines: list[str] = ["墨斗审核报告", "＝" * 40]
    if not result.hits:
        lines.append("无命中：输入未触发任何已启用规则。")
    level_labels = {LEVEL_ERROR: "错误", LEVEL_WARNING: "警告", LEVEL_INFO: "提示"}
    for hit in result.hits:
        lines.append(f"  [{level_labels.get(hit.level, hit.level)}] {hit.rule_id} {hit.file}:{hit.line}")
        lines.append(f"      {hit.message}")
        lines.append(f"      建议：{hit.suggestion}")
    lines.append("")
    by_level = {
        level: sum(1 for h in result.hits if h.level == level) for level in (LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO)
    }
    lines.append(
        f"汇总：命中 {len(result.hits)} 条（错误 {by_level[LEVEL_ERROR]} · "
        f"警告 {by_level[LEVEL_WARNING]} · 提示 {by_level[LEVEL_INFO]}）"
    )
    lines.append(f"退出码：{result.exit_code}（0=无命中，1=存在命中，2=环境或输入错误）")
    return "\n".join(lines)


def result_to_json(result: LintResult) -> dict:
    return {
        "report_kind": "lint",
        "report_version": 1,
        "exit_code": result.exit_code,
        "summary": {
            "hits": len(result.hits),
            "error": sum(1 for h in result.hits if h.level == LEVEL_ERROR),
            "warning": sum(1 for h in result.hits if h.level == LEVEL_WARNING),
            "info": sum(1 for h in result.hits if h.level == LEVEL_INFO),
            "files": len(result.files),
        },
        "hits": [
            {
                "rule_id": h.rule_id,
                "level": h.level,
                "file": h.file,
                "line": h.line,
                "message": h.message,
                "suggestion": h.suggestion,
            }
            for h in result.hits
        ],
    }
