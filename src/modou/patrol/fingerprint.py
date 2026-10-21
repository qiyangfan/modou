"""把 SQL 归一为可聚合的查询指纹。

替换字面量与标识符中的数字，并折叠 IN/VALUES 值列表。
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot.tokens import TokenType

_EMBEDDED_DIGITS = re.compile(r"\d+")


def fingerprint(sql: str) -> str:
    """归一单条语句文本；词法失败时退化为纯文本归一。"""
    try:
        tokens = sqlglot.tokenize(sql, read="mysql")
    except sqlglot.errors.TokenError:
        tokens = []
        # 词法失败时退化为纯文本归一，仍可聚合但保真度低
        return _fallback(sql)

    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if token.token_type in (TokenType.COMMENT,):
            i += 1
            continue
        # IN/VALUES 的值列表整体折叠为一个占位符；IN (SELECT ...) 不是值列表，不能合并
        if token.token_type in (TokenType.IN, TokenType.VALUES):
            group_start = _next_significant(tokens, i + 1)
            if group_start is not None and tokens[group_start].token_type == TokenType.L_PAREN:
                head = _next_significant(tokens, group_start + 1)
                if head is not None and _is_value_list_head(tokens[head]):
                    out.append("?")
                    i = _skip_paren_group(tokens, group_start)
                    # 多值 INSERT 的后续 VALUES 分组一并折叠
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
            # 标识符保留并小写；内嵌数字替换，使 users_2009 与 users_2010 归为一类
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
    """判断括号组首个 token 是否为值形态；子查询不折叠，保持不同指纹。"""
    token_type = token.token_type  # type: ignore[attr-defined]
    if token_type in _VALUE_TOKENS:
        return True
    if token_type in (TokenType.PLUS, TokenType.DASH):
        return True  # 带符号数字（如 IN (-1)）；非法 SQL 折叠也无害
    return token_type == TokenType.L_PAREN  # 行构造器 VALUES ((1,2),(3,4))


def _skip_paren_group(tokens: list, open_index: int) -> int:
    """返回从 open_index 开始的配对括号组之后的下标。"""
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
