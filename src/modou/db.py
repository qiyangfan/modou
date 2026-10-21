"""MySQL 连接参数、连接创建与标识符转义。"""

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
    """用反引号包裹标识符，内部反引号写两次。"""
    return "`" + name.replace("`", "``") + "`"
