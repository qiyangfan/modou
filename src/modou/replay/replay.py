"""在影子库单连接上按序执行变更集；会话状态跨语句保持，首条失败即停止。"""

from __future__ import annotations

from dataclasses import dataclass

import pymysql.connections
import pymysql.err


@dataclass
class ReplayError:
    statement_index: int  # 从 1 开始的全局序号，与 pack 预警一致
    sql: str
    error_code: int
    error_message: str


@dataclass
class ReplayResult:
    executed_count: int
    error: ReplayError | None = None


def replay_statements(conn: pymysql.connections.Connection, statements: list[str]) -> ReplayResult:
    """逐条执行语句；失败即中止并指认失败语句。"""
    executed = 0
    with conn.cursor() as cursor:
        for index, sql in enumerate(statements, start=1):
            try:
                cursor.execute(sql)
                executed = index
            except pymysql.err.MySQLError as exc:
                # 服务器错误通常是 (errno, message)；畸形 args 也不能再抛解包错误
                args = exc.args
                code = args[0] if args and isinstance(args[0], int) else 0
                message = str(args[1]) if len(args) > 1 else str(exc)
                return ReplayResult(
                    executed_count=executed,
                    error=ReplayError(
                        statement_index=index,
                        sql=sql,
                        error_code=int(code),
                        error_message=message,
                    ),
                )
    return ReplayResult(executed_count=executed)
