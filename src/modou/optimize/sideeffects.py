"""索引副作用检查：冗余三情形、外键依赖、索引数上限与写放大（确定性，纯元数据）。

冗余判定对齐 sys.schema_redundant_indexes 源码语义（2026-10 调研核实）：
1. duplicate：列集合完全相同；
2. prefix_non_unique：非唯一索引的列序列是另一索引的列前缀 → 前缀者冗余
   （唯一性语义不可丢：冗余方必须非唯一）；
3. unique_prefix：唯一索引的列是另一索引的列前缀 → 更长的那条冗余。

函数/表达式索引没有可比的普通列序：跳过比较（宁可漏报不误判）。
"""

from __future__ import annotations

from dataclasses import dataclass

from modou.snapshot.model import TableDef

# 单表二级索引数上限默认值（宪法口径：阈值可配置）
DEFAULT_INDEX_COUNT_LIMIT = 10


@dataclass
class IndexView:
    """可比索引视图：仅保留非表达式部分的列序。

    columns 供展示；keys 供比较——带 (列, 前缀长度) 整体比较，前缀索引
    （如 a(64)）与完整列索引不等价，不得互判冗余。keys 缺省时从 columns
    派生为完整列（sub_part=None），手工构造视图语义不变。
    """

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
        # 含任一表达式部分（如 (LOWER(name), age)）即整条不可比：最左前缀是表达式，
        # 普通列序比较会误判冗余（宁可漏报不误判，见模块 docstring）
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
    """被外键依赖的索引名：外键列序列是索引列前缀的索引即被依赖。"""
    required: set[str] = set()
    for fk in table.foreign_keys:
        for index in table.indexes:
            columns = [part.column for part in index.parts if part.column]
            if columns[: len(fk.columns)] == fk.columns:
                required.add(index.name)
    return required


def find_redundant_pairs(pool: list[IndexView]) -> list[tuple[IndexView, IndexView, str]]:
    """对索引池做两两冗余判定，返回（冗余方, 主导方, 情形）清单。

    池序决定 duplicate 情形下谁被判冗余：调用方把「建议新增的候选」放最前，
    既有索引按名排序在后——重复时候选方被判冗余（不动既有结构）。
    """
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
    """对一条索引候选做确定性副作用检查，返回附注清单（建议随附）。"""
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
