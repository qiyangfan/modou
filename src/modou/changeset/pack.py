"""按序合并变更集，并附带破坏性预警与大表锁风险标注。

预警不构成验收结论；解析失败只产生 unparseable 提示，不阻塞打包。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import sqlglot
from sqlglot import exp

from modou import __version__
from modou.changeset.discovery import ChangeFile, DiscoveryResult, discover_changeset
from modou.replay.splitter import final_delimiter, split_statements

SUPPORTED_TARGET_MAJORS = ("5.7", "8.0")


class ChangesetValidationError(Exception):
    """变更集校验失败：errors 非空，拒绝打包（CLI 映射退出码 1）。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("changeset validation failed")
        self.errors = errors


@dataclass
class StatementWarning:
    source_file: str
    statement_index: int  # 打包产物内全局序号（1 起，与回放序号一致）
    kind: str  # destructive / lock_risk / unparseable
    level: str  # high / medium / info
    message: str  # 人读文本（中文）


@dataclass
class PackResult:
    packed_sql: str
    warnings: list[StatementWarning] = field(default_factory=list)
    discovery: DiscoveryResult | None = None


def pack_changeset(
    directory: Path,
    *,
    allow_legacy_names: bool = False,
    target_major: str = "8.0",
) -> PackResult:
    """发现、校验并按序合并变更集，逐语句产出预警；校验失败抛 ChangesetValidationError。"""
    if target_major not in SUPPORTED_TARGET_MAJORS:
        raise ValueError(f"unsupported target major: {target_major} (supported: {SUPPORTED_TARGET_MAJORS})")
    discovery = discover_changeset(directory, allow_legacy_names=allow_legacy_names)
    if discovery.errors:
        raise ChangesetValidationError(discovery.errors)

    chunks: list[str] = []
    warnings: list[StatementWarning] = []
    global_index = 0
    merged = ""  # 逐文件累加产物，用于校验合并后语句边界不漂移
    expected_total = 0
    # 粘连归因到最近一个有语句的文件，空文件不是根因。
    last_nonempty_item: ChangeFile | None = None
    for item in discovery.items:
        try:
            content = item.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # 文件不可读或非 UTF-8 时按校验错误报告。
            raise ChangesetValidationError([f"cannot read {item.filename}: {exc}"]) from exc
        chunks.append(f"-- ===== {item.filename} =====\n{content.rstrip()}\n")
        warnings.extend(_analyze_file(item, content, start_index=global_index + 1, target_major=target_major))
        file_count = len(split_statements(content))
        global_index += file_count
        expected_total += file_count
        merged = "".join(chunks)
        # 语句数变化说明文件边界粘连，预警序号会与回放序号错位；
        # 通常因前一文件缺分隔符或 DELIMITER 未复位。
        if len(split_statements(merged)) != expected_total:
            culprit = last_nonempty_item.filename if last_nonempty_item is not None else item.filename
            raise ChangesetValidationError(
                [
                    f"merged statement boundaries would shift when appending {item.filename}; file {culprit} "
                    "likely does not end with a statement delimiter (or leaves a DELIMITER block unbalanced) - "
                    "append ';' / 'DELIMITER ;' to its last statement"
                ]
            )
        # 后续文件可能抵消总数变化，因此仍逐文件检查 DELIMITER 是否复位。
        if final_delimiter(content) != ";":
            raise ChangesetValidationError(
                [
                    f"file {item.filename} leaves a non-default DELIMITER in effect at EOF "
                    "(DELIMITER block left unbalanced) - append 'DELIMITER ;' after its last statement"
                ]
            )
        if file_count > 0:
            last_nonempty_item = item

    # 跳号/legacy 等非阻塞提示并入预警输出
    warnings.extend(_discovery_warnings(discovery))
    packed_sql = _provenance_header(directory, discovery, warnings, global_index) + "".join(chunks)
    return PackResult(packed_sql=packed_sql, warnings=warnings, discovery=discovery)


def _provenance_header(
    directory: Path,
    discovery: DiscoveryResult,
    warnings: list[StatementWarning],
    statement_count: int,
) -> str:
    """生成产物出处头；变更集目录是事实源，合并文件只是派生物。"""
    destructive = sum(1 for w in warnings if w.kind == "destructive")
    lock_risk = sum(1 for w in warnings if w.kind == "lock_risk")
    unparseable = sum(1 for w in warnings if w.kind == "unparseable")
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "-- " + "=" * 77,
        "-- 墨斗（modou）合并变更脚本：机械生成，请勿手改；变更集目录是唯一事实源，本文件是派生物。",
        "--",
        f"-- 来源变更集：{directory.name}（{len(discovery.items)} 个文件，{statement_count} 条语句）",
        f"-- 摘要：破坏性语句 {destructive} 条；锁风险标注 {lock_risk} 条；待人工复核 {unparseable} 条",
        f"-- 生成：modou {__version__}，{generated_at}",
        "-- 口径：按序号顺序合并，语句边界已在打包时校验；预警不阻塞执行，明细见打包输出或 --report-json。",
        "-- " + "=" * 77,
        "",
    ]
    return "\n".join(lines) + "\n"


def split_packed(packed_sql: str) -> list[str]:
    """对打包产物做语句切分（回放与序号对齐的单一实现）。"""
    return split_statements(packed_sql)


def _analyze_file(item: ChangeFile, content: str, *, start_index: int, target_major: str) -> list[StatementWarning]:
    warnings: list[StatementWarning] = []
    for offset, statement in enumerate(split_statements(content)):
        index = start_index + offset
        warnings.extend(_analyze_statement(item.filename, index, statement, target_major))
    return warnings


def _analyze_statement(source_file: str, index: int, statement: str, target_major: str) -> list[StatementWarning]:
    try:
        node = sqlglot.parse_one(statement, dialect="mysql")
    except (sqlglot.errors.ParseError, ValueError):
        return [
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="unparseable",
                level="info",
                message="语句无法解析，请人工复核其影响（预警不因解析失败阻塞打包）。",
            )
        ]
    if node is None:
        return []

    if isinstance(node, exp.Drop):
        kind = (node.args.get("kind") or "OBJECT").upper()
        return [
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="destructive",
                level="high",
                message=f"破坏性语句：DROP {kind}，删除后不可恢复，请确认备份与回滚预案。",
            )
        ]
    if isinstance(node, exp.TruncateTable):
        return [
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="destructive",
                level="high",
                message="破坏性语句：TRUNCATE 清空全表数据且不可回滚，请确认备份与回滚预案。",
            )
        ]
    if isinstance(node, (exp.Update, exp.Delete)) and node.args.get("where") is None:
        verb = "UPDATE" if isinstance(node, exp.Update) else "DELETE"
        return [
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="destructive",
                level="high",
                message=f"破坏性语句：{verb} 未带 WHERE 条件，将作用于全表，请确认是否为有意全表操作。",
            )
        ]
    if isinstance(node, exp.Alter):
        return _analyze_alter(source_file, index, node, target_major)
    if isinstance(node, exp.Command) and statement.upper().lstrip().startswith("ALTER"):
        return [
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="lock_risk",
                level="medium",
                message="ALTER 无法解析出执行算法，按 MySQL 默认行为可能为 COPY 全表重建，请人工确认。",
            )
        ]
    return []


def _analyze_alter(source_file: str, index: int, node: exp.Alter, target_major: str) -> list[StatementWarning]:
    """按操作类型标注锁风险；算法随目标大版本变化，5.7 无 INSTANT。"""
    warnings: list[StatementWarning] = []
    actions = node.args.get("actions") or []
    table_name = node.this.sql(dialect="mysql") if node.this is not None else "?"
    for action in actions:
        note = _alter_note(action, target_major)
        if note is None:
            continue
        warnings.append(
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="lock_risk",
                level="medium",
                message=f"ALTER {table_name}：{note}",
            )
        )
    # 引擎/字符集整体转换在 options 中，不在 actions
    if node.args.get("options"):
        warnings.append(
            StatementWarning(
                source_file=source_file,
                statement_index=index,
                kind="lock_risk",
                level="high",
                message=(
                    f"ALTER {table_name}：表级选项变更（ENGINE/字符集等）触发 COPY 全表重建并阻塞写入，"
                    "大表务必用 pt-osc/gh-ost 或低峰窗口执行。"
                ),
            )
        )
    return warnings


def _alter_note(action: exp.Expression, target_major: str) -> str | None:
    if isinstance(action, exp.ColumnDef):
        if target_major == "5.7":
            return "ADD COLUMN 走 INPLACE（5.7 无 INSTANT），不阻塞写但需评估表规模。"
        return (
            "ADD COLUMN 可走 INSTANT（8.0.12+），通常秒级完成；"
            "若失败会以报错快速终止，可显式指定 ALGORITHM=INSTANT 验证。"
        )
    if isinstance(action, exp.Drop):
        if target_major == "5.7":
            return "DROP COLUMN 走 INPLACE 并重建表，大表耗时与磁盘占用翻倍，建议 pt-osc/gh-ost。"
        return (
            "DROP COLUMN 在 8.0.29+ 可 INSTANT，否则 INPLACE 重建；不确定小版本时按重建评估，大表建议 pt-osc/gh-ost。"
        )
    if isinstance(action, exp.AddConstraint):
        return "ADD INDEX/约束走 INPLACE：不阻塞写但需构建索引树，大表注意耗时与临时磁盘。"
    if isinstance(action, (exp.ModifyColumn, exp.AlterColumn, exp.RenameColumn)):
        return (
            "列定义变更多为 COPY/INPLACE 重建，写阻塞风险最高；仅加长 varchar 等元数据场景可在线，"
            "大表建议 pt-osc/gh-ost 或低峰窗口。"
        )
    return None


def _discovery_warnings(discovery: DiscoveryResult) -> list[StatementWarning]:
    warnings: list[StatementWarning] = []
    for message in discovery.warnings:
        # 按 sequence gap 前缀区分跳号与目录提示，避免归错类别
        text = f"变更集序号跳号：{message}" if message.startswith("sequence gap") else f"变更集目录提示：{message}"
        warnings.append(
            StatementWarning(
                source_file=discovery.items[0].filename if discovery.items else "-",
                statement_index=0,
                kind="notice",
                level="info",
                message=text,
            )
        )
    return warnings
