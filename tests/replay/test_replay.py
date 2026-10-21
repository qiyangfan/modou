"""回放器单测：MySQLError 解包防御与成功计数（真实服务器语义由容器集成覆盖）。"""

from __future__ import annotations

import contextlib

import pymysql.err

from modou.replay.replay import replay_statements


class _StubCursor:
    def __init__(self, script: list[Exception | None]) -> None:
        self._script = list(script)

    def execute(self, sql: str) -> None:
        outcome = self._script.pop(0)
        if outcome is not None:
            raise outcome

    def __enter__(self) -> _StubCursor:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class _StubConn:
    def __init__(self, cursor: _StubCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> contextlib.AbstractContextManager[_StubCursor]:
        return contextlib.nullcontext(self._cursor)


def test_non_int_first_arg_yields_code_zero() -> None:
    """客户端侧错误可能只有 message 一个参数，code 应归 0。"""
    conn = _StubConn(_StubCursor([pymysql.err.InternalError("just a message")]))
    result = replay_statements(conn, ["SELECT 1"])  # type: ignore[arg-type]
    assert result.executed_count == 0
    assert result.error is not None
    assert result.error.error_code == 0
    assert result.error.error_message == "just a message"


def test_standard_two_arg_error_keeps_code_and_message() -> None:
    conn = _StubConn(_StubCursor([None, pymysql.err.OperationalError(1064, "syntax error")]))
    result = replay_statements(conn, ["SELECT 1", "SELECT 2"])  # type: ignore[arg-type]
    assert result.executed_count == 1
    assert result.error is not None
    assert result.error.statement_index == 2
    assert result.error.error_code == 1064
    assert result.error.error_message == "syntax error"
