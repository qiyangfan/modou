"""归一 CLI 与 MCP 使用的 MySQL 连接参数。

口令优先级：``--password``、DSN 内嵌口令、``MOUDO_MYSQL_PASSWORD``、交互提示；空口令有效。
MCP 走 stdio，不允许交互提示，缺口令即报错。
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

import typer

from modou.db import MysqlParams

PASSWORD_ENV = "MOUDO_MYSQL_PASSWORD"


class PasswordUnavailableError(Exception):
    """缺失口令且不允许交互提示（MCP），映射为工具错误。"""


def resolve_params(
    dsn: str | None,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
    *,
    allow_prompt: bool = True,
) -> MysqlParams:
    """以 DSN 为底，显式参数覆盖；allow_prompt=False 时缺口令即报错。"""
    dsn_host, dsn_port, dsn_user, dsn_password = "127.0.0.1", 3306, "root", None
    if dsn is not None:
        parsed = urlparse(dsn if "://" in dsn else f"mysql://{dsn}")
        if parsed.scheme not in ("mysql", ""):
            raise ValueError(f"unsupported DSN scheme: {parsed.scheme} (expected mysql://)")
        dsn_host = parsed.hostname or dsn_host
        dsn_port = parsed.port or dsn_port
        dsn_user = unquote(parsed.username) if parsed.username else dsn_user
        # 空口令是合法显式配置，用 is None 判断以保留它
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
