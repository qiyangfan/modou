"""回放器：把切分后的变更集语句在影子库上逐条执行。

- 单连接顺序执行，会话状态（USE 切库等）跨语句保持，与运维用客户端执行语义一致；
- autocommit，DDL/DML 即时生效，便于回放后内省；
- 首个失败语句即中止（期望态推导中止，spec 明确要求），产出序号 + 错误码 + 错误文本。
"""

from __future__ import annotations

from dataclasses import dataclass

import pymysql.connections
import pymysql.err


@dataclass
class ReplayError:
    statement_index: int  # 1 起全局序号，与 pack 预警序号同口径
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
                # pymysql 服务器错误恒为 (errno, message) 二元组，但防御分支自身
                # 不得对 len==1/len>=3 的畸形 args 再抛解包错误
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
