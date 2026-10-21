"""纯静态 SQL 审核引擎：不连库、不启容器、不联网。

解析失败的语句记为 PARSE.001，其他语句继续审核；语句切分复用回放切分器。
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

# 工具命中：语句无法解析。它不是规则，但走同一命中与跳过机制，让覆盖缺口可见。
PARSE_RULE_ID = "PARSE.001"
PARSE_SUGGESTION = "人工复核该语句的影响；确认无需机器审核后可用 --skip-rule PARSE.001 关闭此类提示。"


@dataclass(frozen=True)
class Thresholds:
    """规则数值阈值，可由配置文件覆盖。"""

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
    """一条规则：标识、级别、说明与判定函数。"""

    rule_id: str
    level: str
    description: str
    suggestion: str
    check: Callable[[exp.Expression, Thresholds], list[str]]


@dataclass
class ResidualStatement:
    """解析成功且规则零命中的语句，与 hits 同趟产出。"""

    file: str
    line: int
    sql: str


@dataclass
class LintResult:
    hits: list[Hit] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    statements: int = 0
    residuals: list[ResidualStatement] = field(default_factory=list)

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
    """审核文件或目录（路径去重），单趟产出命中与残留语句。"""
    resolved = thresholds or Thresholds()
    disabled_rules = disabled or set()
    result = LintResult()
    for path in _collect_sql_files(paths):
        text = path.read_text(encoding="utf-8")
        result.files.append(str(path))
        hits, residuals = _lint_file(text, str(path), rules, resolved, disabled_rules)
        result.hits.extend(hits)
        result.residuals.extend(
            ResidualStatement(file=str(path), line=line, sql=statement) for line, statement in residuals
        )
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
    """审核一段 SQL 文本并返回命中。"""
    resolved = thresholds or Thresholds()
    disabled_rules = disabled or set()
    hits, _ = _lint_file(text, filename, rules, resolved, disabled_rules)
    return hits


def residual_statements(
    text: str,
    rules: list[Rule],
    *,
    thresholds: Thresholds | None = None,
    disabled: set[str] | None = None,
) -> list[tuple[int, str]]:
    """返回解析成功且未命中规则的语句，供 AI 分析；解析失败由 PARSE.001 披露。"""
    resolved = thresholds or Thresholds()
    disabled_rules = disabled or set()
    _, residuals = _lint_file(text, "", rules, resolved, disabled_rules)
    return residuals


def _lint_file(
    text: str,
    filename: str,
    rules: list[Rule],
    thresholds: Thresholds,
    disabled_rules: set[str],
) -> tuple[list[Hit], list[tuple[int, str]]]:
    """单文件单趟判定，同时产出命中与残留语句。"""
    statements = split_statements(text)
    if not statements:
        return [], []
    lines = _statement_start_lines(text, statements)
    hits: list[Hit] = []
    residual: list[tuple[int, str]] = []
    for statement, line in zip(statements, lines, strict=True):
        findings, parse_ok, parse_error = _judge_statement(statement, rules, thresholds, disabled_rules)
        if not parse_ok:
            if PARSE_RULE_ID not in disabled_rules:
                hits.append(_parse_hit(filename, line, parse_error or ""))
            continue
        if findings:
            hits.extend(_hits_from_findings(findings, filename, line))
        else:
            residual.append((line, statement))
    return hits, residual


def _judge_statement(
    statement: str,
    rules: list[Rule],
    thresholds: Thresholds,
    disabled_rules: set[str],
) -> tuple[list[tuple[Rule, str]], bool, str | None]:
    """判定单条语句，返回命中、解析状态和解析错误首行。"""
    try:
        tree = sqlglot.parse_one(statement, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        # 空消息没有首行，返回空字符串。
        return [], False, (str(exc).splitlines() or [""])[0]
    if tree is None:
        return [], True, None
    findings: list[tuple[Rule, str]] = []
    for rule in rules:
        if rule.rule_id in disabled_rules:
            continue
        for message in rule.check(tree, thresholds):
            findings.append((rule, message))
    return findings, True, None


def _parse_hit(filename: str, line: int, parse_error: str) -> Hit:
    detail = f"：{parse_error}" if parse_error else ""
    return Hit(
        rule_id=PARSE_RULE_ID,
        level=LEVEL_WARNING,
        file=filename,
        line=line,
        message=f"语句无法解析，未纳入机器审核{detail}",
        suggestion=PARSE_SUGGESTION,
    )


def _hits_from_findings(findings: list[tuple[Rule, str]], filename: str, line: int) -> list[Hit]:
    return [
        Hit(
            rule_id=rule.rule_id,
            level=rule.level,
            file=filename,
            line=line,
            message=message,
            suggestion=rule.suggestion,
        )
        for rule, message in findings
    ]


def _collect_sql_files(paths: list[Path]) -> list[Path]:
    """收集文件和目录中的 .sql 文件，并按解析后的绝对路径去重。"""
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
    """按空白不敏感的顺序扫描，定位每条语句的起始行。"""
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
            # 理论不可达：语句来自本文件切分；兜底为上一位置
            positions.append(line_of(norm_positions[cursor]) if cursor < len(norm_positions) else 1)
            continue
        positions.append(line_of(norm_positions[found]))
        cursor = found + len(needle)
    return positions


def render_text(result: LintResult) -> str:
    """生成中文人读报告，逐条列出命中与建议。"""
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
