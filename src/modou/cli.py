"""CLI 入口：子命令按车道逐步落位（pack/verify、optimize、lint、patrol），当前仅承载元信息。"""

import typer

from modou import __version__

app = typer.Typer(
    name="modou",
    help="墨斗：数据库工程化的本地层——变更验收、SQL 优化、规则审核、漂移洞察。",
    no_args_is_help=True,
)


# 单命令的 Typer app 会被当作单命令应用（子命令名变成参数），callback 强制子命令模式
@app.callback()
def main() -> None:
    """墨斗：数据库工程化的本地层——变更验收、SQL 优化、规则审核、漂移洞察。"""


@app.command()
def version() -> None:
    """输出版本号。"""
    typer.echo(f"modou {__version__}")


if __name__ == "__main__":
    app()
