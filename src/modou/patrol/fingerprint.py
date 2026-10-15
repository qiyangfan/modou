"""查询指纹归一：对齐 pt-query-digest 的行业事实口径（2026-10 调研核实）。

规则：全小写、空白折叠、去注释、字面量（字符串/数字/十六进制/NULL）→ `?`、
标识符内嵌数字替换、IN()/VALUES() 列表无论基数折叠为单个占位符、多值 INSERT
折叠为单 VALUES。基于 sqlglot tokenizer（唯一解析器，ADR-0006），不引入第二套实现。

与服务器端 digest 表口径不互认（不折叠 IN、1024 字节截断、容量上限），设计已
声明本模块为唯一指纹源（change Non-goals）。
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot.tokens import TokenType

_EMBEDDED_DIGITS = re.compile(r"\d+")


def fingerprint(sql: str) -> str:
    """归一化语句文本（语句级，多语句请先切分）。解析失败按词法降级处理。"""
    try:
        tokens = sqlglot.tokenize(sql, read="mysql")
    except sqlglot.errors.TokenError:
        tokens = []
        # 词法都过不了：退化为纯文本归一（仍可聚合，但保真度低）
        return _fallback(sql)

    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if token.token_type in (TokenType.COMMENT,):
            i += 1
            continue
        # IN(...) / VALUES(...) 折叠：无论基数，整组换成一个占位符——仅值列表折叠，
        # IN (SELECT ...) 子查询不是列表，不同形态不得合并为同一指纹
        if token.token_type in (TokenType.IN, TokenType.VALUES):
            group_start = _next_significant(tokens, i + 1)
            if group_start is not None and tokens[group_start].token_type == TokenType.L_PAREN:
                head = _next_significant(tokens, group_start + 1)
                if head is not None and _is_value_list_head(tokens[head]):
                    out.append("?")
                    i = _skip_paren_group(tokens, group_start)
                    # 多值 INSERT：VALUES (...), (...), ... 的后续分组一并折叠
                    while True:
                        comma_at = _next_significant(tokens, i)
                        if comma_at is None or tokens[comma_at].token_type != TokenType.COMMA:
                            break
                        group_at = _next_significant(tokens, comma_at + 1)
                        if group_at is None or tokens[group_at].token_type != TokenType.L_PAREN:
                            break
                        i = _skip_paren_group(tokens, group_at)
                    continue
        text = token.text
        token_type = token.token_type
        if token_type in (
            TokenType.STRING,
            TokenType.NUMBER,
            TokenType.HEX_STRING,
            TokenType.NULL,
            TokenType.BIT_STRING,
        ):
            out.append("?")
        elif token_type in (TokenType.IDENTIFIER, TokenType.VAR):
            # 标识符保留（pt 口径只归一字面量）；小写 + 内嵌数字替换（users_2009 ≡ users_2010）
            bare = text.strip('`"').lower()
            out.append(_EMBEDDED_DIGITS.sub("?", bare))
        else:
            out.append(text.lower())
        i += 1
    return " ".join(out)


def _next_significant(tokens: list, start: int) -> int | None:
    for index in range(start, len(tokens)):
        if tokens[index].token_type != TokenType.COMMENT:
            return index
    return None


_VALUE_TOKENS = (TokenType.STRING, TokenType.NUMBER, TokenType.HEX_STRING, TokenType.NULL, TokenType.BIT_STRING)


def _is_value_list_head(token: object) -> bool:
    """括号组内首个有效 token 是否值形态：字面量 / 带符号数字 / 行构造器分组。

    子查询（SELECT 开头）不是值列表，不折叠——不同查询形态必须保持不同指纹。
    """
    token_type = token.token_type  # type: ignore[attr-defined]
    if token_type in _VALUE_TOKENS:
        return True
    if token_type in (TokenType.PLUS, TokenType.DASH):
        return True  # 带符号数字（IN (-1)）；非法 SQL 由此折叠亦无害
    return token_type == TokenType.L_PAREN  # 行构造器 VALUES ((1,2),(3,4))


def _skip_paren_group(tokens: list, open_index: int) -> int:
    """跳过从 open_index（L_PAREN）开始的配对括号组，返回组后第一个下标。"""
    depth = 0
    for index in range(open_index, len(tokens)):
        token_type = tokens[index].token_type
        if token_type == TokenType.L_PAREN:
            depth += 1
        elif token_type == TokenType.R_PAREN:
            depth -= 1
            if depth == 0:
                return index + 1
    return len(tokens)


def _fallback(sql: str) -> str:
    text = _EMBEDDED_DIGITS.sub("?", sql.lower())
    return " ".join(text.split())
