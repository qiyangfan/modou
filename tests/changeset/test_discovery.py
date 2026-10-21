"""变更集发现器测试：manifest 校验与 V 文件命名。"""

from pathlib import Path

from modou.changeset.discovery import discover_changeset


def make_changeset(tmp_path: Path, files: dict[str, str], manifest: str | None) -> Path:
    """构造变更集目录；manifest 为 None 时不写 manifest.txt。"""
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    if manifest is not None:
        (tmp_path / "manifest.txt").write_text(manifest, encoding="utf-8")
    return tmp_path


def test_discover_happy_path_sorted_by_seq(tmp_path: Path) -> None:
    make_changeset(
        tmp_path,
        {"V02__add_index.sql": "ALTER TABLE t ADD INDEX i1(c);", "V01__create_t.sql": "CREATE TABLE t(id INT);"},
        "V01__create_t.sql\nV02__add_index.sql\n",
    )
    result = discover_changeset(tmp_path)
    assert result.errors == []
    assert [item.seq for item in result.items] == [1, 2]
    assert result.items[0].filename == "V01__create_t.sql"
    assert result.items[1].description == "add_index"


def test_manifest_declares_missing_file(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;"}, "V01__a.sql\nV02__missing.sql\n")
    result = discover_changeset(tmp_path)
    assert any("V02__missing.sql" in err for err in result.errors)


def test_dir_has_undeclared_file(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;", "V02__extra.sql": "SELECT 2;"}, "V01__a.sql\n")
    result = discover_changeset(tmp_path)
    assert any("V02__extra.sql" in err for err in result.errors)


def test_duplicate_seq_rejected(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;", "V001__b.sql": "SELECT 2;"}, "V01__a.sql\nV001__b.sql\n")
    result = discover_changeset(tmp_path)
    assert any("1" in err and ("V01__a.sql" in err or "V001__b.sql" in err) for err in result.errors)


def test_single_underscore_name_rejected_strict(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01_bad_name.sql": "SELECT 1;"}, "V01_bad_name.sql\n")
    result = discover_changeset(tmp_path)
    assert any("V01_bad_name.sql" in err for err in result.errors)


def test_legacy_name_admitted_with_flag_and_warning(tmp_path: Path) -> None:
    make_changeset(
        tmp_path, {"V01__a.sql": "SELECT 1;", "legacy_patch.sql": "SELECT 2;"}, "V01__a.sql\nlegacy_patch.sql\n"
    )
    result = discover_changeset(tmp_path, allow_legacy_names=True)
    assert result.errors == []
    assert [item.filename for item in result.items] == ["V01__a.sql", "legacy_patch.sql"]
    assert any("legacy_patch.sql" in warn for warn in result.warnings)


def test_missing_manifest_rejected(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;"}, None)
    result = discover_changeset(tmp_path)
    assert any("manifest" in err.lower() for err in result.errors)


def test_seq_gap_warns_but_not_blocks(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;", "V03__c.sql": "SELECT 3;"}, "V01__a.sql\nV03__c.sql\n")
    result = discover_changeset(tmp_path)
    assert result.errors == []
    assert any("2" in warn for warn in result.warnings)


def test_manifest_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;"}, "# 示例说明\n\nV01__a.sql\n")
    result = discover_changeset(tmp_path)
    assert result.errors == []
    assert len(result.items) == 1


def test_manifest_entry_with_path_separator_rejected(tmp_path: Path) -> None:
    make_changeset(tmp_path, {"V01__a.sql": "SELECT 1;"}, "../V01__a.sql\n")
    result = discover_changeset(tmp_path)
    assert result.errors != []
