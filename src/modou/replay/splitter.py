"""按 MySQL 词法规则切分语句，供回放和预警分析共用。

识别 DELIMITER、引号和注释中的分隔符；保留可执行的 ``/*! ... */`` 注释，不解析 SQL 语法。
"""

from __future__ import annotations

_DELIMITER_KEYWORD = "delimiter"


def split_statements(sql_text: str) -> list[str]:
    """按当前分隔符切出语句序列（语句文本不含结尾分隔符）；纯空白/纯注释片段不计入。"""
    statements, _ = _scan(sql_text)
    return statements


def final_delimiter(sql_text: str) -> str:
    """返回扫描结束时生效的分隔符，供 pack 检查文件是否以默认分隔符收尾。"""
    _, delimiter = _scan(sql_text)
    return delimiter


def _scan(sql_text: str) -> tuple[list[str], str]:
    """单一词法实现：同时产出语句序列与结束时生效的分隔符。"""
    statements: list[str] = []
    delimiter = ";"
    buffer: list[str] = []
    buffer_has_code = False  # 缓冲区是否含非注释内容（纯注释尾巴不算语句）
    i = 0
    n = len(sql_text)

    def buffer_is_statement_start() -> bool:
        """缓冲区只含空白/注释时，才把行首词识别为 DELIMITER 指令。"""
        return not buffer_has_code

    while i < n:
        # DELIMITER 只在语句起点识别
        if (
            buffer_is_statement_start()
            and _at_line_start(buffer)
            and sql_text[i : i + len(_DELIMITER_KEYWORD)].lower() == _DELIMITER_KEYWORD
            and _is_word_boundary_before(sql_text, i)
        ):
            j = i + len(_DELIMITER_KEYWORD)
            while j < n and sql_text[j] in " \t":
                j += 1
            k = j
            while k < n and sql_text[k] not in "\r\n":
                k += 1
            token = sql_text[j:k].strip()
            if token:
                delimiter = token
            buffer = []
            buffer_has_code = False
            i = k
            continue

        ch = sql_text[i]

        # 字符串与反引号
        if ch == "'":
            j = _skip_single_quoted(sql_text, i)
            buffer.append(sql_text[i:j])
            buffer_has_code = True
            i = j
            continue
        if ch == '"':
            j = _skip_double_quoted(sql_text, i)
            buffer.append(sql_text[i:j])
            buffer_has_code = True
            i = j
            continue
        if ch == "`":
            j = _skip_backquoted(sql_text, i)
            buffer.append(sql_text[i:j])
            buffer_has_code = True
            i = j
            continue

        # 注释
        if ch == "#":
            j = _skip_line(sql_text, i)
            buffer.append(sql_text[i:j])
            i = j
            continue
        if ch == "-" and sql_text[i : i + 2] == "--" and (i + 2 >= n or sql_text[i + 2] in " \t\r\n"):
            j = _skip_line(sql_text, i)
            buffer.append(sql_text[i:j])
            i = j
            continue
        if ch == "/" and sql_text[i : i + 2] == "/*":
            j = _skip_block_comment(sql_text, i)
            buffer.append(sql_text[i:j])
            # /*! ... */ 版本注释可执行，算语句内容
            if sql_text[i : i + 3] == "/*!":
                buffer_has_code = True
            i = j
            continue

        # 分隔符命中
        if delimiter and sql_text.startswith(delimiter, i):
            statement = "".join(buffer).strip()
            if buffer_has_code:
                statements.append(statement)
            buffer = []
            buffer_has_code = False
            i += len(delimiter)
            continue

        if not ch.isspace():
            buffer_has_code = True
        buffer.append(ch)
        i += 1

    if buffer_has_code:
        tail = "".join(buffer).strip()
        if tail:
            statements.append(tail)
    return statements, delimiter


def _at_line_start(buffer: list[str]) -> bool:
    """缓冲区最后一个非空字符是换行，或缓冲区为空 → 位于行首。"""
    for ch in reversed("".join(buffer)):
        if ch in " \t":
            continue
        return ch == "\n"
    return True


def _is_word_boundary_before(sql_text: str, i: int) -> bool:
    """DELIMITER 关键词前必须是行首或空白（避免匹配 my_delimiter 之类标识符）。"""
    if i == 0:
        return True
    return sql_text[i - 1] in " \t\r\n;"


def _skip_single_quoted(sql_text: str, start: int) -> int:
    """跳过单引号串；支持反斜杠转义与 '' 双写转义。返回结束位置（引号之后）。"""
    i = start + 1
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "'":
            if i + 1 < n and sql_text[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _skip_double_quoted(sql_text: str, start: int) -> int:
    """跳过双引号串（MySQL 默认把双引号当字符串）；转义规则同单引号。"""
    i = start + 1
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == '"':
            if i + 1 < n and sql_text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _skip_backquoted(sql_text: str, start: int) -> int:
    """跳过反引号标识符（`` 双写转义）。"""
    i = start + 1
    n = len(sql_text)
    while i < n:
        if sql_text[i] == "`":
            if i + 1 < n and sql_text[i + 1] == "`":
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _skip_line(sql_text: str, start: int) -> int:
    n = len(sql_text)
    i = sql_text.find("\n", start)
    return n if i == -1 else i + 1


def _skip_block_comment(sql_text: str, start: int) -> int:
    end = sql_text.find("*/", start + 2)
    return len(sql_text) if end == -1 else end + 2
