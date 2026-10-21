"""语句切分器测试：字符串、注释与 DELIMITER 边界。"""

from modou.replay.splitter import final_delimiter, split_statements


def test_simple_statements() -> None:
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_semicolon_inside_strings_not_split() -> None:
    sql = "INSERT INTO t VALUES ('a;b', \"c;d\", `e;f`); SELECT 2;"
    assert split_statements(sql) == ["INSERT INTO t VALUES ('a;b', \"c;d\", `e;f`)", "SELECT 2"]


def test_string_escapes() -> None:
    sql = r"SELECT 'it\'s; ok', 'it''s; ok'; SELECT 2;"
    assert len(split_statements(sql)) == 2


def test_comments_with_semicolons_not_split() -> None:
    sql = "SELECT 1 /* 内部;注释 */; # 尾注;释\nSELECT 2; -- 行注;释\nSELECT 3;"
    assert split_statements(sql) == ["SELECT 1 /* 内部;注释 */", "# 尾注;释\nSELECT 2", "-- 行注;释\nSELECT 3"]


def test_double_dash_without_space_is_not_comment() -> None:
    sql = "SELECT 1--2; SELECT 3;"
    assert split_statements(sql) == ["SELECT 1--2", "SELECT 3"]


def test_version_comment_with_semicolon_stays_one_statement() -> None:
    sql = "/*!40101 SET NAMES utf8mb4 */;\n/*!50003 CREATE PROCEDURE p() BEGIN SELECT 1; END */;"
    parts = split_statements(sql)
    assert len(parts) == 2


def test_delimiter_block_keeps_procedure_intact() -> None:
    sql = (
        "CREATE TABLE t(id INT);\n"
        "DELIMITER $$\n"
        "CREATE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END$$\n"
        "CREATE TRIGGER tr AFTER INSERT ON t FOR EACH ROW BEGIN SET @x=1; END$$\n"
        "DELIMITER ;\n"
        "SELECT 3;\n"
    )
    parts = split_statements(sql)
    assert len(parts) == 4
    assert parts[1].startswith("CREATE PROCEDURE p()")
    assert parts[1].endswith("END")
    assert parts[2].startswith("CREATE TRIGGER tr")
    assert parts[3] == "SELECT 3"


def test_delimiter_double_semicolon() -> None:
    sql = "DELIMITER ;;\nCREATE PROCEDURE p() BEGIN SELECT 1; END;;\nDELIMITER ;\nSELECT 2;"
    parts = split_statements(sql)
    assert len(parts) == 2
    assert parts[0] == "CREATE PROCEDURE p() BEGIN SELECT 1; END"


def test_empty_and_comment_only_input() -> None:
    assert split_statements("") == []
    assert split_statements("   \n-- only comment\n") == []


def test_statement_without_trailing_delimiter() -> None:
    assert split_statements("SELECT 1") == ["SELECT 1"]


def test_final_delimiter_tracks_delimiter_directives() -> None:
    assert final_delimiter("SELECT 1;") == ";"
    assert final_delimiter("DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END$$\nDELIMITER ;") == ";"
    assert final_delimiter("DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END$$") == "$$"
    assert final_delimiter("") == ";"
