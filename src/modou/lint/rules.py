"""首批规则库：SOAR 高频反模式子集 26 条（ID 沿用 SOAR 编号，降低迁移心智）。

选型依据（change design §1/§2）：SOAR 125 条中约 120 条为纯静态判定；首批取
SOAR × Bytebase 共识高频反模式，全部单树 AST 可判定（sqlglot，唯一解析器）。
排除需 schema/连库/流程性的 ARG.003、KEY.009、SEC.003。文档见 docs/rules.md。
"""

from __future__ import annotations

from collections.abc import Iterator

import sqlglot.expressions as exp

from modou.lint.engine import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARNING, Rule, Thresholds

# ── 判定辅助 ────────────────────────────────────────────────────────────────

_INT_DTYPE_NAMES = {
    "INT",
    "INTEGER",
    "TINYINT",
    "SMALLINT",
    "MEDIUMINT",
    "BIGINT",
    # BIGINT UNSIGNED 等：sqlglot 归一为 U 前缀类型
    "UINT",
    "UTINYINT",
    "USMALLINT",
    "UMEDIUMINT",
    "UBIGINT",
    # MySQL 整型别名：SERIAL = BIGINT UNSIGNED NULL AUTO_INCREMENT UNIQUE，
    # BOOLEAN/BOOL = TINYINT(1)
    "SERIAL",
    "BOOLEAN",
    "BOOL",
}
_TIMESTAMP_DTYPE_NAMES = {"TIMESTAMP", "TIMESTAMPTZ"}
_CHAR_DTYPE_NAMES = {"VARCHAR", "CHAR", "NVARCHAR", "TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT"}
_PASSWORD_NAMES = {"password", "passwd", "pwd", "pass", "userpass", "user_pass", "login_password"}
_HASH_MARKERS = ("hash", "md5", "sha", "digest", "token")
_COMPARISON_NODES = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.In)
_ARITHMETIC_NODES = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)


def _column_defs(tree: exp.Expression) -> list[exp.ColumnDef]:
    """CREATE TABLE 的列定义清单（非建表语句返回空）。"""
    if not isinstance(tree, exp.Create) or tree.kind != "TABLE":
        return []
    schema = tree.this
    if not isinstance(schema, exp.Schema):
        return []
    return [e for e in schema.expressions if isinstance(e, exp.ColumnDef)]


def _table_constraints(tree: exp.Expression) -> list[exp.Expression]:
    if not isinstance(tree, exp.Create) or tree.kind != "TABLE":
        return []
    schema = tree.this
    if not isinstance(schema, exp.Schema):
        return []
    return [e for e in schema.expressions if not isinstance(e, exp.ColumnDef)]


def _flattened_table_constraints(tree: exp.Expression) -> list[exp.Expression]:
    """表级约束的展平视图：具名 `CONSTRAINT <名> PRIMARY KEY/UNIQUE/KEY` 在 sqlglot
    里是 exp.Constraint（名字在 this，真实约束在 expressions），mysqldump 高频形态
    ——不解包会被 KEY.002/005/007 整体漏判。"""
    flattened: list[exp.Expression] = []
    for constraint in _table_constraints(tree):
        if isinstance(constraint, exp.Constraint):
            flattened.extend(constraint.args.get("expressions") or [])
        else:
            flattened.append(constraint)
    return flattened


def _dtype_name(coldef: exp.ColumnDef) -> str:
    kind = coldef.args.get("kind")
    if kind is None or getattr(kind, "this", None) is None:
        return ""
    return str(kind.this.name) if hasattr(kind.this, "name") else str(kind.this)


def _constraint_kinds(coldef: exp.ColumnDef) -> list[exp.Expression]:
    return [c.args["kind"] for c in (coldef.constraints or []) if c.args.get("kind") is not None]


def _has_constraint_of(coldef: exp.ColumnDef, constraint_type: type) -> bool:
    return any(isinstance(k, constraint_type) for k in _constraint_kinds(coldef))


def _index_column_name(index: exp.Expression) -> str:
    """索引约束的显式名：普通 KEY 的 this 是 Identifier；UNIQUE KEY 的 this 是
    Schema（this=名称 Identifier, expressions=列）。"""
    this = index.args.get("this")
    if isinstance(this, exp.Schema):
        return this.this.name if isinstance(this.this, exp.Identifier) else ""
    return this.name if isinstance(this, exp.Identifier) else ""


def _naming_pairs(tree: exp.Expression) -> list[tuple[str, str]]:
    """(索引名, 期望前缀) 清单：表级 UNIQUE KEY（uk_）与普通 KEY（idx_），
    含具名 `CONSTRAINT <名> UNIQUE/KEY` 形态（约束名即索引名）。

    FULLTEXT/SPATIAL（args.kind 标注）命名不属 idx_/uk_ 口径，豁免；列级
    UNIQUE 由 MySQL 自动命名（无显式名可查），不参与判定。
    """
    pairs: list[tuple[str, str]] = []

    def fulltext_or_spatial(node: exp.Expression) -> bool:
        return str(node.args.get("kind") or "").upper() in ("FULLTEXT", "SPATIAL")

    for constraint in _table_constraints(tree):
        if isinstance(constraint, exp.Constraint):
            name = constraint.this.name if isinstance(constraint.this, exp.Identifier) else ""
            for inner in constraint.args.get("expressions") or []:
                if isinstance(inner, exp.UniqueColumnConstraint):
                    pairs.append((name, "uk_"))
                elif isinstance(inner, exp.IndexColumnConstraint) and not fulltext_or_spatial(inner):
                    pairs.append((name, "idx_"))
        elif isinstance(constraint, exp.UniqueColumnConstraint):
            pairs.append((_index_column_name(constraint), "uk_"))
        elif isinstance(constraint, exp.IndexColumnConstraint) and not fulltext_or_spatial(constraint):
            pairs.append((_index_column_name(constraint), "idx_"))
    return pairs


def _wrapped_predicate_columns(node: exp.Expression | None) -> list[exp.Column]:
    """比较节点两侧被函数/运算实际包裹的列（去重，保持出现顺序）。

    逐包裹节点收集其内部列，而非收集全部列再判包裹——保证消息只归属真实
    被包裹的列（`a = b + 1` 只指认 b，不误述裸列 a）；越过查询边界（子查询/
    集合操作）的包裹属于嵌套查询自己的谓词，不归本层比较。
    """
    if node is None:
        return []

    def prune_nested_query(n: exp.Expression) -> bool:
        return isinstance(n, (exp.Select, exp.Union, exp.Subquery)) and n is not node

    seen: set[int] = set()
    columns: list[exp.Column] = []
    for sub in node.walk(prune=prune_nested_query):
        if not isinstance(sub, (*exp.Func.__subclasses__(), *_ARITHMETIC_NODES)):  # type: ignore[arg-type]
            continue
        for col in sub.find_all(exp.Column):
            if id(col) not in seen:
                seen.add(id(col))
                columns.append(col)
    return columns


def _is_prefix_wildcard_like(like: exp.Expression) -> bool:
    return (
        isinstance(like.this, exp.Column)
        and isinstance(like.expression, exp.Literal)
        and isinstance(like.expression.this, str)
        and like.expression.this[:1] in ("%_")
    )


def _pk_column_name(pk_part: exp.Expression) -> str:
    """主键列名：不同 sqlglot 版本下可能是 Column 或 Identifier，取 name 统一口径。"""
    return pk_part.name if hasattr(pk_part, "name") else ""


def _has_pk_or_unique(tree: exp.Expression) -> bool:
    """建表语句是否声明了主键或唯一键（列级、表级、具名 CONSTRAINT 形态都要看）。

    sqlglot 形态：`id INT PRIMARY KEY` 是 ColumnDef 上的 PrimaryKeyColumnConstraint，
    表级 PRIMARY KEY 是 exp.PrimaryKey，UNIQUE（列级与表级 UNIQUE KEY 同形）是
    UniqueColumnConstraint，`CONSTRAINT <名> PRIMARY KEY/UNIQUE` 是 exp.Constraint
    包裹（见 _flattened_table_constraints）——只看表级约束会漏掉最常见的列级写法。
    """
    for coldef in _column_defs(tree):
        if _has_constraint_of(coldef, (exp.PrimaryKeyColumnConstraint, exp.UniqueColumnConstraint)):
            return True
    return any(isinstance(c, (exp.PrimaryKey, exp.UniqueColumnConstraint)) for c in _flattened_table_constraints(tree))


def _pk_column_defs(tree: exp.Expression) -> list[exp.ColumnDef]:
    """主键列的列定义（列级 PRIMARY KEY + 表级/具名 CONSTRAINT PRIMARY KEY 归一）。"""
    by_name = {coldef.name: coldef for coldef in _column_defs(tree)}
    names = [coldef.name for coldef in _column_defs(tree) if _has_constraint_of(coldef, exp.PrimaryKeyColumnConstraint)]
    for constraint in _flattened_table_constraints(tree):
        if isinstance(constraint, exp.PrimaryKey):
            names.extend(name for name in (_pk_column_name(e) for e in constraint.expressions) if name)
    seen: set[str] = set()
    coldefs: list[exp.ColumnDef] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        coldef = by_name.get(name)
        if coldef is not None:
            coldefs.append(coldef)
    return coldefs


def _secondary_index_count(tree: exp.Expression) -> int:
    """建表语句声明的二级索引数：表级 KEY/UNIQUE KEY（含 FULLTEXT/SPATIAL，含具名
    CONSTRAINT 形态）+ 列级 UNIQUE。列级 UNIQUE 同样建二级索引；主键不计。"""
    count = sum(
        1
        for c in _flattened_table_constraints(tree)
        if isinstance(c, (exp.IndexColumnConstraint, exp.UniqueColumnConstraint))
    )
    count += sum(1 for coldef in _column_defs(tree) if _has_constraint_of(coldef, exp.UniqueColumnConstraint))
    return count


# ── 规则清单（26 条，顺序即输出顺序）────────────────────────────────────────

RULES: list[Rule] = [
    Rule(
        "ARG.001",
        LEVEL_WARNING,
        "LIKE 前缀通配符",
        "无法走索引；确需模糊匹配请用搜索引擎或覆盖索引+延迟关联",
        lambda tree, th: [
            f"列 {like.this.name} 的 LIKE 模式以通配符开头（{like.expression.this!r}），索引失效"
            for like in tree.find_all(exp.Like)
            if not like.args.get("negate") and _is_prefix_wildcard_like(like)
        ],
    ),
    Rule(
        "ARG.004",
        LEVEL_ERROR,
        "IN (NULL) 恒不为真",
        "IN 列表中出现 NULL 使整个条件永假，疑似笔误",
        lambda tree, th: [
            "IN 列表包含 NULL 字面量：条件恒不为真"
            for node in _iter_in(tree)
            if not node.args.get("negate") and any(isinstance(e, exp.Null) for e in node.expressions)
        ],
    ),
    Rule(
        "ARG.005",
        LEVEL_WARNING,
        "IN 列表元素过多",
        "超长 IN 列表建议改临时表 JOIN 或分批",
        lambda tree, th: [
            f"IN 列表含 {len(node.expressions)} 个元素（阈值 {th.in_list}）"
            for node in _iter_in(tree)
            if len(node.expressions) > th.in_list
        ],
    ),
    Rule(
        "ARG.006",
        LEVEL_INFO,
        "对列判 NULL",
        "IS NULL 可能全表扫描；可考虑默认值语义替代",
        lambda tree, th: [
            f"列 {node.this.name} 使用 IS [NOT] NULL 判定"
            for node in tree.find_all(exp.Is)
            if isinstance(node.this, exp.Column)
        ],
    ),
    Rule(
        "ARG.011",
        LEVEL_WARNING,
        "负向查询",
        "NOT IN / NOT LIKE 通常退化为全表扫描",
        lambda tree, th: [
            "NOT IN / NOT LIKE 负向条件无法有效利用索引"
            for node in tree.walk()
            if (isinstance(node, exp.Not) and isinstance(node.this, (exp.In, exp.Like)))
            or (isinstance(node, exp.Like) and node.args.get("negate"))
            or (isinstance(node, exp.In) and node.args.get("negate"))
        ],
    ),
    Rule(
        "CLA.001",
        LEVEL_WARNING,
        "SELECT 无 WHERE",
        "全表扫描确认是否必要；大表请加分页或过滤条件",
        lambda tree, th: [
            "SELECT 语句无 WHERE 条件，将全表扫描"
            for node in [tree]
            if isinstance(node, exp.Select) and node.args.get("from_") is not None and node.args.get("where") is None
        ],
    ),
    Rule(
        "CLA.002",
        LEVEL_ERROR,
        "ORDER BY RAND()",
        "随机排序需全表计算，效率极低；用应用侧随机或随机主键法",
        lambda tree, th: [
            "ORDER BY RAND() 需对全部结果集随机计算"
            for order in tree.find_all(exp.Order)
            for expr in order.expressions
            if isinstance(expr.this, exp.Rand)
        ],
    ),
    Rule(
        "CLA.003",
        LEVEL_WARNING,
        "大 OFFSET 分页",
        "深翻页扫描并丢弃 offset 行；建议书签（keyset）分页",
        lambda tree, th: (
            [_offset_message(tree, th)] if _offset_value(tree) is not None and _offset_value(tree) > th.offset else []
        ),
    ),
    Rule(
        "CLA.015",
        LEVEL_ERROR,
        "UPDATE 无 WHERE",
        "全表更新；确认非误写，必要时先在影子库验证影响面",
        lambda tree, th: [
            "UPDATE 语句无 WHERE 条件，将更新全表"
            for node in [tree]
            if isinstance(node, exp.Update) and node.args.get("where") is None
        ],
    ),
    Rule(
        "COL.001",
        LEVEL_WARNING,
        "SELECT *",
        "表结构变更时行为漂移；显式列出所需列",
        lambda tree, th: [
            "SELECT * 随表结构变更漂移，且无法利用覆盖索引"
            for select in [tree]
            if isinstance(select, exp.Select) and select.find(exp.Star) is not None
        ],
    ),
    Rule(
        "COL.002",
        LEVEL_WARNING,
        "INSERT 未指定列名",
        "表结构变更（加列/调序）时语义漂移；显式列名",
        lambda tree, th: [
            "INSERT 未显式指定列名"
            for node in [tree]
            if isinstance(node, exp.Insert) and isinstance(node.this, exp.Table)
        ],
    ),
    Rule(
        "COL.005",
        LEVEL_INFO,
        "列缺注释",
        "列应带 COMMENT 说明业务含义",
        lambda tree, th: _missing_comment_message(tree),
    ),
    Rule(
        "COL.013",
        LEVEL_WARNING,
        "TIMESTAMP 列无默认值",
        "无默认值的 TIMESTAMP 列在严格模式下插入报错，影响在线变更",
        lambda tree, th: [
            f"TIMESTAMP 列 {coldef.name} 未设默认值"
            for coldef in _column_defs(tree)
            if _dtype_name(coldef) in _TIMESTAMP_DTYPE_NAMES
            and not _has_constraint_of(coldef, exp.DefaultColumnConstraint)
        ],
    ),
    Rule(
        "DIS.001",
        LEVEL_INFO,
        "疑似多余 DISTINCT",
        "若选择列含主键/唯一键，DISTINCT 无效果，徒增去重开销",
        lambda tree, th: [
            "DISTINCT 与主键形态列并存或作用于 *，疑似多余"
            for select in [tree]
            if isinstance(select, exp.Select)
            and select.args.get("distinct")
            and (
                select.find(exp.Star) is not None
                or any(isinstance(e, exp.Column) and e.name.lower() == "id" for e in select.expressions)
            )
        ],
    ),
    Rule(
        "FUN.001",
        LEVEL_WARNING,
        "WHERE 中对列施加函数/运算",
        "索引失效；改写为对常量侧运算或使用函数索引（8.0+）",
        lambda tree, th: [
            f"谓词中列 {col.name} 被函数或运算包裹，索引失效"
            for node in tree.find_all(*_COMPARISON_NODES)
            for col in _wrapped_predicate_columns(node)
        ],
    ),
    Rule(
        "FUN.005",
        LEVEL_INFO,
        "COUNT(col) 应为 COUNT(*)",
        "COUNT(col) 语义为非空计数且难走最优计划；统计行数用 COUNT(*)",
        lambda tree, th: [
            f"COUNT({count.this.name}) 建议改为 COUNT(*)"
            for count in tree.find_all(exp.Count)
            if isinstance(count.this, exp.Column)
        ],
    ),
    Rule(
        "JOI.001",
        LEVEL_WARNING,
        "逗号 JOIN 与 ANSI JOIN 混用",
        "易引入笛卡尔积；统一 ANSI JOIN 写法",
        lambda tree, th: [
            "逗号 JOIN 与 ANSI JOIN 混用"
            for select in [tree]
            if isinstance(select, exp.Select)
            and sum(1 for j in select.args.get("joins", []) or [] if j.args.get("on") is None) > 0
            and sum(1 for j in select.args.get("joins", []) or [] if j.args.get("on") is not None) > 0
        ],
    ),
    Rule(
        "KEY.002",
        LEVEL_ERROR,
        "表无主键/唯一键",
        "无主键表阻塞 gh-ost/pt-osc 在线变更，副本回放也慢",
        lambda tree, th: [
            "表没有主键也没有唯一键，无法安全在线变更"
            for tree_create in [tree]
            if isinstance(tree_create, exp.Create)
            and tree_create.kind == "TABLE"
            and not _has_pk_or_unique(tree_create)
        ],
    ),
    Rule(
        "KEY.005",
        LEVEL_WARNING,
        "单表索引数过多",
        "每加一个索引都放大写开销；合并或删除低价值索引",
        lambda tree, th: [
            f"二级索引 {count} 个，超过阈值 {th.index_count}"
            for create in [tree]
            if isinstance(create, exp.Create) and create.kind == "TABLE"
            for count in [_secondary_index_count(create)]
            if count > th.index_count
        ],
    ),
    Rule(
        "KEY.007",
        LEVEL_WARNING,
        "主键应为整型",
        "非整型主键（如 VARCHAR）聚簇存储代价高、二级索引膨胀",
        lambda tree, th: [
            f"主键列 {coldef.name} 类型 {dtype} 非整型"
            for create in [tree]
            if isinstance(create, exp.Create) and create.kind == "TABLE"
            for coldef in _pk_column_defs(create)
            for dtype in [_dtype_name(coldef)]
            if dtype and dtype not in _INT_DTYPE_NAMES
        ],
    ),
    Rule(
        "LCK.002",
        LEVEL_WARNING,
        "INSERT ON DUPLICATE KEY UPDATE",
        "自增暴涨、主从不一致风险；评估改用 INSERT IGNORE 或先查后写",
        lambda tree, th: [
            "INSERT ON DUPLICATE KEY UPDATE：自增消耗与主从一致性风险"
            for node in [tree]
            if isinstance(node, exp.Insert) and node.args.get("conflict") is not None
        ],
    ),
    Rule(
        "RES.002",
        LEVEL_WARNING,
        "LIMIT 无 ORDER BY",
        "结果集不确定，分页可能重复/丢行；补确定性排序",
        lambda tree, th: [
            "LIMIT 未配合 ORDER BY，结果集不确定"
            for select in [tree]
            if isinstance(select, exp.Select)
            and select.args.get("limit") is not None
            and select.args.get("order") is None
        ],
    ),
    Rule(
        "RES.003",
        LEVEL_ERROR,
        "UPDATE/DELETE 带 LIMIT",
        "主从执行序不一致风险；用确定范围（主键列表）替代",
        lambda tree, th: [
            f"{type(tree).__name__} 带 LIMIT 子句，主从可能不一致"
            for node in [tree]
            if isinstance(node, (exp.Update, exp.Delete)) and node.args.get("limit") is not None
        ],
    ),
    Rule(
        "SEC.002",
        LEVEL_ERROR,
        "疑似明文密码列",
        "密码列应存哈希（bcrypt/argon2 等），禁止明文",
        lambda tree, th: [
            f"列 {coldef.name} 疑似明文密码存储（类型 {_dtype_name(coldef)}）"
            for coldef in _column_defs(tree)
            if _looks_like_password_column(coldef)
        ],
    ),
    Rule(
        "STA.003",
        LEVEL_INFO,
        "索引命名前缀",
        "二级索引用 idx_、唯一索引用 uk_（SOAR 口径）",
        lambda tree, th: [
            f"索引 {name} 命名不符合{prefix}前缀规范"
            for name, prefix in _naming_pairs(tree)
            if name and not name.startswith(prefix)
        ],
    ),
    Rule(
        "SUB.002",
        LEVEL_INFO,
        "UNION 应为 UNION ALL",
        "无需去重时 UNION 的隐式去重开销大；确认后改 UNION ALL",
        lambda tree, th: [
            "UNION 触发去重排序；无重复可能时改 UNION ALL"
            for node in [tree]
            if isinstance(node, exp.Union) and node.args.get("distinct")
        ],
    ),
]


def _iter_in(tree: exp.Expression) -> Iterator[exp.In]:
    return tree.find_all(exp.In)


def _offset_value(tree: exp.Expression) -> int | None:
    if not isinstance(tree, exp.Select):
        return None
    offset = tree.args.get("offset")
    if offset is None:
        return None
    literal = offset.args.get("expression") or offset.args.get("this")
    value = getattr(literal, "this", literal)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _offset_message(tree: exp.Expression, th: Thresholds) -> str:
    return f"OFFSET {_offset_value(tree)} 超过阈值 {th.offset}，深翻页将扫描并丢弃大量行"


def _missing_comment_message(tree: exp.Expression) -> list[str]:
    missing = [
        coldef.name for coldef in _column_defs(tree) if not _has_constraint_of(coldef, exp.CommentColumnConstraint)
    ]
    if not missing:
        return []
    preview = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
    return [f"{len(missing)} 个列缺少 COMMENT：{preview}"]


def _looks_like_password_column(coldef: exp.ColumnDef) -> bool:
    name = coldef.name.lower()
    if any(marker in name for marker in _HASH_MARKERS):
        return False
    if name not in _PASSWORD_NAMES and not name.endswith(("_password", "_passwd", "_pwd")):
        return False
    return _dtype_name(coldef) in _CHAR_DTYPE_NAMES


def get_rule(rule_id: str) -> Rule:
    for rule in RULES:
        if rule.rule_id == rule_id:
            return rule
    raise KeyError(rule_id)
