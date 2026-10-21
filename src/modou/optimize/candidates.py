"""分析慢 SQL 的 AST，产出确定性发现与索引候选。

发现是事实；候选须经影子库实证才能标为实测提升。OR 分支不生成组合索引候选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

from modou.snapshot.model import ColumnDef, TableDef
from modou.snapshot.sample import TEXT_PREFIX_LENGTH

# 每语句候选上限，约束影子实证成本；每个候选需建索引并两次 ANALYZE
MAX_CANDIDATES_PER_STATEMENT = 5
# 候选索引最多列数；列数再多区分度通常骤降
MAX_CANDIDATE_COLUMNS = 4

_EQUALITY_KINDS = (exp.EQ, exp.In, exp.Like)
_RANGE_KINDS = (exp.GT, exp.GTE, exp.LT, exp.LTE)
_COMPARISON_KINDS = _EQUALITY_KINDS + _RANGE_KINDS

# 不影响列值的中性包裹：只分组或翻转语义，不算函数/运算
_NEUTRAL_WRAPPERS = (exp.Not, exp.Paren, exp.In, exp.Like, exp.Is, exp.Between, exp.Exists)
# 会让索引失效的算术运算
_WRAPPING_KINDS = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)

_NON_WORD_PATTERN = re.compile(r"\W")


class StatementTypeError(Exception):
    """输入不是慢 SQL 支持的语句类型（SELECT/UPDATE/DELETE），映射输入错误。"""


@dataclass
class Finding:
    """确定性发现，无需实证的结论。"""

    code: str
    message: str


@dataclass
class IndexCandidate:
    """优化候选：索引（库/表/列）或改写 SQL。"""

    database: str | None
    table: str
    columns: list[str]
    reason: str
    source: str = "rule"  # rule / ai
    kind: str = "index"  # index / rewrite
    sql: str = ""


@dataclass
class StatementAnalysis:
    sql: str
    database: str | None
    table: str
    is_select: bool = False
    findings: list[Finding] = field(default_factory=list)
    candidates: list[IndexCandidate] = field(default_factory=list)
    # 语句引用的全部 (库, 表)，库已按 default_database 归一，供快照覆盖校验
    referenced_tables: list[tuple[str, str]] = field(default_factory=list)


def analyze_statement(sql: str, default_database: str | None) -> StatementAnalysis:
    """解析单条语句，产出发现与规则候选；解析失败或类型不支持时抛错。"""
    try:
        tree = sqlglot.parse_one(sql, read="mysql")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"unparseable statement: {exc}") from exc
    if tree is None or not isinstance(tree, (exp.Select, exp.Update, exp.Delete)):
        raise StatementTypeError("only SELECT/UPDATE/DELETE statements are supported for optimization")

    main_table = _main_table(tree)
    tables, alias_map = _collect_tables(tree, default_database)
    main_name = main_table.name if main_table is not None else "?"
    main_db = _resolve_db(main_table, default_database)

    analysis = StatementAnalysis(sql=sql, database=main_db, table=main_name, is_select=isinstance(tree, exp.Select))
    analysis.referenced_tables = sorted(set(alias_map.values()), key=lambda t: (t[0] or "", t[1]))
    preds = _PredicateCollector(alias_map, tables, default_database, analysis)

    for join in tree.args.get("joins", []) or []:
        on = join.args.get("on")
        if on is not None:
            preds.collect_comparison(on)
    where = tree.args.get("where")
    if where is None or where.this is None:
        analysis.findings.append(Finding("NO_WHERE", "语句未带 WHERE 条件，将全表扫描或全表修改"))
    else:
        preds.collect_conjuncts(where.this)

    if isinstance(tree, exp.Select):
        preds.collect_order_by(tree.args.get("order"))
    analysis.candidates = preds.build_candidates(main_table)
    return analysis


class _PredicateCollector:
    """从连接条件和 WHERE 合取式中提取谓词列，按表聚合候选。"""

    def __init__(
        self,
        alias_map: dict[str, tuple[str | None, str]],
        tables: set[str],
        default_database: str | None,
        analysis: StatementAnalysis,
    ) -> None:
        # 等值列按表累积；范围谓词只取首列
        self._equality: dict[tuple[str | None, str], list[str]] = {}
        self._range: dict[tuple[str | None, str], list[str]] = {}
        self._order_columns: tuple[str | None, str, list[str]] | None = None
        self._alias_map = alias_map
        self._tables = tables
        self._default_database = default_database
        self._analysis = analysis

    # ── 提取 ──────────────────────────────────────────────────────────

    def collect_conjuncts(self, condition: exp.Expression) -> None:
        for conjunct in _flatten_and(condition):
            if _contains_or(conjunct):
                self._analysis.findings.append(
                    Finding("OR_CONDITION", "WHERE 中存在 OR 条件：同列等值 OR 建议改写 IN，跨列 OR 索引难以命中")
                )
                continue
            self.collect_comparison(conjunct)

    def collect_comparison(self, node: exp.Expression) -> None:
        if isinstance(node, exp.And):
            self.collect_conjuncts(node)
            return
        if isinstance(node, exp.Between):
            # BETWEEN 可走索引，不应报为索引失效。
            if isinstance(node.this, exp.Column):
                if not (_contains_column(node.args.get("low")) or _contains_column(node.args.get("high"))):
                    self._add_predicate(node.this, node, is_range=True)
            else:
                # 左值被包裹（如 ABS(a) BETWEEN ...），仍需报告
                self._report_wrapped(node)
            return
        if not isinstance(node, _COMPARISON_KINDS):
            # 非「列 vs 值」比较：只在列被函数/运算包裹时报发现；IS NULL、NOT 等可走索引
            self._report_wrapped(node)
            return

        this, other = node.this, node.expression
        this_is_column = isinstance(this, exp.Column)
        if isinstance(node, exp.Like):
            self._collect_like(this, other)
            return
        if this_is_column and not _contains_column(other):
            self._add_predicate(this, node, is_range=isinstance(node, _RANGE_KINDS))
            return
        if (
            not this_is_column
            and isinstance(other, exp.Column)
            and isinstance(this, (exp.Literal, exp.Placeholder, exp.Parameter))
        ):
            # 值在左侧的写法（'x' = col）同样成立
            self._add_predicate(other, node, is_range=isinstance(node, _RANGE_KINDS))
            return
        if this_is_column and isinstance(other, exp.Column):
            # 列对列：两侧各记一个等值列，连接和过滤都能受益
            self._add_column_equality(this)
            self._add_column_equality(other)
            return
        # 其余形态只对真被包裹的列报发现
        self._report_wrapped(node)

    def _report_wrapped(self, node: exp.Expression) -> None:
        """对列被函数或运算包裹的谓词产出 FUNCTION_ON_COLUMN。"""
        wrapped = [col.name for col in node.find_all(exp.Column) if _is_wrapped_column(col, node)]
        if wrapped:
            self._analysis.findings.append(
                Finding("FUNCTION_ON_COLUMN", f"谓词对列施加函数或运算（{wrapped[0]} 等），索引失效")
            )

    def _collect_like(self, this: object, pattern: object) -> None:
        if not isinstance(this, exp.Column):
            if _contains_column(this):
                self._analysis.findings.append(Finding("FUNCTION_ON_COLUMN", "LIKE 左侧对列施加函数或运算，索引失效"))
            return
        if isinstance(pattern, exp.Literal) and isinstance(pattern.this, str):
            text = pattern.this
            if text.startswith("%") or text.startswith("_"):
                self._analysis.findings.append(
                    Finding("FULL_WILDCARD_LIKE", f"列 {this.name} 的 LIKE 模式以通配符开头，无法走索引")
                )
                return
            self._add_predicate(this, None, is_range=False)
            return
        self._add_predicate(this, None, is_range=False)

    def _add_predicate(self, column: exp.Column, node: exp.Expression | None, *, is_range: bool) -> None:
        target = self._resolve_target(column)
        if target is None:
            return
        bucket = self._range if is_range else self._equality
        columns = bucket.setdefault(target, [])
        if column.name not in columns:
            columns.append(column.name)

    def _add_column_equality(self, column: exp.Column) -> None:
        self._add_predicate(column, None, is_range=False)

    def collect_order_by(self, order: exp.Expression | None) -> None:
        if order is None:
            return
        columns = [
            expr.this.name
            for expr in order.expressions
            if isinstance(expr, exp.Ordered) and isinstance(expr.this, exp.Column)
        ]
        if columns:
            main = _main_table_key(self._analysis)
            self._order_columns = (main[0], main[1], columns)

    # ── 聚合 ──────────────────────────────────────────────────────────

    def build_candidates(self, main_table: exp.Table | None) -> list[IndexCandidate]:
        candidates: list[IndexCandidate] = []
        seen: set[tuple[str | None, str, tuple[str, ...]]] = set()
        targets = sorted(
            {*self._equality.keys(), *self._range.keys(), *([self._order_columns[:2]] if self._order_columns else [])},
            key=lambda t: (t[0] or "", t[1]),
        )
        if main_table is None and self._analysis.table == "?":
            # 派生表或无表形态的主表键 "?" 是哨兵，不产候选
            sentinel = _main_table_key(self._analysis)
            targets = [t for t in targets if t != sentinel]
        for target in targets:
            columns: list[str] = []
            for col in self._equality.get(target, []):
                if col not in columns:
                    columns.append(col)
            range_columns = self._range.get(target, [])
            if range_columns:
                if range_columns[0] not in columns:
                    columns.append(range_columns[0])
            elif self._order_columns is not None and self._order_columns[:2] == target:
                for col in self._order_columns[2]:
                    if col not in columns:
                        columns.append(col)
            columns = columns[:MAX_CANDIDATE_COLUMNS]
            if not columns:
                continue
            key = (target[0], target[1], tuple(columns))
            if key in seen:
                continue
            seen.add(key)
            reason = _candidate_reason(self._equality.get(target, []), self._range.get(target, []))
            candidates.append(IndexCandidate(database=target[0], table=target[1], columns=columns, reason=reason))
        return candidates[:MAX_CANDIDATES_PER_STATEMENT]

    def _resolve_target(self, column: exp.Column) -> tuple[str | None, str] | None:
        qualifier = column.table
        if qualifier:
            target = self._alias_map.get(qualifier)
            if target is None:
                # 未知限定名：若与已知表同名则按该表处理
                if qualifier in self._tables:
                    return (self._default_database, qualifier)
                return None
            return target
        # 无限定列：归属主表
        main = _main_table_key(self._analysis)
        return main


def _flatten_and(condition: exp.Expression) -> list[exp.Expression]:
    """展开顶层 AND；OR 子树整体返回，由调用方处理。"""
    if isinstance(condition, exp.And):
        return _flatten_and(condition.this) + _flatten_and(condition.expression)
    return [condition]


def _contains_or(condition: exp.Expression) -> bool:
    return any(isinstance(node, exp.Or) for node in condition.walk())


def _contains_column(node: exp.Expression | None) -> bool:
    return node is not None and any(isinstance(child, exp.Column) for child in node.walk())


def _is_wrapped_column(column: exp.Column, root: exp.Expression) -> bool:
    """判断列到比较根之间是否有函数或运算；不计中性包裹，不跨查询边界。"""
    parent = column.parent
    seen_wrapper = False
    while parent is not None and parent is not root:
        if isinstance(parent, (exp.Select, exp.Union, exp.Subquery)):
            return False
        if not seen_wrapper and isinstance(parent, (*exp.Func.__subclasses__(), *_WRAPPING_KINDS)):  # type: ignore[arg-type]
            seen_wrapper = True
        parent = parent.parent
    return seen_wrapper


def _main_table(tree: exp.Expression) -> exp.Table | None:
    if isinstance(tree, (exp.Update, exp.Delete)):
        this = tree.this
        return this if isinstance(this, exp.Table) else None
    if isinstance(tree, exp.Select):
        from_clause = tree.args.get("from_") or tree.args.get("from")
        if from_clause is not None:
            this = from_clause.this
            return this if isinstance(this, exp.Table) else None
    return None


def _main_table_key(analysis: StatementAnalysis) -> tuple[str | None, str]:
    return (analysis.database, analysis.table)


def _collect_tables(
    tree: exp.Expression, default_database: str | None
) -> tuple[set[str], dict[str, tuple[str | None, str]]]:
    """收集引用的表与别名；未限定库名归属 default_database，CTE 不算快照表。"""
    cte_names = {alias.name for cte in tree.find_all(exp.CTE) if (alias := cte.args.get("alias")) is not None}
    names: set[str] = set()
    alias_map: dict[str, tuple[str | None, str]] = {}
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name or name in cte_names:
            continue
        names.add(name)
        db = table.db or default_database
        alias = table.alias_or_name
        alias_map[alias] = (db, name)
        alias_map[name] = (db, name)
    return names, alias_map


def _resolve_db(table: exp.Table | None, default_database: str | None) -> str | None:
    if table is None:
        return default_database
    return table.db or default_database


def _candidate_reason(equality: list[str], range_columns: list[str]) -> str:
    parts = []
    if equality:
        parts.append(f"等值谓词列 {', '.join(equality)}")
    if range_columns:
        parts.append(f"范围谓词列 {range_columns[0]}")
    return "；".join(parts)


def is_covered_by_existing(columns: list[str], table: TableDef) -> str | None:
    """返回覆盖候选列序列的既有索引名，没有则返回 None。"""
    for index in table.indexes:
        existing = [part.column for part in index.parts if part.column]
        if existing[: len(columns)] == columns:
            return index.name
    return None


def index_name_for_candidate(columns: list[str]) -> str:
    """生成 idx_ 前缀的候选索引名，建索引和删索引共用。"""
    sanitized = _NON_WORD_PATTERN.sub("_", "_".join(columns))[:56].strip("_") or "cols"
    return f"idx_{sanitized}"


def build_index_ddl(candidate: IndexCandidate, columns_meta: dict[str, ColumnDef] | None = None) -> str:
    """生成候选索引 DDL；TEXT/BLOB 列带前缀长度。"""
    meta = columns_meta or {}

    def quote(name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    rendered = []
    for col in candidate.columns:
        column_type = meta.get(col).column_type if col in meta else ""
        prefix = ""
        if column_type.lower().startswith(
            ("text", "blob", "tinytext", "tinyblob", "mediumtext", "mediumblob", "longtext", "longblob")
        ):
            prefix = f"({TEXT_PREFIX_LENGTH})"
        rendered.append(quote(col) + prefix)
    index_name = index_name_for_candidate(candidate.columns)
    target = (
        quote(candidate.table)
        if candidate.database is None
        else f"{quote(candidate.database)}.{quote(candidate.table)}"
    )
    return f"ALTER TABLE {target} ADD INDEX {quote(index_name)} ({', '.join(rendered)})"
