"""MySQL 连接参数与连接工厂：快照采集、影子灌入、回放共用的薄封装。

仅承担「参数归一 + 建连」两件事，不含任何业务逻辑；标识符转义也在此提供，
供需要拼接 DDL 的场景（SHOW CREATE / CREATE DATABASE）统一使用。
"""

from __future__ import annotations

from dataclasses import dataclass

import pymysql


@dataclass(frozen=True)
class MysqlParams:
    host: str
    port: int
    user: str
    password: str

    def connect(
        self, *, database: str | None = None, autocommit: bool = True, connect_timeout: int = 10
    ) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=database,
            autocommit=autocommit,
            charset="utf8mb4",
            connect_timeout=connect_timeout,
        )


def quote_ident(name: str) -> str:
    """MySQL 标识符转义：反引号内连续两个反引号表示字面反引号。"""
    return "`" + name.replace("`", "``") + "`"
