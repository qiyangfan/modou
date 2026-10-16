"""审核引擎：纯静态规则判定（AST），不连库、不启容器、不联网（宪法与 spec 同源）。

- 语句切分复用回放切分器（DELIMITER 感知，ADR-0004 同源：边界结论不依赖解析）；
- 行号定位用「空白不敏感的顺序扫描」：切分器保留语句内注释，直接 find 会因
  空白差异失配，归一化后顺序锚定既稳健又确定性；
- 解析失败逐语句记录为工具命中（PARSE.001，指认文件与行号、计入汇总与退出码），
  其余语句照常审核，整轮不中断；非静默——可经既有跳过机制显式关闭
  （spec 2026-10-15 修订：真实迁移链存在解析器不支持但合法的语法形态，
  如版本条件注释与存储过程体，整体中止会把局部解析缺口放大成零审计覆盖）。
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

# 工具命中：语句无法解析（解析器不支持该语法形态）。非 SOAR 规则，但占用同一
# 命中通道与跳过机制，保证「覆盖缺口」对调用方可见且可治理。
PARSE_RULE_ID = "PARSE.001"
PARSE_SUGGESTION = "人工复核该语句的影响；确认无需机器审核后可用 --skip-rule PARSE.001 关闭此类提示。"


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
class ResidualStatement:
    """残留语句：解析成功且规则零命中（AI 残留评审的输入面，与 hits 同趟产出）。"""

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
    """对文件/目录/变更集目录清单执行审核（目录递归收集 .sql 文件，输入路径去重）。

    单趟产出命中与残留面（评审 AI 的输入与规则判定同源，无二次读文件/二次判定）。
    """
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
    """审核单文件文本：切分 → 行号定位 → 解析 → 规则判定。"""
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
    """AI 残留评审的输入面：解析成功且规则零命中的语句（[(行号, 语句文本)]）。

    规则覆盖不到的残留即 AI 分析师的职责面；不可解析语句不进残留
    （机器无法判定其语义，已由 PARSE.001 披露覆盖缺口）。
    """
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
    """单文件单趟判定：命中与残留面同源产出（评审 AI 不重读文件、不重跑规则）。"""
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
    """单语句判定核心（lint_sql_text 与 residual_statements 共用）：
    返回（(规则, 消息) 清单, 是否解析成功, 解析错误首行）。"""
    try:
        tree = sqlglot.parse_one(statement, read="mysql", error_level=sqlglot.ErrorLevel.RAISE)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        # splitlines 对空消息返回空列表（旧 split("\n") 实现不会因此崩），兜底保住旧行为
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
