"""连接参数归一：CLI 与 MCP 表面共用的唯一实现（表面层零逻辑重复，ADR-0002）。

口令优先级（显式 > env）：--password flag > DSN 内嵌 > MOUDO_MYSQL_PASSWORD >
交互提示。DSN 是本次调用显式给出的复合参数，内嵌口令不得被环境状态静默覆盖
（libpq/mysql 客户端同款）；env 只兜底「DSN 未内嵌口令」。空口令是合法配置。

MCP 表面运行在 stdio 协议上：交互提示会污染协议流，必须以 allow_prompt=False
运行——口令缺失时直接报参数错误而非挂起等待输入。
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

import typer

from modou.db import MysqlParams

PASSWORD_ENV = "MOUDO_MYSQL_PASSWORD"


class PasswordUnavailableError(Exception):
    """口令缺失且不允许交互提示（MCP 场景），映射工具错误。"""


def resolve_params(
    dsn: str | None,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
    *,
    allow_prompt: bool = True,
) -> MysqlParams:
    """连接参数归一：DSN 为底，显式 flag 覆盖。allow_prompt=False 时缺失口令即报错。"""
    dsn_host, dsn_port, dsn_user, dsn_password = "127.0.0.1", 3306, "root", None
    if dsn is not None:
        parsed = urlparse(dsn if "://" in dsn else f"mysql://{dsn}")
        if parsed.scheme not in ("mysql", ""):
            raise ValueError(f"unsupported DSN scheme: {parsed.scheme} (expected mysql://)")
        dsn_host = parsed.hostname or dsn_host
        dsn_port = parsed.port or dsn_port
        dsn_user = unquote(parsed.username) if parsed.username else dsn_user
        # `mysql://user:@host` 的空口令是合法显式配置（MySQL 允许），is None 判别才不丢它
        dsn_password = unquote(parsed.password) if parsed.password is not None else None

    env_password = os.environ.get(PASSWORD_ENV)
    if password is not None:
        resolved_password: str | None = password
    elif dsn_password is not None:
        resolved_password = dsn_password
    elif env_password is not None:
        resolved_password = env_password
    elif allow_prompt:
        resolved_password = typer.prompt("MySQL password", hide_input=True)
    else:
        raise PasswordUnavailableError(
            "no password available: pass --password/DSN password or set MOUDO_MYSQL_PASSWORD "
            "(interactive prompt is unavailable in MCP mode)"
        )
    return MysqlParams(
        host=host or dsn_host,
        port=port or dsn_port,
        user=user or dsn_user,
        password=resolved_password or "",
    )
