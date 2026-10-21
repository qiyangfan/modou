"""CLI 和快照边界测试：序号对齐、多库计数、JSON 校验和子目录警告。"""

import json
from pathlib import Path

import pytest

from modou.changeset.discovery import discover_changeset
from modou.changeset.pack import ChangesetValidationError, pack_changeset, split_packed
from modou.diff.threeway import KIND_MISSING, ObjectConclusion
from modou.report.render import KIND_LABELS, VerifyReport, render_text
from modou.snapshot.model import snapshot_from_json

# ── 文件末条语句缺分隔符 → 拒绝打包（预警序号与回放序号不得错位） ────────────


def test_pack_rejects_file_missing_trailing_delimiter(tmp_path: Path) -> None:
    (tmp_path / "V01__a.sql").write_text("CREATE TABLE a(id INT)", encoding="utf-8")  # 无分号
    (tmp_path / "V02__b.sql").write_text("CREATE TABLE b(id INT);", encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("V01__a.sql\nV02__b.sql\n", encoding="utf-8")
    with pytest.raises(ChangesetValidationError) as exc_info:
        pack_changeset(tmp_path)
    # 根因归到前一个文件（V01 缺分隔符），而非粘连暴露时的 V02
    assert "V01__a.sql" in exc_info.value.errors[0]
    assert "delimiter" in exc_info.value.errors[0]


def test_pack_aligned_indices_when_files_end_with_delimiter(tmp_path: Path) -> None:
    files = {"V01__a.sql": "CREATE TABLE a(id INT);", "V02__b.sql": "DROP TABLE a;"}
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    result = pack_changeset(tmp_path)
    packed_statements = split_packed(result.packed_sql)
    assert len(packed_statements) == 2
    # 预警序号与合并产物切分序号同源：DROP 的预警必须落在 #2
    assert result.warnings[0].kind == "destructive"
    assert result.warnings[0].statement_index == 2


# ── 多库报告的尾部汇总计数 ─────────────────────────────────────────────────


def _conclusion(db: str, name: str, kind: str) -> ObjectConclusion:
    return ObjectConclusion(database=db, object_type="table", object_name=name, kind=kind, dimensions=["existence"])


def test_multi_database_report_defers_counts_to_summary() -> None:
    report = VerifyReport(
        generated_at="2026-10-14T00:00:00+00:00",
        exit_code=1,
        databases={
            "db0": [_conclusion("db0", "t_a", KIND_MISSING)],
            "db1": [_conclusion("db1", "t_b", KIND_MISSING), _conclusion("db1", "t_c", KIND_MISSING)],
        },
    )
    text = render_text(report)
    db0_line = next(line for line in text.splitlines() if line.startswith("── 库 db0"))
    assert "2" not in db0_line  # db0 只有 1 条结论，不得显示他库计数
    assert "汇总" in text


def test_single_database_report_keeps_inline_counts() -> None:
    report = VerifyReport(
        generated_at="2026-10-14T00:00:00+00:00",
        exit_code=1,
        databases={"db0": [_conclusion("db0", "t_a", KIND_MISSING)]},
    )
    text = render_text(report)
    assert KIND_LABELS[KIND_MISSING] in text and "1" in text


# ── 非对象 JSON 快照 → ValueError ──────────────────────────────────────────


def test_snapshot_from_json_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        snapshot_from_json(json.dumps([1, 2, 3]))


# ── 子目录中的 .sql 不属于变更集 → 警告提示 ──────────────────────────────


def test_discovery_warns_on_nested_sql_files(tmp_path: Path) -> None:
    (tmp_path / "V01__a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("V01__a.sql\n", encoding="utf-8")
    nested = tmp_path / "backup"
    nested.mkdir()
    (nested / "old.sql").write_text("SELECT 2;", encoding="utf-8")
    result = discover_changeset(tmp_path)
    assert result.errors == []
    assert any("backup/old.sql" in w for w in result.warnings)


# ── 容器型字段的 JSON 畸形 → ValueError ────────────────────────────────────


def _valid_meta_dict() -> dict:
    return {
        "server_version": "8.4.11",
        "version_comment": "test",
        "character_set_server": "utf8mb4",
        "collation_server": "utf8mb4_0900_ai_ci",
        "lower_case_table_names": 0,
        "sql_mode": "",
    }


def test_snapshot_from_json_rejects_non_object_meta() -> None:
    raw = {"format_version": 1, "meta": [], "databases": {}, "warnings": []}
    with pytest.raises(ValueError, match="meta"):
        snapshot_from_json(json.dumps(raw))


def test_snapshot_from_json_rejects_non_object_databases() -> None:
    raw = {"format_version": 1, "meta": _valid_meta_dict(), "databases": [], "warnings": []}
    with pytest.raises(ValueError, match="databases"):
        snapshot_from_json(json.dumps(raw))


def test_snapshot_from_json_rejects_non_object_tables() -> None:
    raw = {
        "format_version": 1,
        "meta": _valid_meta_dict(),
        "databases": {"db1": {"name": "db1", "tables": []}},
        "warnings": [],
    }
    with pytest.raises(ValueError, match="tables"):
        snapshot_from_json(json.dumps(raw))
