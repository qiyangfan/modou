"""pack 打包：合并顺序、DELIMITER 边界保持、破坏性预警与大表锁风险标注。"""

from pathlib import Path

import pytest

from modou.changeset.pack import ChangesetValidationError, pack_changeset, split_packed


def write_changeset(tmp_path: Path, files: dict[str, str], manifest_entries: list[str]) -> Path:
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("\n".join(manifest_entries) + "\n", encoding="utf-8")
    return tmp_path


def test_pack_merges_in_seq_order(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {
            "V01__create.sql": "CREATE TABLE a(id INT);",
            "V02__alter.sql": "ALTER TABLE a ADD COLUMN c INT;",
        },
        ["V01__create.sql", "V02__alter.sql"],
    )
    result = pack_changeset(tmp_path)
    assert result.packed_sql.index("V01__create.sql") < result.packed_sql.index("CREATE TABLE a")
    assert result.packed_sql.index("CREATE TABLE a") < result.packed_sql.index("ALTER TABLE a")
    # 合并没有破坏性预警；ADD COLUMN 只标锁风险
    assert all(w.kind != "destructive" for w in result.warnings)


def test_pack_preserves_delimiter_block(tmp_path: Path) -> None:
    proc = "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END$$\nDELIMITER ;\n"
    write_changeset(tmp_path, {"V01__proc.sql": proc}, ["V01__proc.sql"])
    result = pack_changeset(tmp_path)
    # 产物原文保留 DELIMITER 指令（mysql 客户端执行依赖）
    assert "DELIMITER $$" in result.packed_sql
    # 切分后存储过程体仍是一条语句，不被内部的分号拆散
    statements = split_packed(result.packed_sql)
    assert len(statements) == 1
    assert statements[0].startswith("CREATE PROCEDURE")


def test_pack_flags_drop_and_truncate(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {"V01__drop.sql": "DROP TABLE old_t;\nTRUNCATE TABLE log_t;"},
        ["V01__drop.sql"],
    )
    result = pack_changeset(tmp_path)
    kinds = {w.kind for w in result.warnings}
    assert kinds == {"destructive"}
    assert all(w.level == "high" for w in result.warnings)


def test_pack_flags_dml_without_where(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {"V01__dml.sql": "UPDATE t SET a = 1;\nDELETE FROM t;"},
        ["V01__dml.sql"],
    )
    result = pack_changeset(tmp_path)
    assert {w.kind for w in result.warnings} == {"destructive"}
    assert len(result.warnings) == 2


def test_pack_dml_with_where_not_flagged(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {"V01__dml.sql": "UPDATE t SET a = 1 WHERE id = 2;\nDELETE FROM t WHERE id = 3;"},
        ["V01__dml.sql"],
    )
    result = pack_changeset(tmp_path)
    assert result.warnings == []


def test_pack_alter_annotations_by_version(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {
            "V01__alter.sql": (
                "ALTER TABLE t ADD COLUMN c1 INT;\n"
                "ALTER TABLE t MODIFY COLUMN c1 VARCHAR(20);\n"
                "ALTER TABLE t ENGINE = InnoDB;\n"
            )
        },
        ["V01__alter.sql"],
    )
    result_80 = pack_changeset(tmp_path)
    msgs_80 = [w.message for w in result_80.warnings]
    # 8.0：ADD COLUMN 走 INSTANT；MODIFY/ENGINE 标注重风险
    assert any("INSTANT" in m for m in msgs_80)
    assert any("pt-osc/gh-ost" in m for m in msgs_80)

    result_57 = pack_changeset(tmp_path, target_major="5.7")
    msgs_57 = [w.message for w in result_57.warnings]
    assert any("INPLACE" in m for m in msgs_57)


def test_pack_unparseable_statement_warns_but_succeeds(tmp_path: Path) -> None:
    write_changeset(tmp_path, {"V01__weird.sql": "CREATE TABLE ("}, ["V01__weird.sql"])
    result = pack_changeset(tmp_path)
    assert any(w.kind == "unparseable" for w in result.warnings)


def test_pack_embeds_provenance_header(tmp_path: Path) -> None:
    """产物头部记录来源、文件/语句计数与预警摘要，并提示勿手改。"""
    write_changeset(
        tmp_path,
        {
            "V01__drop.sql": "DROP TABLE old_t;",
            "V02__alter.sql": "ALTER TABLE t ADD COLUMN c1 INT;",
        },
        ["V01__drop.sql", "V02__alter.sql"],
    )
    result = pack_changeset(tmp_path)
    assert "请勿手改" in result.packed_sql
    assert "2 个文件，2 条语句" in result.packed_sql
    assert "破坏性语句 1 条" in result.packed_sql
    assert "锁风险标注 1 条" in result.packed_sql
    # 纯注释头不改变切分：首语句仍是 V01 的 DROP，尾部携带原文
    statements = split_packed(result.packed_sql)
    assert len(statements) == 2
    assert statements[0].endswith("DROP TABLE old_t;"[:-1])  # 切分语义：不含结尾分隔符
    assert statements[0].startswith("-- =")


def test_pack_warning_carries_source_and_index(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {
            "V01__ok.sql": "CREATE TABLE a(id INT);\nCREATE TABLE b(id INT);",
            "V02__bad.sql": "DROP TABLE a;",
        },
        ["V01__ok.sql", "V02__bad.sql"],
    )
    result = pack_changeset(tmp_path)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.source_file == "V02__bad.sql"
    assert warning.statement_index == 3  # 跨文件连续计数


def test_pack_rejects_on_discovery_errors(tmp_path: Path) -> None:
    write_changeset(tmp_path, {"V01__a.sql": "SELECT 1;"}, [])
    with pytest.raises(ChangesetValidationError):
        pack_changeset(tmp_path)


def test_discovery_skip_number_produces_warning_only(tmp_path: Path) -> None:
    write_changeset(tmp_path, {"V01__a.sql": "SELECT 1;", "V03__c.sql": "SELECT 3;"}, ["V01__a.sql", "V03__c.sql"])
    result = pack_changeset(tmp_path)
    assert any("gap" in w.message or "跳号" in w.message for w in result.warnings)


def test_split_packed_matches_discovery_order(tmp_path: Path) -> None:
    write_changeset(
        tmp_path,
        {"V01__a.sql": "CREATE TABLE a(id INT);", "V02__b.sql": "CREATE TABLE b(id INT);"},
        ["V01__a.sql", "V02__b.sql"],
    )
    result = pack_changeset(tmp_path)
    statements = split_packed(result.packed_sql)
    # 语句文本不含结尾分隔符（与 mysql 客户端语义一致）；首条语句含文件边界注释前缀
    assert len(statements) == 2
    assert statements[0].endswith("CREATE TABLE a(id INT)")
    assert statements[1].endswith("CREATE TABLE b(id INT)")


# ── 文件边界与目录警告 ──────────────────────────────────────────────────────


def test_pack_culprit_attribution_skips_empty_files(tmp_path: Path) -> None:
    (tmp_path / "V01__a.sql").write_text("CREATE TABLE a(id INT)", encoding="utf-8")  # 缺分隔符
    (tmp_path / "V02__empty.sql").write_text("", encoding="utf-8")
    (tmp_path / "V03__c.sql").write_text("CREATE TABLE c(id INT);", encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("V01__a.sql\nV02__empty.sql\nV03__c.sql\n", encoding="utf-8")
    with pytest.raises(ChangesetValidationError) as exc_info:
        pack_changeset(tmp_path)
    # 粘连在拼 V03 时暴露，根因是产出过语句的 V01，而非空文件 V02
    assert "V01__a.sql" in exc_info.value.errors[0]


def test_pack_notice_prefix_separates_gap_from_directory_hints(tmp_path: Path) -> None:
    write_changeset(tmp_path, {"V01__a.sql": "SELECT 1;", "V03__c.sql": "SELECT 3;"}, ["V01__a.sql", "V03__c.sql"])
    (tmp_path / "backup").mkdir()
    (tmp_path / "backup" / "old.sql").write_text("SELECT 2;", encoding="utf-8")
    result = pack_changeset(tmp_path)
    notices = [w.message for w in result.warnings if w.kind == "notice"]
    assert any(text.startswith("变更集序号跳号：") for text in notices)
    assert any(text.startswith("变更集目录提示：") and "backup/old.sql" in text for text in notices)


def test_pack_rejects_non_utf8_file_as_validation_error(tmp_path: Path) -> None:
    (tmp_path / "V01__a.sql").write_bytes("CREATE TABLE 中文 (id INT);".encode("gbk"))
    (tmp_path / "manifest.txt").write_text("V01__a.sql\n", encoding="utf-8")
    with pytest.raises(ChangesetValidationError) as exc_info:
        pack_changeset(tmp_path)
    assert "cannot read" in exc_info.value.errors[0]


def test_pack_rejects_unbalanced_delimiter_at_file_end(tmp_path: Path) -> None:
    """前文件未复位 DELIMITER 时，即使合并后语句数未变也必须拒绝。"""
    (tmp_path / "V01__proc.sql").write_text(
        "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END$$\n", encoding="utf-8"
    )
    (tmp_path / "V02__after.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("V01__proc.sql\nV02__after.sql\n", encoding="utf-8")
    with pytest.raises(ChangesetValidationError) as exc_info:
        pack_changeset(tmp_path)
    assert "V01__proc.sql" in exc_info.value.errors[0]
    assert "DELIMITER" in exc_info.value.errors[0]


def test_pack_accepts_delimiter_block_with_reset(tmp_path: Path) -> None:
    """正常 DELIMITER 块（结束时复位为 ;）不受守卫影响。"""
    write_changeset(
        tmp_path,
        {
            "V01__proc.sql": "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END$$\nDELIMITER ;\n",
            "V02__after.sql": "CREATE TABLE t (id INT);",
        },
        ["V01__proc.sql", "V02__after.sql"],
    )
    result = pack_changeset(tmp_path)
    assert len(split_packed(result.packed_sql)) == 2
