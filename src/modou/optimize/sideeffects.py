"""检查索引候选的冗余、外键依赖、数量上限和写放大。

按列与前缀长度识别重复或冗余索引；表达式索引不参与比较；唯一索引和外键依赖影响冗余方向。
"""

from __future__ import annotations

from dataclasses import dataclass

from modou.snapshot.model import TableDef

# 单表二级索引数上限，可由 CLI 覆盖
DEFAULT_INDEX_COUNT_LIMIT = 10


@dataclass
class IndexView:
    """用于比较的索引视图；键包含列与前缀长度，前缀索引不等同于整列索引。"""

    name: str
    columns: list[str]
    unique: bool
    expression_only: bool
    keys: list[tuple[str, int | None]] | None = None

    def __post_init__(self) -> None:
        if self.keys is None:
            self.keys = [(column, None) for column in self.columns]


@dataclass
class SideEffectNote:
    # kind: CANDIDATE_REDUNDANT / EXISTING_BECOMES_REDUNDANT / FK_DEPENDENCY /
    #       INDEX_COUNT / WRITE_AMPLIFICATION / INDEX_DROP_FAILED
    kind: str
    message: str


def index_views_from_table(table: TableDef) -> list[IndexView]:
    views: list[IndexView] = []
    for index in table.indexes:
        keys = [(part.column, part.sub_part) for part in index.parts if part.column]
        # 含表达式部分（如 (LOWER(name), age)）即整条不可比；宁可漏报，避免误判冗余
        expression_only = any(part.column is None or part.expression for part in index.parts)
        views.append(
            IndexView(
                name=index.name,
                columns=[column for column, _ in keys],
                unique=index.unique,
                expression_only=expression_only,
                keys=keys,
            )
        )
    return views


def fk_required_index_names(table: TableDef) -> set[str]:
    """返回外键依赖的索引名：外键列是索引前缀即视为依赖。"""
    required: set[str] = set()
    for fk in table.foreign_keys:
        for index in table.indexes:
            columns = [part.column for part in index.parts if part.column]
            if columns[: len(fk.columns)] == fk.columns:
                required.add(index.name)
    return required


def find_redundant_pairs(pool: list[IndexView]) -> list[tuple[IndexView, IndexView, str]]:
    """两两比较索引，返回冗余方、主导方和情形；重复索引按输入顺序判定。"""
    redundant: list[tuple[IndexView, IndexView, str]] = []
    comparable = [view for view in pool if not view.expression_only and view.keys]
    for i in range(len(comparable)):
        for j in range(i + 1, len(comparable)):
            first, second = comparable[i], comparable[j]
            if first.keys == second.keys:
                redundant.append((first, second, "duplicate"))
                continue
            if _is_prefix(first.keys, second.keys):
                if first.unique:
                    redundant.append((second, first, "unique_prefix"))
                else:
                    redundant.append((first, second, "prefix_non_unique"))
            elif _is_prefix(second.keys, first.keys):
                if second.unique:
                    redundant.append((first, second, "unique_prefix"))
                else:
                    redundant.append((second, first, "prefix_non_unique"))
    return redundant


def check_candidate_side_effects(
    candidate_columns: list[str],
    table: TableDef,
    *,
    index_count_limit: int = DEFAULT_INDEX_COUNT_LIMIT,
) -> list[SideEffectNote]:
    """检查一条索引候选的副作用，返回随建议展示的附注。"""
    notes: list[SideEffectNote] = []
    candidate = IndexView(
        name="(候选)",
        columns=list(candidate_columns),
        unique=False,
        expression_only=False,
        keys=[(column, None) for column in candidate_columns],
    )
    existing = sorted(index_views_from_table(table), key=lambda v: v.name)
    fk_protected = fk_required_index_names(table)

    for redundant_view, dominant_view, case in find_redundant_pairs([candidate, *existing]):
        if redundant_view is candidate:
            case_label = {
                "duplicate": "列集合与现有索引完全相同",
                "prefix_non_unique": "列序列被现有索引前缀覆盖",
                "unique_prefix": "现有唯一索引前缀已提供等效访问路径",
            }[case]
            notes.append(
                SideEffectNote(
                    "CANDIDATE_REDUNDANT",
                    f"候选索引 {candidate_columns} 冗余：{case_label}（现有索引 {dominant_view.name}），建议放弃",
                )
            )
        elif redundant_view.name in fk_protected:
            notes.append(
                SideEffectNote(
                    "FK_DEPENDENCY",
                    f"现有索引 {redundant_view.name} 被外键依赖，不可删除；候选落地前应先评估直接依赖现有索引",
                )
            )
        else:
            notes.append(
                SideEffectNote(
                    "EXISTING_BECOMES_REDUNDANT",
                    f"候选落地后现有索引 {redundant_view.name} 变冗余（前缀被候选覆盖），建议评估替换",
                )
            )

    secondary_count = sum(1 for view in existing if view.name != "PRIMARY")
    if secondary_count + 1 > index_count_limit:
        notes.append(
            SideEffectNote(
                "INDEX_COUNT",
                f"候选落地后该表二级索引数达 {secondary_count + 1}，超过上限 {index_count_limit}，写放大风险高",
            )
        )
    notes.append(
        SideEffectNote(
            "WRITE_AMPLIFICATION",
            "新增二级索引会增加写入开销（每次 INSERT/UPDATE 维护一份索引），请结合写负载评估",
        )
    )
    return notes


def _is_prefix(prefix: list[tuple[str, int | None]], whole: list[tuple[str, int | None]]) -> bool:
    return len(prefix) < len(whole) and whole[: len(prefix)] == prefix
